"""Build pairs.csv from REAL labelled reports.

items.csv columns (one row per report):
  group_id   same value for the lost report and found report of the SAME physical object
  role       LOST or FOUND
  category   one of the app categories, e.g. BAG
  title, description, location
  hours      hours since the first report of that group (0 for the lost one)
  image_path optional path to the photo

Collect it by having teammates photograph 50-100 everyday objects twice (different angle/background) and
write a short lost-style and found-style description each. Add 30-50 'orphan' rows with unique group_ids too:
they become the negatives.

Usage:  python pairs_from_items.py items.csv --out data/pairs_real.csv [--embed]
--embed is OPTIONAL and not used by the live matcher (see README): it needs torch + transformers
(pip install -r ../legacy-aws/extractor/requirements.txt torch).
"""
import argparse
import csv
import os
import random
import sys

from pairs_common import HERE, matcher, write_pairs

BASE = 1_800_000_000_000
H = 3_600_000


def load_items(path, embed):
    if embed:
        sys.path.insert(0, os.path.join(HERE, "..", "legacy-aws", "extractor"))
        import features  # noqa: PLC0415
    items = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            embedding = None
            if embed and row.get("image_path"):
                with open(row["image_path"], "rb") as img:
                    embedding = matcher.encode_embedding(features.embed(img.read()))
            items.append((row["group_id"], {
                "type": row["role"].upper(), "title": row["title"], "description": row.get("description", ""),
                "category": row["category"], "location": row["location"],
                "occurredAt": BASE + int(float(row.get("hours") or 0) * H), "embedding": embedding,
            }))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items_csv")
    ap.add_argument("--out", default="data/pairs_real.csv")
    ap.add_argument("--embed", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    items = load_items(args.items_csv, args.embed)
    groups = sorted({g for g, _ in items})
    rng.shuffle(groups)
    split_of = {g: ("train" if i < 0.6 * len(groups) else "val" if i < 0.8 * len(groups) else "test")
                for i, g in enumerate(groups)}

    lost = [(g, i) for g, i in items if i["type"] == "LOST"]
    found = [(g, i) for g, i in items if i["type"] == "FOUND"]
    rows = []
    for lg, li in lost:
        for fg, fi in found:
            if split_of[lg] != split_of[fg]:
                continue
            feats = matcher.features(li, fi)
            if feats is not None:
                rows.append((split_of[lg], feats, 1 if lg == fg else 0))
    write_pairs(args.out, rows)
    # True matches the hard rules throw away before the model ever sees them (no shared word, wrong category...).
    true_total = len({g for g, _ in lost} & {g for g, _ in found})
    true_kept = sum(1 for _, _, label in rows if label == 1)
    print(f"wrote {len(rows)} pairs to {args.out}")
    print(f"true matches: {true_total}; passing the hard rules: {true_kept} "
          f"({true_kept / max(true_total, 1):.0%}) - the rest can never be suggested")


if __name__ == "__main__":
    main()
