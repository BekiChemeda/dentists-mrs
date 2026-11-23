"""Clinic opening hours: stored per weekday, used to refuse appointments outside them."""

from __future__ import annotations

import datetime
import re

from rest_framework import serializers

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday",
             "sat": "Saturday", "sun": "Sunday"}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def clean_opening_hours(value) -> dict:
    """{} (no limits) or one entry per weekday: {"open": "HH:MM", "close": "HH:MM"} or None (closed)."""
    if value in (None, "", {}):
        return {}
    if not isinstance(value, dict) or set(value) - set(DAYS):
        raise serializers.ValidationError("Give the hours for each day of the week (mon to sun).")
    out = {}
    for day in DAYS:
        entry = value.get(day)
        if entry is None:
            out[day] = None
            continue
        if not isinstance(entry, dict) or not _TIME.match(str(entry.get("open", ""))) \
                or not _TIME.match(str(entry.get("close", ""))):
            raise serializers.ValidationError(f"{DAY_NAMES[day]}: use times like 08:00 and 17:30.")
        if entry["open"] >= entry["close"]:
            raise serializers.ValidationError(f"{DAY_NAMES[day]}: closing time must be after opening time.")
        out[day] = {"open": entry["open"], "close": entry["close"]}
    if all(v is None for v in out.values()):
        raise serializers.ValidationError("The clinic must be open on at least one day.")
    return out


def outside_hours(hours: dict, start: datetime.datetime, minutes: int) -> str | None:
    """A message if [start, start+minutes] is outside the opening hours (local time), else None."""
    if not hours:
        return None
    from django.utils import timezone

    local = timezone.localtime(start) if start.tzinfo else start
    day = DAYS[local.weekday()]
    entry = hours.get(day)
    if entry is None:
        return f"The clinic is closed on {DAY_NAMES[day]}s."
    begin = local.strftime("%H:%M")
    end = (local + datetime.timedelta(minutes=minutes)).strftime("%H:%M")
    if begin < entry["open"] or end > entry["close"] or end < begin:
        return f"On {DAY_NAMES[day]}s the clinic is open {entry['open']}–{entry['close']}."
    return None
