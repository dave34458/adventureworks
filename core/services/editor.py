"""Saved-report payload editor helpers."""
import copy

from ..constants import (
    EDITABLE_KEYS,
    EDITOR_CHECKBOX_FIELDS,
    EDITOR_DATE_FIELDS,
    EDITOR_INTEGER_FIELDS,
    EDITOR_NUMBER_FIELDS,
    EDITOR_SELECTS,
    FIELD_LABELS,
    SECTION_LABELS,
)
from .validation import (
    PayloadValidationError,
    humanize_payload_error,
    validate_report_payload,
)


def _select_options(tab, section, name, current):
    pairs = EDITOR_SELECTS.get(name)
    if name == "cls":
        if section == "channels":
            pairs = (("online", "Individuals"), ("store", "Stores"))
        elif tab == "cost" and section == "biggest":
            pairs = (("", "None"), ("online", "Online"), ("bad", "Rejected"))
    if pairs is None:
        return None
    current = "" if current is None else str(current)
    return [{"value": value, "label": label, "selected": value == current}
            for value, label in pairs]


def _editor_type(tab, section, name, value):
    if name in EDITOR_DATE_FIELDS:
        return "date"
    if name in EDITOR_CHECKBOX_FIELDS:
        return "checkbox"
    if _select_options(tab, section, name, value) is not None:
        return "select"
    if name in EDITOR_INTEGER_FIELDS:
        return "integer"
    if name in EDITOR_NUMBER_FIELDS or isinstance(value, (int, float)):
        return "number"
    return "text"


def _editor_field(tab, section, name, value):
    field_type = _editor_type(tab, section, name, value)
    if field_type == "date" and value is not None:
        value = value.date().isoformat() if hasattr(value, "date") else str(value)[:10]
    field = {
        "name": name,
        "label": FIELD_LABELS.get(name, name.replace("_", " ").title()),
        "type": field_type,
        "value": "" if value is None else value,
    }
    if field_type == "number":
        field["step"] = "any"
    elif field_type == "integer":
        field["step"] = "1"
    elif field_type == "select":
        field["options"] = _select_options(tab, section, name, value)
    return field


def editor_sections(tab, payload):
    sections = []
    for key in EDITABLE_KEYS.get(tab, []):
        value = payload.get(key)
        label = SECTION_LABELS.get(key, key.replace("_", " ").title())
        if isinstance(value, list) and all(isinstance(row, dict) for row in value):
            columns = []
            for row in value:
                for field, field_value in row.items():
                    if not isinstance(field_value, (dict, list)) and field not in columns:
                        columns.append(field)
            sections.append({
                "key": key,
                "label": label,
                "kind": "table",
                "columns": [{"name": c, "label": c.replace("_", " ").title()}
                            for c in columns],
                "rows": [
                    {"index": index,
                     "fields": [_editor_field(tab, key, c, row.get(c)) for c in columns]}
                    for index, row in enumerate(value)
                ],
            })
        elif isinstance(value, dict):
            sections.append({
                "key": key,
                "label": label,
                "kind": "dict",
                "items": [_editor_field(tab, key, field, field_value)
                          for field, field_value in value.items()
                          if not isinstance(field_value, (dict, list))],
            })
        else:
            sections.append({
                "key": key,
                "label": label,
                "kind": "scalar",
                "value": "" if value is None else value,
            })
    return sections


def apply_editor(tab, payload, post):
    payload = copy.deepcopy(payload)
    edits = []
    for key in EDITABLE_KEYS.get(tab, []):
        original = payload.get(key)
        if isinstance(original, list) and all(isinstance(row, dict) for row in original):
            for index, row in enumerate(original):
                for field, field_value in list(row.items()):
                    if not isinstance(field_value, (dict, list)):
                        edits.append((row, field, field_value,
                                      f"editor-{key}-{index}-{field}", key, index))
        elif isinstance(original, dict):
            for field, field_value in list(original.items()):
                if not isinstance(field_value, (dict, list)):
                    edits.append((original, field, field_value,
                                  f"editor-{key}-{field}", key, None))
        else:
            edits.append((payload, key, original, f"editor-{key}", key, None))

    errors = []
    for container, field, original_value, name, section, index in edits:
        field_type = _editor_type(tab, section, field, original_value)
        if name not in post and field_type != "checkbox":
            continue
        value = post.get(name, "")
        where = SECTION_LABELS.get(section, section.replace("_", " ").title())
        if index is not None:
            where += f", row {index + 1}"
        where += f", {FIELD_LABELS.get(field, field.replace('_', ' ').title())}"
        if field_type == "checkbox":
            new_value = str(value).lower() in {"1", "true", "on", "yes"}
        elif field_type == "integer":
            if value.strip() == "":
                new_value = None
            else:
                try:
                    new_value = int(value)
                except (TypeError, ValueError):
                    errors.append(f"{where}: must be a whole number.")
                    continue
        elif field_type == "number":
            if value.strip() == "":
                new_value = None
            else:
                try:
                    new_value = float(value)
                except (TypeError, ValueError):
                    errors.append(f"{where}: must be a number.")
                    continue
        else:
            new_value = value or None if field_type == "date" else value
        container[field] = new_value

    if errors:
        return None, errors
    try:
        validate_report_payload(tab, payload)
    except PayloadValidationError as exc:
        return None, [humanize_payload_error(str(exc))]
    return payload, []
