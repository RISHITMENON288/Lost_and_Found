"""API Gateway (HTTP API, payload v2) entry point. JWT is verified by API Gateway's Cognito
authorizer before this code runs; we only read the verified claims."""
import json
import logging

from . import service
from .service import ApiError, User

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_store = None


def get_store():
    global _store
    if _store is None:
        from .store import Store  # imported lazily so unit tests need no AWS libraries
        _store = Store()
    return _store


def _respond(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body),
    }


def _user(event):
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    sub = claims.get("sub")
    if not sub:
        raise ApiError(401, "Unauthorized")
    name = (claims.get("name") or claims.get("email") or "Student")[:50]
    phone = str(claims.get("phone_number") or "")[:20]
    return User(sub=sub, name=name, email=claims.get("email", ""), phone=phone)


def _body(event):
    raw = event.get("body")
    if not raw:
        return {}
    if len(raw) > 10 * 1024:
        raise ApiError(413, "Request too large")
    try:
        return json.loads(raw)
    except ValueError:
        raise ApiError(400, "Body must be valid JSON") from None


def lambda_handler(event, context):
    try:
        store = get_store()
        user = _user(event)
        route = event.get("routeKey")
        params = event.get("pathParameters") or {}

        if route == "GET /items":
            return _respond(200, {"items": service.list_items(store, user)})
        if route == "POST /items":
            return _respond(201, service.create_item(store, user, _body(event)))
        if route == "GET /items/{id}":
            return _respond(200, service.get_item(store, user, params["id"]))
        if route == "POST /items/{id}/close":
            return _respond(200, service.close_item(store, user, params["id"]))
        if route == "POST /items/{id}/return":
            return _respond(200, service.mark_returned(store, user, params["id"]))
        if route == "GET /matches":
            return _respond(200, {"matches": service.list_matches(store, user)})
        if route == "GET /matches/{id}/contact":
            return _respond(200, service.get_contact(store, user, params["id"]))
        if route == "POST /matches/{id}/respond":
            return _respond(200, service.respond_to_match(store, user, params["id"], _body(event).get("confirm")))
        if route == "POST /uploads":
            return _respond(200, service.create_upload(store, user, _body(event)))
        return _respond(404, {"error": "Not found"})
    except ApiError as e:
        return _respond(e.status, {"error": e.message})
    except Exception:  # never leak internals to the client
        logger.exception("Unhandled error")
        return _respond(500, {"error": "Internal error"})
