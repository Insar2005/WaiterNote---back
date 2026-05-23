import re

# nanoid default alphabet: A-Za-z0-9_-
_NANOID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{21}$")


def is_valid_id(value: str) -> bool:
    """Validate that string is a valid nanoid(21)."""
    return bool(_NANOID_PATTERN.match(value))