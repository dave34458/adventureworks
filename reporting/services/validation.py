"""Payload validation shared by the editor and report snapshots."""
import json
import math
import re
from datetime import date

from django.core.serializers.json import DjangoJSONEncoder

from ..constants import FIELD_LABELS, KIND_CHOICES, SECTION_LABELS


def humanize_payload_error(message):
    match = re.match(r"payload((?:\.[A-Za-z_]\w*|\[\d+\])+):\s*(.*)", message)
    if match is None:
        return message
    tokens = re.findall(r"\.([A-Za-z_]\w*)|\[(\d+)\]", match.group(1))
    keys = [key for key, _ in tokens if key]
    row = next((int(index) + 1 for _, index in tokens if index), None)
    bits = []
    if keys:
        bits.append(SECTION_LABELS.get(keys[0], keys[0].replace("_", " ").title()))
    if row is not None:
        bits.append(f"row {row}")
    if len(keys) > 1:
        field = keys[-1]
        bits.append(FIELD_LABELS.get(field, field.replace("_", " ").title()))
    return f"{', '.join(bits)}: {match.group(2)}" if bits else match.group(2)


class PayloadValidationError(ValueError):
    pass


MAX_PAYLOAD_BYTES = 256_000


def _invalid(path, message):
    raise PayloadValidationError(f"{path}: {message}")


def _text(max_len=300, min_len=0):
    def check(value, path):
        if not isinstance(value, str):
            _invalid(path, "must be text")
        if len(value) < min_len:
            _invalid(path, "must not be empty")
        if len(value) > max_len:
            _invalid(path, f"must be at most {max_len} characters")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            _invalid(path, "must not contain control characters")
    return check


def _optional(rule):
    def check(value, path):
        if value is not None:
            rule(value, path)
    return check


def _integer(min_value=0, max_value=1_000_000_000):
    def check(value, path):
        if not isinstance(value, int) or isinstance(value, bool):
            _invalid(path, "must be a whole number")
        if not min_value <= value <= max_value:
            _invalid(path, f"must be between {min_value} and {max_value}")
    return check


def _number(min_value=None, max_value=None):
    def check(value, path):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            _invalid(path, "must be a number")
        if not math.isfinite(value):
            _invalid(path, "must be finite")
        if min_value is not None and value < min_value:
            _invalid(path, f"must be at least {min_value}")
        if max_value is not None and value > max_value:
            _invalid(path, f"must be at most {max_value}")
    return check


def _choice(*allowed, nullable=False):
    allowed = tuple(allowed)

    def check(value, path):
        if value is None and nullable:
            return
        if value not in allowed:
            options = ", ".join(repr(item) for item in allowed)
            _invalid(path, f"must be one of {options}")
    return check


def _boolean(value, path):
    if not isinstance(value, bool):
        _invalid(path, "must be true or false")


def _pattern(pattern, message):
    def check(value, path):
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            _invalid(path, message)
    return check


def _date(value, path):
    if not isinstance(value, str):
        _invalid(path, "must be an ISO date")
    try:
        date.fromisoformat(value)
    except ValueError:
        _invalid(path, "must be an ISO date")


def _points(value, path):
    if not isinstance(value, str):
        _invalid(path, "must be a points string")
    if len(value) > 10_000:
        _invalid(path, "must be at most 10000 characters")
    for pair in value.split():
        parts = pair.split(",")
        if len(parts) != 2:
            _invalid(path, "must contain x,y pairs")
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            _invalid(path, "must contain x,y pairs")
        if not math.isfinite(x) or not math.isfinite(y):
            _invalid(path, "must contain finite coordinates")
        if not 0 <= x <= 960 or not 0 <= y <= 260:
            _invalid(path, "coordinates must fit the chart")


