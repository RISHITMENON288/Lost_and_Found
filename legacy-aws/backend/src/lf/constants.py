"""Values shared by the API, the match worker and the Android app (keep in sync with Models.kt)."""

CATEGORIES = (
    "ELECTRONICS", "BAG", "CLOTHING", "ACCESSORY", "STATIONERY",
    "KEYS", "CONTAINER", "DOCUMENTS", "SPORTS", "TOYS",
)

LOCATIONS = (
    "Library", "Main Gate", "Academic Block", "Cafeteria", "Hostel Area",
    "Sports Ground", "Auditorium", "Parking", "Other",
)

TYPES = ("LOST", "FOUND")

# Report lifecycle. LOST/FOUND shown to users is simply type + OPEN.
STATUS_OPEN = "OPEN"
STATUS_POTENTIAL = "POTENTIAL_MATCH"
STATUS_CLAIMED = "CLAIMED"
STATUS_RETURNED = "RETURNED"
STATUS_CLOSED = "CLOSED"
OPEN_STATUSES = (STATUS_OPEN, STATUS_POTENTIAL)

MATCH_PENDING = "PENDING"
MATCH_CONFIRMED = "CONFIRMED"
MATCH_REJECTED = "REJECTED"

MAX_TITLE = 60
MAX_DESCRIPTION = 300
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = 10 * 1024

# Rekognition labels that say nothing about the object itself, so they must not make two photos "similar".
IGNORED_LABELS = frozenset({
    "indoors", "outdoors", "person", "human", "adult", "male", "female", "man", "woman", "people", "face", "head",
    "hand", "finger", "body part", "floor", "furniture", "table", "wood", "desk", "room", "office", "plant",
})
MAX_PHOTO_LABELS = 15
MIN_LABEL_CONFIDENCE = 75
