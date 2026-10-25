from django import template

from ..utils import (
    count,
    delta_text,
    metric,
    money,
    money_exact,
    percent,
    units,
)

register = template.Library()

register.filter("fmt_money", money)
register.filter("fmt_money_exact", money_exact)
register.filter("fmt_count", count)
register.filter("fmt_percent", percent)
register.filter("fmt_units", units)
register.filter("fmt_metric", metric)
register.filter("fmt_delta", delta_text)


@register.filter
def fmt_signed_percent(value):
    if value is None:
        return "\u2014"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "\u2014"
    return f"{number:+,.1f}%"


@register.filter
def fmt_pct_width(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return min(max(number, 0), 100)
