"""Input validation for everything that arrives from the app. Nothing is trusted."""
import re

from . import constants as C

DAY_MS = 86_400_000


class ValidationError(Exception):
    pass


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def clean_text(value, name, min_len, max_len, required=True):
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be text")
    value = _CONTROL.sub("", value).strip()
    if len(value) < min_len:
        raise ValidationError(f"{name} is too short")
    if len(value) > max_len:
        raise ValidationError(f"{name} is too long (max {max_len})")
    return value


def image_key_pattern(sub):
    return re.compile(rf"^uploads/{re.escape(sub)}/{_UUID}\.jpg$")


def validate_new_item(body, sub, now_ms):
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object")

    item_type = body.get("type")
    if item_type not in C.TYPES:
        raise ValidationError("type must be LOST or FOUND")

    category = body.get("category")
    if category not in C.CATEGORIES:
        raise ValidationError("Unknown category")

    location = body.get("location")
    if location not in C.LOCATIONS:
        raise ValidationError("Unknown location")

    occurred = body.get("occurredAt")
    if isinstance(occurred, bool) or not isinstance(occurred, int):
        raise ValidationError("occurredAt must be epoch milliseconds")
    if occurred > now_ms + 5 * 60 * 1000:
        raise ValidationError("occurredAt cannot be in the future")
    if occurred < now_ms - 365 * DAY_MS:
        raise ValidationError("occurredAt is more than a year ago")

    image_key = body.get("imageKey")
    if image_key is not None:
        if not isinstance(image_key, str) or not image_key_pattern(sub).match(image_key):
            raise ValidationError("Invalid imageKey")

    return {
        "type": item_type,
        "title": clean_text(body.get("title"), "title", 3, C.MAX_TITLE),
        "category": category,
        "description": clean_text(body.get("description"), "description", 0, C.MAX_DESCRIPTION, required=False),
        "location": location,
        "occurredAt": occurred,
        "imageKey": image_key,
    }
