"""Fit the final scorer on ALL labelled data and pick its decision threshold honestly.

1. Out-of-fold probabilities: every pair is scored by a model that never saw either of its two objects
   (repeated, by object group). Nothing is graded on data it was trained on.
2. The threshold is the lowest one whose out-of-fold precision reaches --target-precision.
3. The final model is then fitted on everything and written to out/weights.json + out/install_model.sql.

Usage:  python fit_final.py data/items.csv [--target-precision 0.95]
"""
import argparse
import itertools
import json
import os
import random

import numpy as np
from cross_validate import build_pairs
from pairs_common import matcher
from pairs_from_items import load_items
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from train_scorer import NAMES, baseline_probs, metrics

FOLDS = 5


def out_of_fold(pairs, x, y, groups, rep):
    order = groups[:]
    random.Random(rep).shuffle(order)
    fold = {g: i % FOLDS for i, g in enumerate(order)}
    prob = np.zeros(len(pairs))
    for a, b in itertools.combinations_with_replacement(range(FOLDS), 2):
        train = [i for i, p in enumerate(pairs) if fold[p[0]] not in (a, b) and fold[p[1]] not in (a, b)]
        test = [i for i, p in enumerate(pairs) if {fold[p[0]], fold[p[1]]} == {a, b}]
        if test:
            prob[test] = LogisticRegression(C=1.0, max_iter=2000).fit(x[train], y[train]).predict_proba(x[test])[:, 1]
    return prob


def lowest_threshold(y, prob, target):
    for t in np.arange(0.05, 0.995, 0.005):
        m = metrics(y, (prob >= t).astype(int))
        if m["precision"] >= target and m["tp"] > 0:
            return float(t)
    return 0.99


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items_csv")
    ap.add_argument("--out", default="out")
    ap.add_argument("--target-precision", type=float, default=0.95)
    ap.add_argument("--repeats", type=int, default=10)
    args = ap.parse_args()

    items = load_items(args.items_csv, embed=False)
    pairs = build_pairs(items)
    groups = sorted({g for g, _ in items})
    x = np.array([p[2] for p in pairs])
    y = np.array([p[3] for p in pairs])
    total_true = len({g for g, i in items if i["type"] == "LOST"} & {g for g, i in items if i["type"] == "FOUND"})

    runs = [out_of_fold(pairs, x, y, groups, rep) for rep in range(args.repeats)]
    thresholds = [lowest_threshold(y, p, args.target_precision) for p in runs]
    threshold = float(np.median(thresholds))
    learned = [metrics(y, (p >= threshold).astype(int)) for p in runs]
    hand_prob = baseline_probs(x)
    hand_default = metrics(y, (hand_prob >= matcher.DEFAULT_THRESHOLD).astype(int))
    hand_matched = metrics(y, (hand_prob >= lowest_threshold(y, hand_prob, args.target_precision)).astype(int))

    clf = LogisticRegression(C=1.0, max_iter=2000).fit(x, y)
    model = {
        "type": "logistic",
        "bias": float(clf.intercept_[0]),
        "weights": {n: float(w) for n, w in zip(NAMES, clf.coef_[0], strict=True)},
        "threshold": round(threshold, 3),
        "trainedOn": {"pairs": int(len(y)), "trueMatches": int(y.sum()), "reports": len(items),
                      "synthetic": False, "targetPrecision": args.target_precision},
    }
    assert matcher.validate_model(model) is not None

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "weights.json"), "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    compact = json.dumps(model, separators=(",", ":"))
    with open(os.path.join(args.out, "install_model.sql"), "w", encoding="utf-8") as f:
        f.write("-- Paste into the Supabase SQL Editor and run.\n")
        f.write("-- Undo: update public.match_settings set model = null where id = 1;\n")
        f.write(f"update public.match_settings set model = $json${compact}$json$::jsonb where id = 1;\n")  # noqa: S608

    mean = {k: float(np.mean([m[k] for m in learned])) for k in ("precision", "recall", "fp", "fn")}
    ap_learned = float(np.mean([average_precision_score(y, p) for p in runs]))
    lines = [
        "# Scorer evaluation", "",
        f"Data: {len(items)} reports ({int(total_true)} true lost/found pairs, the rest unmatched). "
        f"{int(y.sum())} of the {int(total_true)} true pairs pass the hard rules; the other "
        f"{int(total_true - y.sum())} can never be suggested. {len(y)} candidate pairs are scored.",
        "Every number below is out-of-fold: a pair is scored by a model that never saw either of its objects.", "",
        f"Ranking quality (average precision): learned {ap_learned:.3f} vs hand-set weights "
        f"{average_precision_score(y, hand_prob):.3f}.", "",
        "| Scorer | Threshold | Precision | Recall | False suggestions | Missed matches |", "|---|---|---|---|---|---|",
        f"| Hand-set weights (current default) | {matcher.DEFAULT_THRESHOLD} | {hand_default['precision']} | "
        f"{hand_default['recall']} | {hand_default['fp']} | {hand_default['fn']} |",
        f"| Hand-set weights, threshold raised to hit the target | "
        f"{lowest_threshold(y, hand_prob, args.target_precision):.2f} | {hand_matched['precision']} | "
        f"{hand_matched['recall']} | {hand_matched['fp']} | {hand_matched['fn']} |",
        f"| Learned logistic (this model, mean of {args.repeats} shuffles) | {model['threshold']} | "
        f"{mean['precision']:.3f} | {mean['recall']:.3f} | {mean['fp']:.1f} | {mean['fn']:.1f} |", "",
        "Weights: " + json.dumps({k: round(v, 3) for k, v in model["weights"].items()}) + f", bias {model['bias']:.3f}",
    ]
    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
