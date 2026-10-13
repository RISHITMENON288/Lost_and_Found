"""Business rules. Pure Python: every AWS call goes through the `store` object,
so this module is fully unit-testable with an in-memory fake."""
import logging
import time
import uuid
from dataclasses import dataclass

from . import constants as C
from . import matcher
from . import notify
from . import validation

MAX_ACTIVE_REPORTS_PER_USER = 20

logger = logging.getLogger()


@dataclass(frozen=True)
class User:
    sub: str
    name: str
    email: str
    phone: str = ""


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def now_ms():
    return int(time.time() * 1000)


# ---------- views (what leaves the API) ----------

def item_view(store, item):
    key = item.get("imageKey")
    return {
        "id": item["itemId"],
        "type": item["type"],
        "title": item["title"],
        "category": item["category"],
        "description": item.get("description", ""),
        "location": item["location"],
        "occurredAt": item["occurredAt"],
        "imageUrl": store.image_url(key) if key else None,
        "reporterId": item["reporterId"],
        "reporterName": item["reporterName"],
        "status": item["status"],
        "createdAt": item["createdAt"],
    }


def match_view(match):
    return {
        "id": match["matchId"],
        "lostItemId": match["lostItemId"],
        "foundItemId": match["foundItemId"],
        "score": round(float(match["score"]), 4),
        "state": match["state"],
        "createdAt": match["createdAt"],
    }


# ---------- queries ----------

def list_items(store, user):
    """Public feed (open reports) + my own reports + items that appear in my matches."""
    by_id = {}
    for item in store.query_feed("LOST") + store.query_feed("FOUND") + store.query_by_reporter(user.sub):
        by_id[item["itemId"]] = item
    matches = store.query_matches_for_user(user.sub)
    needed = set()
    for m in matches:
        needed.update((m["lostItemId"], m["foundItemId"]))
    missing = [i for i in needed if i not in by_id]
    for item in store.batch_get_items(missing):
        by_id[item["itemId"]] = item
    ordered = sorted(by_id.values(), key=lambda i: i["createdAt"], reverse=True)
    return [item_view(store, i) for i in ordered]


def get_item(store, user, item_id):
    item = store.get_item(item_id)
    if item is None:
        raise ApiError(404, "Item not found")
    visible = item["status"] in C.OPEN_STATUSES or item["reporterId"] == user.sub
    if not visible:
        for m in store.query_matches_for_item(item_id):
            if user.sub in (m["lostReporterId"], m["foundReporterId"]):
                visible = True
                break
    if not visible:
        raise ApiError(404, "Item not found")
    return item_view(store, item)


def list_matches(store, user):
    matches = sorted(store.query_matches_for_user(user.sub), key=lambda m: m["createdAt"], reverse=True)
    return [match_view(m) for m in matches]


def get_contact(store, user, match_id):
    """The finder's phone number. Only the owner of the lost item, only after confirming,
    and only until the item is returned."""
    match = store.get_match(match_id)
    if match is None or match["lostReporterId"] != user.sub:
        raise ApiError(404, "Match not found")
    if match["state"] != C.MATCH_CONFIRMED:
        raise ApiError(403, "The phone number is shown only after you confirm the match")
    found = store.get_item(match["foundItemId"])
    if found is None or found["status"] != C.STATUS_CLAIMED:
        raise ApiError(404, "The phone number is no longer available")
    phone = found.get("reporterPhone")
    if not phone:
        raise ApiError(404, "The finder did not add a phone number.")
    return {"phone": phone}


# ---------- commands ----------

def create_upload(store, user, body):
    if not isinstance(body, dict) or body.get("contentType") != "image/jpeg":
        raise ApiError(400, "Only image/jpeg uploads are accepted")
    key = f"uploads/{user.sub}/{uuid.uuid4()}.jpg"
    upload = store.create_upload(key)
    return {"key": key, "url": upload["url"], "fields": upload["fields"]}


