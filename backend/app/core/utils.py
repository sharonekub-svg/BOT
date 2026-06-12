"""Small shared helpers used across the platform."""

import json
import math
from datetime import datetime, timezone
from typing import Any


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """Normalize DB datetimes: SQLite returns naive values, Postgres aware ones."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def parse_json_field(value: Any, default: Any = None) -> Any:
    """Gamma returns several fields as JSON-encoded strings ('["Yes","No"]')."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return default
    return default


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return as_utc(dt)


def hours_until(dt: datetime | None, reference: datetime | None = None) -> float | None:
    if dt is None:
        return None
    ref = reference or now_utc()
    return (as_utc(dt) - ref).total_seconds() / 3600.0


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"
