"""Shared dashboard helpers: number formatting and the rolling 12-month window.

The sample data is historical, so every window is anchored to the data's own last
order date instead of "today"; all four tabs use the same window so their numbers
describe the same period.
"""
import calendar
from typing import NamedTuple

from django.db.models import Max, Q

MONTHS = 12


def shift_months(dt, months):
    """Move a naive datetime by whole months, clamping the day (pure stdlib)."""
    year, month0 = divmod(dt.year * 12 + dt.month - 1 + months, 12)
    day = min(dt.day, calendar.monthrange(year, month0 + 1)[1])
    return dt.replace(year=year, month=month0 + 1, day=day)


def money(value):
    if value is None:
        return "—"
    value = float(value)
    for threshold, divisor, suffix in ((1e9, 1e9, "B"), (1e6, 1e6, "M"), (1e4, 1e3, "K")):
        if abs(value) >= threshold:
            return f"${value / divisor:,.1f}{suffix}"
    return f"${value:,.0f}"


def delta(cur, prev):
    """Percent change and direction, or (None, None) when there is nothing to compare."""
    if cur is None or prev in (None, 0):
        return None, None
    change = round((float(cur) - float(prev)) / float(prev) * 100, 1)
    return f"{change:+.1f}%", "up" if change > 0 else "down" if change < 0 else "flat"


def rank(rows, name_key, value_key, fmt):
    """Rows with a display value and a bar width (percent of the largest row)."""
    top = max((float(r[value_key] or 0) for r in rows), default=0)
    ranked = []
    for row in rows:
        value = row[value_key] or 0
        ranked.append({
            "name": row[name_key] or "—",
            "value": fmt(value),
            "pct": max(round(float(value) / top * 100), 2) if top else 0,
        })
    return ranked


class Window(NamedTuple):
    last: object            # latest order date in the data
    trend_start: object     # first instant of the current 12-month window
    window_start: object    # 12 months before trend_start (start of the compare window)
    cur: Q                  # filter for the current window
    prev: Q                 # filter for the compare window
    label: str              # e.g. "Jul 2024 – Jun 2025"
    prev_label: str         # e.g. "Jul 2023 – Jun 2024"


def rolling_window(model, date_field="order_date"):
    """The standard two 12-month windows, or None when the table is empty."""
    last = model.objects.aggregate(last=Max(date_field))["last"]
    if last is None:
        return None
    month_start = last.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    trend_start = shift_months(month_start, -(MONTHS - 1))
    window_start = shift_months(trend_start, -MONTHS)
    return Window(
        last=last,
        trend_start=trend_start,
        window_start=window_start,
        cur=Q(**{f"{date_field}__gte": trend_start}),
        prev=Q(**{f"{date_field}__lt": trend_start}),
        label=f"{trend_start:%b %Y} – {last:%b %Y}",
        prev_label=f"{window_start:%b %Y} – {shift_months(trend_start, -1):%b %Y}",
    )
