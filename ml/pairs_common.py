"""Shared helpers. lf_matcher.py is the Python reference of the scoring that runs inside the database
(supabase/schema.sql); supabase/tests/test_schema.py proves both give the same numbers, so features computed
for training are the features used when serving."""
import csv
import os

import lf_matcher as matcher

HERE = os.path.dirname(os.path.abspath(__file__))

COLUMNS = ["split", *matcher.FEATURE_NAMES, "label"]


def write_pairs(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for split, feats, label in rows:
            writer.writerow([split, *(round(feats[n], 6) for n in matcher.FEATURE_NAMES), label])


def read_pairs(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
