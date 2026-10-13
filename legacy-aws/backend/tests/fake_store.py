"""In-memory stand-in for lf.store.Store with the same method names and semantics."""
import copy

from lf import constants as C


class FakeStore:
    def __init__(self):
        self.items = {}
        self.matches = {}
        self.images = set()
        self.queue = []
        self.labels = {}        # image key -> labels Rekognition would return
        self.label_errors = set()

    # items
    def put_item(self, item):
        assert item["itemId"] not in self.items
        self.items[item["itemId"]] = copy.deepcopy(item)

    def get_item(self, item_id):
        return copy.deepcopy(self.items.get(item_id))

    def batch_get_items(self, ids):
        return [copy.deepcopy(self.items[i]) for i in ids if i in self.items]

    def _sorted(self, rows):
        return sorted(copy.deepcopy(list(rows)), key=lambda i: i["createdAt"], reverse=True)

    def query_feed(self, item_type, limit=100):
        rows = (i for i in self.items.values() if i["type"] == item_type and i["status"] in C.OPEN_STATUSES)
        return self._sorted(rows)[:limit]

    def query_by_reporter(self, sub, limit=200):
        return self._sorted(i for i in self.items.values() if i["reporterId"] == sub)[:limit]

    def query_candidates(self, category, item_type, limit=300):
        return self._sorted(
            i for i in self.items.values()
            if i["category"] == category and i["type"] == item_type and i["status"] in C.OPEN_STATUSES
        )[:limit]

    def query_older(self, item_type, cutoff_ms, limit=500):
        return self._sorted(
            i for i in self.items.values()
            if i["type"] == item_type and i["createdAt"] < cutoff_ms and i["status"] in C.OPEN_STATUSES
        )[:limit]

    def update_status(self, item_id, new_status, expected=None):
        item = self.items.get(item_id)
        if item is None or (expected and item["status"] not in expected):
            return False
        item["status"] = new_status
        return True

    def set_embedding(self, item_id, embedding):
        self.items[item_id]["embedding"] = embedding

    def set_labels(self, item_id, labels):
        self.items[item_id]["imageLabels"] = list(labels)

    def detect_labels(self, key):
        if key in self.label_errors:
            raise RuntimeError("Rekognition is down")
        return list(self.labels.get(key, []))

    # matches
    def put_match(self, match):
        if match["matchId"] in self.matches:
            return False
        self.matches[match["matchId"]] = copy.deepcopy(match)
        return True

    def get_match(self, match_id):
        return copy.deepcopy(self.matches.get(match_id))

    def query_matches_for_user(self, sub, limit=200):
        return copy.deepcopy([m for m in self.matches.values() if sub in (m["lostReporterId"], m["foundReporterId"])])

    def query_matches_for_item(self, item_id):
        return copy.deepcopy([m for m in self.matches.values() if item_id in (m["lostItemId"], m["foundItemId"])])

    def update_match_state(self, match_id, new_state, expected_state):
        m = self.matches.get(match_id)
        if m is None or m["state"] != expected_state:
            return False
        m["state"] = new_state
        return True

    # s3 / sqs
    def image_url(self, key):
        return f"https://example.invalid/{key}"

    def image_exists(self, key):
        return key in self.images

    def create_upload(self, key):
        return {"url": "https://example.invalid/upload", "fields": {"key": key}}

    def enqueue(self, item_id, has_image):
        self.queue.append(("extract" if has_image else "match", item_id))

    def enqueue_match(self, item_id):
        self.queue.append(("match", item_id))

    def load_model(self):
        return None
