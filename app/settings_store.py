"""Tiny DB-backed key/value store (persists Gmail token on ephemeral cloud disks)."""
from .db import session
from .models import Setting


def get(key: str, default=None):
    with session() as s:
        row = s.get(Setting, key)
        return row.value if row else default


def put(key: str, value: str):
    with session() as s:
        row = s.get(Setting, key)
        if row:
            row.value = value
        else:
            s.add(Setting(key=key, value=value))
        s.commit()