def _object(fields, nullable=False):
    expected = set(fields)

    def check(value, path):
        if value is None and nullable:
            return
        if not isinstance(value, dict):
            _invalid(path, "must be an object")
        missing = expected - set(value)
        extra = set(value) - expected
        if missing:
            _invalid(path, f"missing key(s): {', '.join(sorted(missing))}")
        if extra:
            _invalid(path, f"unexpected key(s): {', '.join(sorted(extra))}")
        for name, rule in fields.items():
            rule(value[name], f"{path}.{name}")
    return check


def _rows(fields, max_rows=50):
    row = _object(fields)

    def check(value, path):
        if not isinstance(value, list):
            _invalid(path, "must be a list")
        if len(value) > max_rows:
            _invalid(path, f"must contain at most {max_rows} rows")
        for index, item in enumerate(value):
            row(item, f"{path}[{index}]")
    return check


def _kpis(value, path):
    _rows(KPI_FIELDS, 20)(value, path)
    for index, kpi in enumerate(value):
        value_path = f"{path}[{index}].value"
        number = kpi["value"]
        if number is not None:
            if kpi["value_kind"] == "percent" and not 0 <= number <= 100:
                _invalid(value_path, "must be between 0 and 100")
            if number < 0 and kpi["label"] not in KPI_NEGATIVE_LABELS:
                _invalid(value_path, "must be at least 0")
        delta, direction = kpi["delta"], kpi["dir"]
        if delta is None:
            if direction not in (None, ""):
                _invalid(f"{path}[{index}].dir", "must be empty when delta is empty")
            continue
        expected = "up" if delta > 0 else "down" if delta < 0 else "flat"
        if direction != expected:
            inverted = {"up": "down", "down": "up"}.get(expected, expected)
            if not (kpi["label"] in KPI_INVERTED_LABELS and direction == inverted):
                _invalid(f"{path}[{index}].dir", f"must be {expected} for this delta")


def _total_100(rows, field, path):
    if not rows:
        return
    total = sum(float(row[field]) for row in rows)
    if abs(total - 100) > 0.5:
        _invalid(path, f"{field} values must add up to 100 (got {total:.1f})")


