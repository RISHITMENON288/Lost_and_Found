"""Cognito PreSignUp trigger: optionally restrict registration to one email domain
(e.g. your college domain) so strangers cannot create accounts."""
from . import config


def lambda_handler(event, context):
    allowed = config.allowed_email_domain()
    if allowed:
        email = (event.get("request", {}).get("userAttributes", {}).get("email") or "").lower()
        if not email.endswith("@" + allowed):
            raise Exception(f"Please sign up with your @{allowed} email address.")
    return event