def create_item(store, user, body, now=None):
    now = now if now is not None else now_ms()
    try:
        data = validation.validate_new_item(body, user.sub, now)
    except validation.ValidationError as e:
        raise ApiError(400, str(e)) from None

    active = [i for i in store.query_by_reporter(user.sub) if i["status"] in C.OPEN_STATUSES]
    if len(active) >= MAX_ACTIVE_REPORTS_PER_USER:
        raise ApiError(429, "You have too many open reports. Close some before adding more.")

    key = data.pop("imageKey")
    if key is not None and not store.image_exists(key):
        raise ApiError(400, "Photo upload was not completed")

    item = dict(data)
    item.update(
        itemId=str(uuid.uuid4()),
        reporterId=user.sub,
        reporterName=user.name,
        status=C.STATUS_OPEN,
        createdAt=now,
    )
    # Private: used for emails and for the owner's contact lookup. Never part of item_view.
    if user.email:
        item["reporterEmail"] = user.email
    if user.phone:
        item["reporterPhone"] = user.phone
    if key is not None:
        item["imageKey"] = key
    store.put_item(item)
    store.enqueue(item["itemId"], has_image=key is not None)
    return item_view(store, item)


def _owned_item(store, user, item_id):
    item = store.get_item(item_id)
    if item is None or item["reporterId"] != user.sub:
        raise ApiError(404, "Item not found")
    return item


def refresh_status(store, item_id):
    """A POTENTIAL_MATCH item with no pending suggestion left goes back to OPEN."""
    item = store.get_item(item_id)
    if item is None or item["status"] != C.STATUS_POTENTIAL:
        return
    pending = [m for m in store.query_matches_for_item(item_id) if m["state"] == C.MATCH_PENDING]
    if not pending:
        store.update_status(item_id, C.STATUS_OPEN, expected=(C.STATUS_POTENTIAL,))


def _reject_pending_for(store, item_id):
    """Reject pending matches of an item; return the ids of the *other* items touched."""
    touched = set()
    for m in store.query_matches_for_item(item_id):
        if m["state"] == C.MATCH_PENDING and store.update_match_state(m["matchId"], C.MATCH_REJECTED, C.MATCH_PENDING):
            touched.update((m["lostItemId"], m["foundItemId"]))
    touched.discard(item_id)
    return touched


def _close(store, item):
    others = _reject_pending_for(store, item["itemId"])
    store.update_status(item["itemId"], C.STATUS_CLOSED, expected=C.OPEN_STATUSES)
    for other in others:
        refresh_status(store, other)


def close_item(store, user, item_id):
    item = _owned_item(store, user, item_id)
    if item["status"] not in C.OPEN_STATUSES:
        raise ApiError(409, "This report can no longer be closed")
    _close(store, item)
    return item_view(store, store.get_item(item_id))


def respond_to_match(store, user, match_id, confirm):
    if not isinstance(confirm, bool):
        raise ApiError(400, "confirm must be true or false")
    match = store.get_match(match_id)
    if match is None or user.sub not in (match["lostReporterId"], match["foundReporterId"]):
        raise ApiError(404, "Match not found")
    if user.sub != match["lostReporterId"]:
        raise ApiError(403, "Only the owner of the lost item can respond to a match")
    if match["state"] != C.MATCH_PENDING:
        raise ApiError(409, "This match was already answered")

    lost_id, found_id = match["lostItemId"], match["foundItemId"]
    new_state = C.MATCH_CONFIRMED if confirm else C.MATCH_REJECTED
    if not store.update_match_state(match_id, new_state, C.MATCH_PENDING):
        raise ApiError(409, "This match was already answered")

    others = set()
    if confirm:
        others |= _reject_pending_for(store, lost_id)
        others |= _reject_pending_for(store, found_id)
        store.update_status(lost_id, C.STATUS_CLAIMED, expected=C.OPEN_STATUSES)
        store.update_status(found_id, C.STATUS_CLAIMED, expected=C.OPEN_STATUSES)
        others -= {lost_id, found_id}
    else:
        others |= {lost_id, found_id}
    for other in others:
        refresh_status(store, other)
    if confirm:
        found = store.get_item(found_id)
        if found is not None:
            notify.send(
                found.get("reporterEmail"),
                "The owner confirmed your found item",
                "The owner of the lost item confirmed that \"{}\" is theirs and will contact you. "
                "Please keep it safe until then.\n\nCampus Lost & Found".format(found["title"]),
            )
    return match_view(store.get_match(match_id))


