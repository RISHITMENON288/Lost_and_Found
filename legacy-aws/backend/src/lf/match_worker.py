"""SQS consumer: runs the matcher for each queued report. Safe to retry (matches are idempotent)."""
import json
import logging

from . import service

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_store = None


def get_store():
    global _store
    if _store is None:
        from .store import Store
        _store = Store()
    return _store


def lambda_handler(event, context):
    store = get_store()
    model = store.load_model()
    failures = []
    for record in event.get("Records", []):
        try:
            item_id = json.loads(record["body"])["itemId"]
            created = service.process_item(store, item_id, model)
            logger.info(json.dumps({"event": "matched", "itemId": item_id, "newMatches": created}))
        except Exception:
            logger.exception("Matching failed for message %s", record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
