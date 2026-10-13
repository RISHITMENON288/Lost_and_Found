import unittest

from lf import validation as v

NOW = 1_800_000_000_000
SUB = "user-123"
KEY = "uploads/user-123/123e4567-e89b-12d3-a456-426614174000.jpg"


def good(**over):
    body = {"type": "LOST", "title": "Black bag", "category": "BAG", "description": "Shoulder bag",
            "location": "Library", "occurredAt": NOW - 1000}
    body.update(over)
    return body


class ValidationTest(unittest.TestCase):
    def test_accepts_valid(self):
        out = v.validate_new_item(good(imageKey=KEY), SUB, NOW)
        self.assertEqual("Black bag", out["title"])
        self.assertEqual(KEY, out["imageKey"])

    def test_rejects_bad_fields(self):
        bad = [
            good(type="STOLEN"), good(category="CARS"), good(location="Moon"), good(title="ab"),
            good(title="x" * 61), good(description="x" * 301), good(occurredAt=NOW + 10 * 60 * 1000),
            good(occurredAt=NOW - 400 * 86_400_000), good(occurredAt="yesterday"), good(occurredAt=True),
            good(title=123),
        ]
        for body in bad:
            with self.assertRaises(v.ValidationError, msg=str(body)):
                v.validate_new_item(body, SUB, NOW)

    def test_image_key_must_belong_to_user(self):
        for key in ("uploads/other/123e4567-e89b-12d3-a456-426614174000.jpg", "../etc/passwd", KEY + ".exe", 5):
            with self.assertRaises(v.ValidationError):
                v.validate_new_item(good(imageKey=key), SUB, NOW)

    def test_control_characters_stripped(self):
        out = v.validate_new_item(good(title="Bla\x00ck bag"), SUB, NOW)
        self.assertEqual("Black bag", out["title"])

    def test_body_must_be_object(self):
        with self.assertRaises(v.ValidationError):
            v.validate_new_item([], SUB, NOW)


if __name__ == "__main__":
    unittest.main()
