"""Tiny cron-next helper for Plan 13 §7.1.

We do NOT take a hard dep on ``croniter`` because the rest of Donna is
deliberately small. The schedules we ship today only need the standard
5-field cron grammar with no second / DOW-name extensions; this
implementation covers ``*``, ``*/N``, and comma-separated lists.

If the cron grammar grows, swap to ``croniter`` — the function
signature is the only contract.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone as _tz
from typing import Iterable


_RANGES = {
    "minute": range(0, 60),
    "hour": range(0, 24),
    "dom": range(1, 32),
    "month": range(1, 13),
    "dow": range(0, 7),
}


def _expand(field: str, rng: range) -> set[int]:
    if field == "*":
        return set(rng)
    out: set[int] = set()
    for piece in field.split(","):
        if piece.startswith("*/"):
            step = int(piece[2:])
            out.update(rng[::step])
        elif "-" in piece:
            lo, hi = piece.split("-")
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(piece))
    return out & set(rng)


def parse(expr: str) -> dict[str, set[int]]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"expected 5-field cron, got {len(parts)} fields: {expr!r}")
    keys = ("minute", "hour", "dom", "month", "dow")
    return {k: _expand(parts[i], _RANGES[k]) for i, k in enumerate(keys)}


def next_fire_after(expr: str, after: datetime) -> datetime:
    """Return the next datetime ≥ ``after`` matching ``expr``.

    Caps at 4 years out so a pathological cron expression can't loop
    forever.
    """
    fields = parse(expr)
    cursor = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    deadline = cursor + timedelta(days=365 * 4)
    while cursor < deadline:
        if cursor.month not in fields["month"]:
            cursor = _bump_month(cursor)
            continue
        if cursor.day not in fields["dom"]:
            cursor = cursor.replace(hour=0, minute=0) + timedelta(days=1)
            continue
        if cursor.weekday() not in _dow_to_weekday(fields["dow"]):
            cursor = cursor.replace(hour=0, minute=0) + timedelta(days=1)
            continue
        if cursor.hour not in fields["hour"]:
            cursor = cursor.replace(minute=0) + timedelta(hours=1)
            continue
        if cursor.minute not in fields["minute"]:
            cursor = cursor + timedelta(minutes=1)
            continue
        return cursor
    raise ValueError(f"no fire time within 4 years for cron {expr!r}")


def _dow_to_weekday(dow: Iterable[int]) -> set[int]:
    """Cron uses 0=Sun..6=Sat; Python weekday uses 0=Mon..6=Sun. Map."""
    mapping = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}
    return {mapping[d] for d in dow}


def _bump_month(cursor: datetime) -> datetime:
    year = cursor.year + (1 if cursor.month == 12 else 0)
    month = 1 if cursor.month == 12 else cursor.month + 1
    return cursor.replace(year=year, month=month, day=1, hour=0, minute=0)
