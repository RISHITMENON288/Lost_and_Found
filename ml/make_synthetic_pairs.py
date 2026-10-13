"""Generate SYNTHETIC lost/found data so the training pipeline can be run and tested end to end.

The numbers it produces say nothing about real-world accuracy. Replace it with real data
(see pairs_from_items.py) before quoting any metric in a report.

Image embeddings are simulated: embedding = normalise(a*category_vec + b*object_vec + c*noise), which gives
~0.90 cosine for two photos of the same object and ~0.62 for different objects of one category, similar to CLIP.
"""
import argparse
import math
import random

from pairs_common import matcher, write_pairs

NOUNS = {
    "ELECTRONICS": ["earbuds case", "phone charger", "power bank", "smartphone", "laptop charger", "headphones",
                    "pen drive"],
    "BAG": ["backpack", "laptop bag", "sling bag", "duffel bag", "tote bag", "pouch"],
    "CLOTHING": ["hoodie", "jacket", "scarf", "cap", "sports shoes", "sweatshirt"],
    "ACCESSORY": ["wrist watch", "spectacles", "bracelet", "ring", "sunglasses", "belt"],
    "STATIONERY": ["calculator", "notebook", "textbook", "pencil box", "geometry box", "record book"],
    "KEYS": ["room keys", "bike key", "key bunch", "padlock key"],
    "CONTAINER": ["water bottle", "lunch box", "flask", "tiffin"],
    "DOCUMENTS": ["student id card", "wallet", "debit card", "library card"],
    "SPORTS": ["cricket bat", "badminton racket", "football", "skipping rope", "shuttle box"],
    "TOYS": ["rubiks cube", "card game", "chess set", "fidget spinner"],
}
COLORS = ["black", "blue", "red", "white", "grey", "green", "silver", "brown", "pink", "yellow"]
BRANDS = ["Dell", "HP", "Apple", "Samsung", "Boat", "Sony", "Nike", "Adidas", "Casio", "Milton", "Wildcraft", "Skybags"]
MARKS = ["scratched back", "sticker on the side", "small crack", "name tag", "keychain attached", "worn straps",
         "torn corner", "coffee stain"]
NOISE = ["found on a bench", "left unattended", "looks quite new", "was lying near the stairs", "someone dropped it"]
SYNONYMS = {"backpack": "bag", "earbuds case": "earphones case", "smartphone": "mobile phone", "wrist watch": "watch",
            "water bottle": "bottle", "student id card": "id card", "laptop bag": "laptop backpack"}
LOCATIONS = ["Library", "Main Gate", "Academic Block", "Cafeteria", "Hostel Area", "Sports Ground", "Auditorium",
             "Parking", "Other"]
H = 3_600_000
DIM = 512


def unit(vec):
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def gauss_vec(rng):
    return [rng.gauss(0, 1) for _ in range(DIM)]


def make_embedding(rng, category_vec, object_vec):
    return matcher.encode_embedding(unit([0.75 * c + 0.50 * o + 0.30 * n
                                          for c, o, n in zip(category_vec, object_vec, gauss_vec(rng), strict=True)]))


def make_object(rng, category):
    return {
        "category": category,
        "noun": rng.choice(NOUNS[category]),
        "color": rng.choice(COLORS),
        "brand": rng.choice(BRANDS) if rng.random() < 0.5 else None,
        "mark": rng.choice(MARKS) if rng.random() < 0.5 else None,
    }


def describe(rng, obj, noisy):
    noun = obj["noun"]
    if noisy and noun in SYNONYMS and rng.random() < 0.4:
        noun = SYNONYMS[noun]
    parts = [obj["color"]] if not (noisy and rng.random() < 0.15) else []
    if obj["brand"] and not (noisy and rng.random() < 0.35):
        parts.append(obj["brand"])
    title = " ".join([*parts, noun])
    desc = []
    if obj["mark"] and not (noisy and rng.random() < 0.4):
        desc.append(obj["mark"])
    if noisy and rng.random() < 0.5:
        desc.append(rng.choice(NOISE))
    return title, ", ".join(desc)


def build_item(rng, kind, obj, at, location, embedding, noisy):
    title, desc = describe(rng, obj, noisy)
    return {"type": kind, "title": title, "description": desc, "category": obj["category"], "location": location,
            "occurredAt": int(at), "embedding": embedding}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/pairs_synthetic.csv")
    ap.add_argument("--groups", type=int, default=400, help="real lost+found pairs")
    ap.add_argument("--orphans", type=int, default=250, help="extra unmatched lost and found reports each")
    ap.add_argument("--image-rate", type=float, default=0.6)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    category_vecs = {c: gauss_vec(rng) for c in NOUNS}
    base = 1_800_000_000_000
    lost_items, found_items = [], []   # (group_id, split, item)

    def split_for():
        r = rng.random()
        return "train" if r < 0.6 else "val" if r < 0.8 else "test"

    def maybe_embedding(obj_vec, cat):
        return make_embedding(rng, category_vecs[cat], obj_vec) if rng.random() < args.image_rate else None

    gid = 0
    for _ in range(args.groups):
        cat = rng.choice(list(NOUNS))
        obj = make_object(rng, cat)
        obj_vec = gauss_vec(rng)
        t0 = base + rng.uniform(0, 30 * 24) * H
        place = rng.choice(LOCATIONS)
        split = split_for()
        lost_items.append((gid, split, build_item(rng, "LOST", obj, t0, place, maybe_embedding(obj_vec, cat), False)))
        found_place = place if rng.random() < 0.65 else rng.choice(LOCATIONS)
        found_items.append((gid, split, build_item(rng, "FOUND", obj, t0 + rng.uniform(0, 72) * H, found_place,
                                                   maybe_embedding(obj_vec, cat), True)))
        gid += 1
    for kind, bucket in (("LOST", lost_items), ("FOUND", found_items)):
        for _ in range(args.orphans):
            cat = rng.choice(list(NOUNS))
            obj = make_object(rng, cat)
            obj_vec = gauss_vec(rng)
            t0 = base + rng.uniform(0, 30 * 24) * H
            bucket.append((gid, split_for(), build_item(rng, kind, obj, t0, rng.choice(LOCATIONS),
                                                        maybe_embedding(obj_vec, cat), kind == "FOUND")))
            gid += 1

    rows = []
    for lg, lsplit, lost in lost_items:
        for fg, fsplit, found in found_items:
            if lsplit != fsplit:
                continue  # never mix splits: no leakage between train and test
            feats = matcher.features(lost, found)
            if feats is None:
                continue  # hard gates already reject these at serving time
            rows.append((lsplit, feats, 1 if lg == fg else 0))
    write_pairs(args.out, rows)
    pos = sum(r[2] for r in rows)
    print(f"wrote {len(rows)} pairs ({pos} positive, {len(rows) - pos} negative) to {args.out}")


if __name__ == "__main__":
    main()