def mark_returned(store, user, item_id):
    item = _owned_item(store, user, item_id)
    if item["status"] != C.STATUS_CLAIMED:
        raise ApiError(409, "Only a claimed item can be marked as returned")
    ids = {item_id}
    for m in store.query_matches_for_item(item_id):
        if m["state"] == C.MATCH_CONFIRMED:
            ids.update((m["lostItemId"], m["foundItemId"]))
    for i in ids:
        store.update_status(i, C.STATUS_RETURNED, expected=(C.STATUS_CLAIMED,))
    return item_view(store, store.get_item(item_id))


def expire_old(store, now, days):
    """Scheduled housekeeping: close reports nobody has touched for `days` days."""
    cutoff = now - days * 86_400_000
    closed = 0
    for item_type in C.TYPES:
        for item in store.query_older(item_type, cutoff):
            if item["status"] in C.OPEN_STATUSES:
                _close(store, item)
                closed += 1
    return closed


# ---------- matching (called by the SQS worker) ----------

def _ensure_labels(store, item):
    """Ask Rekognition what is in the photo, once per report. A failure just means no photo score."""
    key = item.get("imageKey")
    if not key or "imageLabels" in item:
        return
    try:
        labels = store.detect_labels(key)
        store.set_labels(item["itemId"], labels)
    except Exception as e:
        logger.warning("Photo labels not added: %s", type(e).__name__)
        return
    item["imageLabels"] = labels


def process_item(store, item_id, model=None, now=None):
    """Compare one report with every open report of the opposite type. Idempotent."""
    now = now if now is not None else now_ms()
    item = store.get_item(item_id)
    if item is None or item["status"] not in C.OPEN_STATUSES:
        return 0
    _ensure_labels(store, item)
    opposite = "FOUND" if item["type"] == "LOST" else "LOST"
    created = 0
    for other in store.query_candidates(item["category"], opposite):
        if other["status"] not in C.OPEN_STATUSES or other["reporterId"] == item["reporterId"]:
            continue
        lost, found = (item, other) if item["type"] == "LOST" else (other, item)
        value = matcher.score(lost, found, model)
        if not matcher.is_match(value, model):
            continue
        match = {
            "matchId": "{}_{}".format(lost["itemId"], found["itemId"]),
            "lostItemId": lost["itemId"],
            "foundItemId": found["itemId"],
            "lostReporterId": lost["reporterId"],
            "foundReporterId": found["reporterId"],
            "score": value,
            "state": C.MATCH_PENDING,
            "createdAt": now,
        }
        if store.put_match(match):  # False when this pair already exists (retry or earlier decision)
            created += 1
            store.update_status(lost["itemId"], C.STATUS_POTENTIAL, expected=(C.STATUS_OPEN,))
            store.update_status(found["itemId"], C.STATUS_POTENTIAL, expected=(C.STATUS_OPEN,))
            _email_suggestion(lost, found)
    return created


def _email_suggestion(lost, found):
    """Tell both people about a new suggestion. No phone numbers are ever put in an email."""
    notify.send(
        lost.get("reporterEmail"),
        "Possible match for your lost item",
        "Something that may be your lost \"{}\" was reported found at {}. "
        "Open the app to look at it and confirm.\n\nCampus Lost & Found".format(lost["title"], found["location"]),
    )
    notify.send(
        found.get("reporterEmail"),
        "Someone may be looking for the item you found",
        "The owner of a lost \"{}\" may be looking for the \"{}\" you found. "
        "You will get another email if they confirm.\n\nCampus Lost & Found".format(lost["title"], found["title"]),
    )
