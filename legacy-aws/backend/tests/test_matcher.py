import unittest

from lf import matcher

H = 3_600_000
NOW = 1_800_000_000_000


def item(type_, title, desc="", category="BAG", location="Library", at=NOW, embedding=None):
    return {"type": type_, "title": title, "description": desc, "category": category,
            "location": location, "occurredAt": at, "embedding": embedding}


class MatcherTest(unittest.TestCase):
    def test_strong_match_suggested(self):
        lost = item("LOST", "Black laptop bag", "Black backpack with Dell charger")
        found = item("FOUND", "Black laptop bag with charger", "Black backpack, Dell charger inside", at=NOW + 3 * H)
        s = matcher.score(lost, found)
        self.assertTrue(matcher.is_match(s), s)

    def test_different_category_never_matches(self):
        self.assertEqual(0.0, matcher.score(item("LOST", "Black laptop bag"), item("FOUND", "Black laptop bag", category="ELECTRONICS")))

    def test_no_shared_words_never_matches(self):
        self.assertEqual(0.0, matcher.score(item("LOST", "Black laptop bag"), item("FOUND", "Umbrella", "Folding rain cover")))

    def test_found_long_before_lost_rejected(self):
        self.assertEqual(0.0, matcher.score(item("LOST", "Black laptop bag", at=NOW), item("FOUND", "Black laptop bag", at=NOW - 48 * H)))

    def test_wrong_types_score_zero(self):
        self.assertEqual(0.0, matcher.score(item("LOST", "Black laptop bag"), item("LOST", "Black laptop bag")))

    def test_weak_overlap_far_apart_not_suggested(self):
        lost = item("LOST", "Black bag", "Small shoulder bag", location="Library")
        found = item("FOUND", "Black duffel bag", "Large gym duffel with zip pockets", location="Parking", at=NOW + 120 * H)
        self.assertFalse(matcher.is_match(matcher.score(lost, found)))

    def test_image_similarity_raises_score(self):
        v = [1.0] + [0.0] * 511
        same = matcher.encode_embedding(v)
        other = matcher.encode_embedding([0.0, 1.0] + [0.0] * 510)
        lost = item("LOST", "Black bag", "Shoulder bag", embedding=same)
        base = item("FOUND", "Black bag", "Shoulder bag", location="Parking", embedding=same)
        diff = item("FOUND", "Black bag", "Shoulder bag", location="Parking", embedding=other)
        self.assertGreater(matcher.score(lost, base), matcher.score(lost, diff))

    def test_photo_labels_raise_and_lower_the_score(self):
        bag = ["backpack", "bag", "black"]
        lost = item("LOST", "Black bag", "Shoulder bag")
        lost["imageLabels"] = bag
        plain = item("FOUND", "Black bag", "Shoulder bag", location="Parking")
        same = {**plain, "imageLabels": ["backpack", "bag", "luggage"]}
        other = {**plain, "imageLabels": ["bottle", "cup"]}
        model = {"type": "logistic", "bias": -6.4185, "threshold": 0.57,
                 "weights": {"text": 5.904, "location": 1.5074, "time": 2.5542, "image": 3.0, "has_image": -0.5}}
        self.assertGreater(matcher.score(lost, same, model), matcher.score(lost, plain, model))
        self.assertLess(matcher.score(lost, other, model), matcher.score(lost, plain, model))

    def test_label_similarity(self):
        self.assertEqual(1.0, matcher.label_similarity(["Bag", "backpack"], ["backpack", "bag"]))
        self.assertEqual(0.0, matcher.label_similarity(["bag"], ["cup"]))
        self.assertEqual(0.0, matcher.label_similarity([], ["cup"]))
        self.assertAlmostEqual(0.5, matcher.label_similarity(["a", "b"], ["b", "c"]))

    def test_embedding_roundtrip(self):
        values = [0.25, -0.5, 1.0]
        self.assertEqual(values, matcher.decode_embedding(matcher.encode_embedding(values)))

    def test_learned_model_is_used_and_validated(self):
        lost = item("LOST", "Black laptop bag", "Black backpack")
        found = item("FOUND", "Black laptop bag", "Black backpack")
        model = {"type": "logistic", "bias": -10.0, "threshold": 0.5,
                 "weights": {"text": 0.0, "location": 0.0, "time": 0.0, "image": 0.0, "has_image": 0.0}}
        self.assertLess(matcher.score(lost, found, model), 0.01)
        self.assertEqual(0.5, matcher.threshold(model))
        broken = {"type": "pickle", "weights": {}}
        self.assertIsNone(matcher.validate_model(broken))
        self.assertEqual(matcher.DEFAULT_THRESHOLD, matcher.threshold(broken))


if __name__ == "__main__":
    unittest.main()
