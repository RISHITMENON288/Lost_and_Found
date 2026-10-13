"""Train the pair scorer and write out/weights.json (plain JSON, never pickle) + an evaluation report.

Because a wrong "this is yours" suggestion is worse than a missed one, the decision threshold is chosen on the
validation split as the LOWEST-risk point that still reaches --target-precision, then reported on the untouched
test split next to the hand-set baseline scorer.
"""
import argparse
import json
import math
import os

import numpy as np
from pairs_common import matcher, read_pairs
from sklearn.linear_model import LogisticRegression

NAMES = list(matcher.FEATURE_NAMES)


def load(rows, split):
    sel = [r for r in rows if r["split"] == split]
    x = np.array([[float(r[n]) for n in NAMES] for r in sel])
    y = np.array([int(r["label"]) for r in sel])
    return x, y


def metrics(y, pred):
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "accuracy": round((tp + tn) / max(len(y), 1), 4)}


def pick_threshold(y, prob, target_precision):
    best = None
    for t in np.arange(0.05, 0.995, 0.005):
        m = metrics(y, (prob >= t).astype(int))
        if m["precision"] >= target_precision and m["tp"] > 0 and (best is None or m["recall"] > best[1]["recall"]):
            best = (float(t), m)
    if best is None:  # target unreachable: fall back to the most precise threshold that still finds something
        scored = [(metrics(y, (prob >= t).astype(int)), float(t)) for t in np.arange(0.05, 0.995, 0.005)]
        scored = [s for s in scored if s[0]["tp"] > 0] or scored
        m, t = max(scored, key=lambda s: (s[0]["precision"], s[0]["recall"]))
        best = (t, m)
    return best


def baseline_probs(x):
    out = []
    for row in x:
        out.append(matcher._default_score(dict(zip(NAMES, row, strict=True))))  # noqa: SLF001
    return np.array(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="data/pairs_synthetic.csv")
    ap.add_argument("--out", default="out")
    ap.add_argument("--target-precision", type=float, default=0.95)
    ap.add_argument("--synthetic", action="store_true", help="mark the report as based on synthetic data")
    args = ap.parse_args()

    rows = read_pairs(args.pairs)
    xtr, ytr = load(rows, "train")
    xva, yva = load(rows, "val")
    xte, yte = load(rows, "test")
    if min(len(ytr), len(yva), len(yte)) == 0 or ytr.sum() == 0:
        raise SystemExit("Need train/val/test splits that each contain pairs, with some positives in train.")

    clf = LogisticRegression(C=1.0, max_iter=2000).fit(xtr, ytr)
    threshold, val_metrics = pick_threshold(yva, clf.predict_proba(xva)[:, 1], args.target_precision)

    test_prob = clf.predict_proba(xte)[:, 1]
    learned = metrics(yte, (test_prob >= threshold).astype(int))
    base_threshold = matcher.DEFAULT_THRESHOLD
    baseline = metrics(yte, (baseline_probs(xte) >= base_threshold).astype(int))

    model = {
        "type": "logistic",
        "bias": float(clf.intercept_[0]),
        "weights": {n: float(w) for n, w in zip(NAMES, clf.coef_[0], strict=True)},
        "threshold": round(threshold, 3),
        "trainedOn": {"train": int(len(ytr)), "val": int(len(yva)), "test": int(len(yte)),
                      "synthetic": bool(args.synthetic), "targetPrecision": args.target_precision},
    }
    assert matcher.validate_model(model) is not None

    # parity check: the runtime formula must reproduce sklearn's probabilities exactly
    for row, p in list(zip(xte, test_prob, strict=True))[:200]:
        z = model["bias"] + sum(model["weights"][n] * v for n, v in zip(NAMES, row, strict=True))
        assert math.isclose(1 / (1 + math.exp(-z)), p, abs_tol=1e-9)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "weights.json"), "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    report = {"threshold": model["threshold"], "validation": val_metrics, "test_learned": learned,
              "test_baseline_hand_weights": baseline, "baseline_threshold": base_threshold,
              "positives_in_test": int(yte.sum()), "pairs_in_test": int(len(yte)), "synthetic": bool(args.synthetic)}
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    note = "\n> **Synthetic data:** these numbers only prove the pipeline runs. Do not quote them as real accuracy.\n" \
        if args.synthetic else ""
    md = ["# Scorer evaluation (held-out test split)", note,
          "Test pairs: {} ({} true matches).  Learned threshold: {}.\n".format(
              len(yte), int(yte.sum()), model["threshold"]),
          "| Scorer | Precision | Recall | F1 | False positives | False negatives |", "|---|---|---|---|---|---|",
          "| Learned logistic | {precision} | {recall} | {f1} | {fp} | {fn} |".format(**learned),
          "| Hand-set weights (>= {}) | {precision} | {recall} | {f1} | {fp} | {fn} |".format(
              base_threshold, **baseline),
          "\nWeights: " + json.dumps({k: round(v, 3) for k, v in model["weights"].items()}) +
          ", bias {:.3f}".format(model["bias"])]
    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
