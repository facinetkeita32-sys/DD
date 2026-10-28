import secrets


# Sessions belong to this live database generation, not to backup contents.
# A fresh process also requires a fresh login rather than reviving old cookies.
_generation = secrets.token_hex(32)


def session_generation():
    return _generation


def invalidate_sessions():
    global _generation
    _generation = secrets.token_hex(32)
