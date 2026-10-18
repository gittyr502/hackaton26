"""The 6 extracted fields. Multi-value fields hold lists."""
FIELD_NAMES = [
    "full_name",
    "id_number",
    "central_numbers",
    "receipt_date",
    "sender",
    "commitment_numbers",
]
MULTI_FIELDS = {"central_numbers", "commitment_numbers"}

LEVEL_OK = "ok"
LEVEL_REVIEW = "review"
LEVEL_EMPTY = "empty"
