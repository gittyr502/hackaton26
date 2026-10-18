"""Israeli ID (ת.ז.) check-digit validation."""


def is_valid_id(id_number: str) -> bool:
    """Up to 9 digits (leading zeros are dropped by normalize); padded to 9, the weighted digit sum
    (weights 1,2,1,2,...) must be divisible by 10."""
    if not id_number or not id_number.isdigit() or len(id_number) > 9:
        return False
    id_number = id_number.zfill(9)
    total = 0
    for i, ch in enumerate(id_number):
        d = int(ch) * (1 if i % 2 == 0 else 2)
        total += d - 9 if d > 9 else d
    return total % 10 == 0
