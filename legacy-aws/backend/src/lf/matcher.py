"""Hybrid lost/found scoring.

Hard gates keep false positives down (score 0 if any fails):
  * one LOST and one FOUND report, same category
  * found no more than a day before lost
  * at least one shared word in title/description

Then a score in [0, 1]:
  * default (hand-set) weights, or
  * a logistic model trained by ml/train_scorer.py and shipped as weights.json
    (plain JSON, never pickle, so loading it cannot execute code).

Photo similarity is used only when both reports have a photo:
  * labels from Amazon Rekognition (e.g. "backpack", "bag"): Dice overlap of the two label sets, or
  * CLIP embeddings (optional extractor): cosine similarity.
"""
import math
import re
from array import array

DAY_MS = 86_400_000
MAX_GAP_DAYS = 7.0
DEFAULT_THRESHOLD = 0.60

STOP_WORDS = frozenset(
    "the and with has have was were near from for this that there found lost left "
    "some very into onto its are not but inside side".split()
)

FEATURE_NAMES = ("text", "location", "time", "image", "has_image")


def tokens(text):
    parts = re.split(r"[^a-z0-9]+", (text or "").lower())
    return {p for p in parts if len(p) > 2 and p not in STOP_WORDS}


def text_similarity(a, b):
    """Dice coefficient over word sets."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return 2.0 * len(ta & tb) / (len(ta) + len(tb))


def label_similarity(a, b):
    """Dice coefficient over two lists of photo labels (0 when either list is empty)."""
    sa, sb = {str(x).lower() for x in a or ()}, {str(x).lower() for x in b or ()}
    if not sa or not sb:
        return 0.0
    return 2.0 * len(sa & sb) / (len(sa) + len(sb))


def encode_embedding(values):
    arr = array("f", values)
    return arr.tobytes()


def decode_embedding(blob):
    if not blob:
        return None
    arr = array("f")
    arr.frombytes(bytes(blob))
    return list(arr)


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _text_of(item):
    return "{} {}".format(item.get("title", ""), item.get("description", ""))


def features(lost, found):
    """Feature dict, or None if a hard gate fails."""
    if lost.get("type") != "LOST" or found.get("type") != "FOUND":
        return None
    if lost.get("category") != found.get("category"):
        return None
    if found["occurredAt"] + DAY_MS < lost["occurredAt"]:
        return None

    text = text_similarity(_text_of(lost), _text_of(found))
    if text <= 0.0:
        return None

    same_place = 1.0 if str(lost.get("location", "")).lower() == str(found.get("location", "")).lower() else 0.0
    gap_days = abs(found["occurredAt"] - lost["occurredAt"]) / DAY_MS
    closeness = max(0.0, 1.0 - min(gap_days / MAX_GAP_DAYS, 1.0))

    ea, eb = decode_embedding(lost.get("embedding")), decode_embedding(found.get("embedding"))
    if ea and eb:
        # CLIP cosine of two photos of the same object is typically 0.8-0.95, unrelated objects ~0.5-0.75.
        image = max(0.0, min((cosine(ea, eb) - 0.5) / 0.5, 1.0))
        has_image = 1.0
    elif lost.get("imageLabels") and found.get("imageLabels"):
        image = label_similarity(lost["imageLabels"], found["imageLabels"])
        has_image = 1.0
    else:
        image, has_image = 0.0, 0.0

    return {"text": text, "location": same_place, "time": closeness, "image": image, "has_image": has_image}


def _default_score(f):
    if f["has_image"]:
        return 0.10 + 0.25 * f["text"] + 0.15 * f["location"] + 0.10 * f["time"] + 0.40 * f["image"]
    return 0.20 + 0.45 * f["text"] + 0.20 * f["location"] + 0.15 * f["time"]


def _sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def validate_model(model):
    """Return model if it is a well-formed logistic model, else None."""
    try:
        if not isinstance(model, dict) or model.get("type") != "logistic":
            return None
        weights = model["weights"]
        for name in FEATURE_NAMES:
            float(weights[name])
        float(model["bias"])
        float(model.get("threshold", DEFAULT_THRESHOLD))
        return model
    except (KeyError, TypeError, ValueError):
        return None


def score(lost, found, model=None):
    f = features(lost, found)
    if f is None:
        return 0.0
    model = validate_model(model)
    if model is None:
        return _default_score(f)
    z = float(model["bias"]) + sum(float(model["weights"][n]) * f[n] for n in FEATURE_NAMES)
    return _sigmoid(z)


def threshold(model=None):
    model = validate_model(model)
    return float(model.get("threshold", DEFAULT_THRESHOLD)) if model else DEFAULT_THRESHOLD


def is_match(value, model=None):
    return value >= threshold(model)
