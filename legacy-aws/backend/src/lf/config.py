import os


def env(name, default=""):
    return os.environ.get(name, default)


def items_table():
    return env("ITEMS_TABLE")


def matches_table():
    return env("MATCHES_TABLE")


def bucket():
    return env("BUCKET")


def match_queue_url():
    return env("MATCH_QUEUE_URL")


def extract_queue_url():
    return env("EXTRACT_QUEUE_URL")  # empty when the image extractor is not deployed


def expiry_days():
    return int(env("EXPIRY_DAYS", "60"))


def allowed_email_domain():
    return env("ALLOWED_EMAIL_DOMAIN").strip().lower()


def sender_email():
    return env("SENDER_EMAIL").strip()  # must be a verified Amazon SES identity; empty turns emails off
