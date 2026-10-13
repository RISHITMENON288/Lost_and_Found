"""Scheduled by EventBridge once a day: closes reports that were never resolved."""
import json
import logging

from . import config, service

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
    closed = service.expire_old(get_store(), service.now_ms(), config.expiry_days())
    logger.info(json.dumps({"event": "expired", "closed": closed}))
    return {"closed": closed}