KPI_KINDS = tuple(kind for kind, _ in KIND_CHOICES)
KPI_NEGATIVE_LABELS = {"Gross profit"}
KPI_INVERTED_LABELS = {
    "Cost of goods",
    "Cost of goods sold",
    "Cost per $1 revenue",
    "Procurement spend",
    "Scrap rate",
    "Rejected receipts",
}
KPI_FIELDS = {
    "label": _text(120, 1),
    "value": _optional(_number()),
    "value_kind": _choice(*KPI_KINDS),
    "delta": _optional(_number(-1_000_000_000, 1_000_000_000)),
    "dir": _choice("", "up", "down", "flat", nullable=True),
    "cap": _text(300),
}
RANK_FIELDS = {
    "name": _text(200, 1),
    "value": _number(0, 1_000_000_000_000),
    "pct": _number(0, 100),
}
RANK_NOTE_FIELDS = {**RANK_FIELDS, "note": _text(300)}
SALES_TREND_FIELDS = {
    "label": _text(20, 1),
    "full": _text(40, 1),
    "money": _number(0),
    "orders": _integer(),
    "height": _number(0, 100),
    "prev_full": _text(40),
    "prev_money": _optional(_number(0)),
    "prev_orders": _optional(_integer()),
    "prev_h": _number(0, 100),
}
CUSTOMER_GROWTH_FIELDS = {
    "label": _text(20, 1),
    "full": _text(40, 1),
    "act": _integer(),
    "nw": _integer(),
    "ret": _integer(),
    "new_h": _number(0, 100),
    "ret_h": _number(0, 100),
}
CUSTOMER_CHANNEL_FIELDS = {
    "name": _text(80, 1),
    "pct": _number(0, 100),
    "cust_pct": _number(0, 100),
    "cls": _choice("online", "store"),
    "money": _number(0),
    "customers": _integer(),
    "aov": _optional(_number(0)),
}
BUBBLE_FIELDS = {
    "code": _pattern(r"[A-Z]{2,3}", "must be a country code"),
    "lat": _number(-90, 90),
    "lon": _number(-180, 180),
    "r": _number(0, 100),
    "title": _text(300, 1),
}
CUSTOMER_BIGGEST_FIELDS = {
    "id": _integer(),
    "name": _text(200, 1),
    "store": _boolean,
    "territory": _text(100),
    "orders": _integer(),
    "rev": _number(0),
}
LEGEND_FIELDS = {
    "n": _integer(),
    "rev": _number(0),
}
COMBO_BAR_FIELDS = {
    "x": _number(0, 960),
    "y": _number(0, 260),
    "h": _number(0, 260),
    "w": _number(0, 960),
    "t": _text(300, 1),
}
COMBO_DOT_FIELDS = {
    "cls": _choice("dotp", "dotc"),
    "x": _number(0, 960),
    "y": _number(0, 260),
    "t": _text(300, 1),
}
COMBO_XTICK_FIELDS = {
    "x": _number(0, 960),
    "lab": _text(20, 1),
}
COMBO_YTICK_FIELDS = {
    "y": _number(0, 260),
    "lab": _text(40, 1),
}
COMBO_FIELDS = {
    "bars": _rows(COMBO_BAR_FIELDS, 36),
    "cur_pts": _points,
    "prev_pts": _points,
    "dots": _rows(COMBO_DOT_FIELDS, 72),
    "xticks": _rows(COMBO_XTICK_FIELDS, 36),
    "lticks": _rows(COMBO_YTICK_FIELDS, 12),
    "rticks": _rows(COMBO_YTICK_FIELDS, 12),
}
DONUT_FIELDS = {
    "cls": _pattern(r"c[1-9]\d?", "must be a chart colour class"),
    "pct": _number(0, 100),
    "t": _text(300, 1),
    "dash": _number(0, 1000),
    "off": _number(-1000, 0),
}
DONUT_MID_FIELDS = {
    "big": _number(0),
    "small": _text(80, 1),
}
MIX_FIELDS = {
    "name": _text(200, 1),
    "cls": _pattern(r"c[1-9]\d?", "must be a chart colour class"),
    "pct": _number(0, 100),
    "money": _number(0),
    "margin": _number(-100, 100),
}
REV_TREND_FIELDS = {
    "label": _text(20, 1),
    "full": _text(40, 1),
    "money": _number(0),
    "height": _number(0, 100),
    "prev_full": _text(40),
    "prev_money": _optional(_number(0)),
    "prev_h": _number(0, 100),
}
REV_PRODUCT_FIELDS = {
    "id": _integer(),
    "name": _text(200, 1),
    "rev": _number(0),
    "cost": _number(0),
    "profit": _number(),
    "margin": _number(-100, 100),
}
COST_PIPELINE_FIELDS = {
    "k": _text(80, 1),
    "big": _number(0),
    "kind": _choice(*KPI_KINDS),
    "cap": _text(300),
    "cls": _choice("", "bad"),
}
COST_TREND_FIELDS = {
    "label": _text(20, 1),
    "full": _text(40, 1),
    "money": _number(0),
    "margin": _number(-100, 100),
    "height": _number(0, 100),
    "prev_full": _text(40),
    "prev_money": _optional(_number(0)),
    "prev_h": _number(0, 100),
}
COST_BIGGEST_FIELDS = {
    "id": _integer(),
    "vendor": _text(200, 1),
    "date": _date,
    "lines": _integer(),
    "total": _number(0),
    "status": _choice("Pending", "Approved", "Rejected", "Complete"),
    "cls": _choice("", "online", "bad"),
}
COST_CHANGE_FIELDS = {
    "name": _text(200, 1),
    "old": _number(0),
    "now": _number(0),
    "pct": _number(-100, 1_000),
    "note": _text(300),
}
PERFORMANCE_FIELDS = {
    "cost": _number(0, 1_000),
    "margin": _number(-1_000, 100),
    "note": _text(1000),
}
REPORT_PAYLOADS = {
    "sales": {
        "kpis": _kpis,
        "trend": _rows(SALES_TREND_FIELDS, 36),
        "products": _rows(RANK_FIELDS, 50),
        "low_products": _rows(RANK_FIELDS, 50),
    },
    "customer-profile": {
        "kpis": _kpis,
        "growth": _rows(CUSTOMER_GROWTH_FIELDS, 36),
        "channels": _rows(CUSTOMER_CHANNEL_FIELDS, 10),
        "countries": _rows(RANK_FIELDS, 50),
        "bubbles": _rows(BUBBLE_FIELDS, 50),
        "cities": _rows(RANK_FIELDS, 50),
        "network": _rows(RANK_NOTE_FIELDS, 50),
        "frequency": _rows(RANK_FIELDS, 50),
        "biggest": _rows(CUSTOMER_BIGGEST_FIELDS, 20),
        "new_legend": _object(LEGEND_FIELDS),
        "ret_legend": _object(LEGEND_FIELDS),
    },
    "revenue-and-loss": {
        "kpis": _kpis,
        "combo": _object(COMBO_FIELDS),
        "donut": _rows(DONUT_FIELDS, 20),
        "donut_mid": _object(DONUT_MID_FIELDS),
        "mix": _rows(MIX_FIELDS, 20),
        "rev_trend": _rows(REV_TREND_FIELDS, 36),
        "declining": _rows(RANK_NOTE_FIELDS, 50),
        "leaks": _rows(RANK_NOTE_FIELDS, 50),
        "products": _rows(REV_PRODUCT_FIELDS, 20),
    },
    "cost": {
        "kpis": _kpis,
        "pipeline": _rows(COST_PIPELINE_FIELDS, 10),
        "trend": _rows(COST_TREND_FIELDS, 36),
        "mix": _rows(MIX_FIELDS, 20),
        "donut": _rows(DONUT_FIELDS, 20),
        "donut_mid": _object(DONUT_MID_FIELDS),
        "vendors": _rows(RANK_NOTE_FIELDS, 50),
        "products": _rows(RANK_NOTE_FIELDS, 50),
        "scrap_metric": _choice("cost", "units"),
        "reasons": _rows(RANK_NOTE_FIELDS, 50),
        "changes": _rows(COST_CHANGE_FIELDS, 50),
        "biggest": _rows(COST_BIGGEST_FIELDS, 20),
        "performance": _object(PERFORMANCE_FIELDS, nullable=True),
    },
}


def validate_report_payload(module, payload):
    if not isinstance(payload, dict):
        _invalid("payload", "must be an object")
    try:
        encoded = json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False)
    except (TypeError, ValueError):
        _invalid("payload", "must be JSON-serializable")
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        _invalid("payload", f"must be at most {MAX_PAYLOAD_BYTES} bytes")
    schema = REPORT_PAYLOADS.get(module)
    if schema is None:
        _invalid("module", "is not a report module")
    _object(schema)(payload, "payload")

    if module in ("revenue-and-loss", "cost"):
        _total_100(payload["mix"], "pct", "payload.mix")
        _total_100(payload["donut"], "pct", "payload.donut")
    if module == "customer-profile":
        _total_100(payload["channels"], "pct", "payload.channels")
        _total_100(payload["channels"], "cust_pct", "payload.channels")
    if module == "cost" and payload["performance"]:
        performance = payload["performance"]
        total = performance["cost"] + performance["margin"]
        if abs(total - 100) > 0.5:
            _invalid("payload.performance", f"cost and margin must add up to 100 (got {total:.1f})")


# ---------------------------------------------------------------------------
# Pages: home, the central dashboard, the four report panels, and the generic table
# browser for the remaining source tables. Each report is one view: it builds its own
# data and template.
