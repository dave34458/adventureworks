from django import template

from ..utils import (
    cents,
    count,
    delta_text,
    metric,
    money,
    money_exact,
    percent,
    units,
)

register = template.Library()


@register.filter
def fmt_money(value):
    return money(value)


@register.filter
def fmt_money_exact(value):
    return money_exact(value)


@register.filter
def fmt_count(value):
    return count(value)


@register.filter
def fmt_percent(value):
    return percent(value)


@register.filter
def fmt_units(value):
    return units(value)


@register.filter
def fmt_cents(value):
    return cents(value)


@register.filter
def fmt_metric(value, kind):
    return metric(value, kind)


@register.filter
def fmt_delta(value):
    return delta_text(value)


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
