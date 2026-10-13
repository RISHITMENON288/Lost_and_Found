"""Honest evaluation on a small dataset: repeated k-fold cross-validation BY OBJECT GROUP.

One train/test split of ~200 reports leaves only ~15 true matches in the test part, so a single run is mostly luck.
Here every group is tested several times; the totals are over all folds and all repeats.

Usage:  python cross_validate.py data/items.csv [--repeats 20] [--target-precision 0.95]
"""
import argparse
import random

import numpy as np
from pairs_common import matcher
from pairs_from_items import load_items
from sklearn.linear_model import LogisticRegression
from train_scorer import NAMES, baseline_probs, metrics, pick_threshold


def build_pairs(items):
    lost = [(g, i) for g, i in items if i["type"] == "LOST"]
    found = [(g, i) for g, i in items if i["type"] == "FOUND"]
    pairs = []
    for lg, li in lost:
        for fg, fi in found:
            f = matcher.features(li, fi)
            if f is not None:
                pairs.append((lg, fg, [f[n] for n in NAMES], 1 if lg == fg else 0))
    return pairs


def select(pairs, groups):
    sel = [p for p in pairs if p[0] in groups and p[1] in groups]
    return np.array([p[2] for p in sel]), np.array([p[3] for p in sel])


def add(total, m):
    for k in ("tp", "fp", "fn", "tn"):
        total[k] += m[k]


def summary(t):
    p = t["tp"] / max(t["tp"] + t["fp"], 1)
    r = t["tp"] / max(t["tp"] + t["fn"], 1)
    return p, r, 2 * p * r / max(p + r, 1e-9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items_csv")
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--target-precision", type=float, default=0.95)
    args = ap.parse_args()

    items = load_items(args.items_csv, embed=False)
    pairs = build_pairs(items)
    all_groups = sorted({g for g, _ in items})
    learned = dict.fromkeys(("tp", "fp", "fn", "tn"), 0)
    hand = dict(learned)
    for rep in range(args.repeats):
        rng = random.Random(rep)
        order = all_groups[:]
        rng.shuffle(order)
        for k in range(args.folds):
            test = set(order[k::args.folds])
            rest = [g for g in order if g not in test]
            val = set(rest[: len(rest) // 4])
            train = set(rest) - val
            xtr, ytr = select(pairs, train)
            xva, yva = select(pairs, val)
            xte, yte = select(pairs, test)
            if ytr.sum() == 0 or yva.sum() == 0 or len(yte) == 0:
                continue
            clf = LogisticRegression(C=1.0, max_iter=2000).fit(xtr, ytr)
            threshold, _ = pick_threshold(yva, clf.predict_proba(xva)[:, 1], args.target_precision)
            add(learned, metrics(yte, (clf.predict_proba(xte)[:, 1] >= threshold).astype(int)))
            add(hand, metrics(yte, (baseline_probs(xte) >= matcher.DEFAULT_THRESHOLD).astype(int)))

    print(f"{args.repeats} repeats x {args.folds} folds, target precision {args.target_precision}")
    print("| Scorer | Precision | Recall | F1 | False positives | Missed matches |")
    print("|---|---|---|---|---|---|")
    for name, t in (("Learned logistic", learned), (f"Hand-set weights (>= {matcher.DEFAULT_THRESHOLD})", hand)):
        p, r, f1 = summary(t)
        print(f"| {name} | {p:.3f} | {r:.3f} | {f1:.3f} | {t['fp']} | {t['fn']} |")


if __name__ == "__main__":
    main()
