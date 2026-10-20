"""The extracted fields. Multi-value fields hold lists."""
FIELD_NAMES = [
    "full_name",
    "id_number",
    "central_numbers",
    "receipt_date",
    "sender",
    "commitment_numbers",
    "test_type",
    "referral_number",
]
# Not on every form: left empty, they never hold a form back from approval (and are not exported by default).
OPTIONAL_FIELDS = {"test_type", "referral_number"}
MULTI_FIELDS = {"central_numbers", "commitment_numbers"}

LEVEL_OK = "ok"
LEVEL_REVIEW = "review"
LEVEL_EMPTY = "empty"
