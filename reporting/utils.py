"""Shared report helpers: number formatting and the rolling 12-month window.

The sample data is historical, so every window is anchored to the data's own last
order date instead of "today"; all four tabs use the same window so their numbers
describe the same period.
"""
import calendar
from datetime import datetime, time, timedelta
from typing import NamedTuple

from django.db.models import Max

MONTHS = 12


def shift_months(dt, months):
    """Move a naive datetime by whole months, clamping the day (pure stdlib)."""
    year, month0 = divmod(dt.year * 12 + dt.month - 1 + months, 12)
    day = min(dt.day, calendar.monthrange(year, month0 + 1)[1])
    return dt.replace(year=year, month=month0 + 1, day=day)


def money(value):
    if value is None or value == "":
        return "—"
    value = float(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    for threshold, divisor, suffix in ((1e9, 1e9, "B"), (1e6, 1e6, "M"), (1e4, 1e3, "K")):
        if value >= threshold:
            return f"{sign}${value / divisor:,.1f}{suffix}"
    return f"{sign}${value:,.0f}"


def money_exact(value):
    if value is None or value == "":
        return "—"
    value = float(value)
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def count(value):
    if value is None or value == "":
        return "—"
    return f"{int(value):,}"


def percent(value, digits=None):
    if value is None or value == "":
        return "—"
    if digits is None:
        text = f"{float(value):,.2f}".rstrip("0").rstrip(".")
    else:
        text = f"{float(value):,.{int(digits)}f}"
    return f"{text}%"


def units(value):
    if value is None or value == "":
        return "—"
    return f"{int(value):,} units"


def cents(value):
    if value is None or value == "":
        return "—"
    return f"{round(float(value)):,}¢"


_METRIC_FORMATTERS = {
    "money": money,
    "count": count,
    "percent": percent,
    "units": units,
    "cents": cents,
}


def metric(value, kind):
    return _METRIC_FORMATTERS.get(kind, count)(value)


def delta_pct(cur, prev):
    """Percent change as a number and direction, or (None, None) without a baseline."""
    if cur is None or prev is None or float(prev) <= 0:
        return None, None
    change = round((float(cur) - float(prev)) / float(prev) * 100, 1)
    return change, "up" if change > 0 else "down" if change < 0 else "flat"


def delta(cur, prev):
    change, direction = delta_pct(cur, prev)
    return (f"{change:+.1f}%" if change is not None else None), direction


def delta_text(value):
    if value is None:
        return ""
    return f"{float(value):+.1f}%"


def rank(rows, name_key, value_key):
    """Rows with a raw numeric value and a bar width (percent of the largest row)."""
    top = max((float(r[value_key] or 0) for r in rows), default=0)
    ranked = []
    for row in rows:
        value = row[value_key] or 0
        if not isinstance(value, (int, float)):
            value = float(value)
        ranked.append({
            "name": row[name_key] or "—",
            "value": value,
            "pct": max(round(float(value) / top * 100), 2) if top and value else 0,
        })
    return ranked


RING = 2 * 3.141592653589793 * 60  # circumference of the donut chart's r=60 ring


def ring(rows):
    """Rows with a "pct" get the circle dash length and offset for the SVG donut (r=60)."""
    out, cum = [], 0.0
    for row in rows:
        out.append({**row, "dash": round(row["pct"] / 100 * RING, 2),
                    "off": round(-cum / 100 * RING, 2)})
        cum += row["pct"]
    return out


class Window(NamedTuple):
    last: object            # end of the latest data month
    trend_start: object     # first instant of the current 12-month window
    window_start: object    # 12 months before trend_start (start of the compare window)
    label: str              # e.g. "Jul 2024 – Jun 2025"
    prev_label: str         # e.g. "Jul 2023 – Jun 2024"
    custom: bool            # True when the user applied their own ?from=/?to= range


def rolling_window(model, date_field="order_date"):
    """The standard two 12-month windows, or None when the table is empty."""
    last = model.objects.aggregate(last=Max(date_field))["last"]
    if last is None:
        return None
    month_start = last.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = shift_months(month_start, 1) - timedelta(microseconds=1)
    trend_start = shift_months(month_start, -(MONTHS - 1))
    window_start = shift_months(trend_start, -MONTHS)
    return Window(
        last=month_end,
        trend_start=trend_start,
        window_start=window_start,
        label=f"{trend_start:%b %Y} \u2013 {month_end:%b %Y}",
        prev_label=f"{window_start:%b %Y} \u2013 {shift_months(trend_start, -1):%b %Y}",
        custom=False,
    )


def range_window(model, start, end, date_field="order_date"):
    """Explicit [start, end] date range: cur = that range, prev = the same length before it.

    The selected end is honored even when it is later than the last row in the table.
    Callers report empty months as zero rather than silently shrinking the range.
    """
    last = model.objects.aggregate(last=Max(date_field))["last"]
    if last is None:
        return None
    lo = datetime.combine(start, time.min)
    hi = datetime.combine(end, time.max)
    if hi < lo:
        return None
    span = hi - lo
    prev_hi = lo - timedelta(microseconds=1) if lo > datetime.min else lo
    try:
        prev_lo = prev_hi - span
    except OverflowError:  # a range that starts near year 1 has no room for a compare window
        prev_lo = datetime.min
    return Window(
        last=hi,
        trend_start=lo,
        window_start=prev_lo,
        label=f"{lo:%b %d, %Y} – {hi:%b %d, %Y}",
        prev_label=f"{prev_lo:%b %d, %Y} – {prev_hi:%b %d, %Y}",
        custom=True,
    )


def window_for(request, model, date_field="order_date"):
    """The rolling 12-month default, or the ?from=/?to= range when the user applied one."""
    params = getattr(request, "_range_params", request.GET)

    def pick(key):
        try:
            return datetime.strptime(params.get(key, ""), "%Y-%m-%d").date()
        except ValueError:
            return None
    start, end = pick("from"), pick("to")
    if start and end:
        if start > end:
            return None
        return range_window(model, start, end, date_field)
    return rolling_window(model, date_field)
