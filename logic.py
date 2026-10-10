"""If-specific routing and editor helpers around the shared condition language."""

from __future__ import annotations

import json

from . import conditions

DEFAULTS = {
    "combinator": "all",
    "conditions": [{"path": "status", "operator": "equals", "value": "paid",
                    "value_type": "auto", "case_sensitive": True}],
    "parse_json": "auto",
    "on_error": "fail",
}
MAX_SAMPLE_CHARS = 262_144


def settings(raw):
    """Merge manifest defaults with stored settings, keeping framework-owned keys untouched."""
    return {**DEFAULTS, **conditions.thaw(raw or {})}


def group(raw):
    """Validate merged settings and return the evaluation group."""
    return conditions.configuration(settings(raw))


def route(raw_message, raw_settings):
    """Decide the branch of one message: ``{"branch": "true"|"false"|None, ...evaluation}``.

    ``branch`` is None when the ``fail`` policy stops the activation.
    """
    evaluation = conditions.evaluate(group(raw_settings), raw_message)
    matched = evaluation["matched"]
    return {**evaluation, "branch": None if matched is None else ("true" if matched else "false")}


def output_text(raw_message):
    """The routed payload: the received text unchanged, or compact JSON for a native value."""
    if isinstance(raw_message, str):
        return raw_message
    try:
        return conditions.compact(raw_message)
    except (TypeError, ValueError, RecursionError):
        raise conditions.ConditionError("message_not_text", "the message is not text or JSON.") from None


def editor_conditions(rows):
    """Convert editor rows (``value_text``) into canonical condition objects.

    The editor sends the text typed in the value field; it is standard JSON when it
    parses (100, true, null, ["FR","BE"], "quoted text") and plain text otherwise.
    """
    if not isinstance(rows, list):
        return rows
    converted = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or "value_text" not in row:
            converted.append(row)
            continue
        item = {key: value for key, value in row.items() if key != "value_text"}
        try:
            item["value"] = conditions.parse_value_text(row["value_text"])
        except conditions.ConditionError as exc:
            exc.index = index
            raise
        converted.append(item)
    return converted


def editor_settings(raw):
    """Canonical settings from an editor draft; unknown draft keys are rejected by validation."""
    draft = dict(raw or {})
    if "conditions" in draft:
        draft["conditions"] = editor_conditions(draft["conditions"])
    return draft


def validation(raw_draft, stored=None):
    """Every problem of an editor draft, as JSON-safe descriptions (empty when valid)."""
    try:
        draft = settings({**conditions.thaw(stored or {}), **editor_settings(raw_draft)})
    except conditions.ConditionError as exc:
        return [exc.describe()]
    return [error.describe() for error in conditions.problems(draft)]


def preview(raw_draft, sample, stored=None):
    """Evaluate a draft on a pasted sample exactly like a text message, without running the graph."""
    errors = validation(raw_draft, stored)
    if errors:
        return {"valid": False, "errors": errors}
    if not isinstance(sample, str):
        return {"valid": True, "errors": [], "sample_error": {"code": "sample_type", "params": {},
                "message": "The sample must be text."}}
    if len(sample) > MAX_SAMPLE_CHARS:
        return {"valid": True, "errors": [], "sample_error": {"code": "sample_too_large",
                "params": {"max": MAX_SAMPLE_CHARS}, "message": "The sample is longer than {max} characters."}}
    draft = settings({**conditions.thaw(stored or {}), **editor_settings(raw_draft)})
    result = route(sample, draft)
    return {"valid": True, "errors": [], "branch": result["branch"], "outcomes": result["outcomes"],
            "failure": result["failure"], "warnings": result["warnings"],
            "combinator": draft["combinator"], "on_error": draft["on_error"]}


def summary(result):
    """Compact, content-free JSON summary of one routing decision for run state."""
    matched = [item["index"] for item in result["outcomes"] if item["outcome"] == "true"]
    errors = [item["index"] for item in result["outcomes"] if item["outcome"] == "error"]
    return {"branch": result["branch"], "matched": matched, "errors": errors,
            "conditions": len(result["outcomes"])}


def where(index, group_settings):
    """``path operator`` of a condition, without its configured value or any message content."""
    rows = group_settings.get("conditions") if isinstance(group_settings, dict) else None
    item = rows[index - 1] if isinstance(rows, list) and index and 0 < index <= len(rows) else None
    if not isinstance(item, dict):
        return ""
    return f"{item.get('path') or '$'} {item.get('operator')}"


def describe_failure(failure, group_settings):
    """English diagnostic naming the condition index, its path/operator and the reason."""
    index = failure.get("index")
    reason = failure.get("message", "")
    return f"Condition {index} ({where(index, group_settings)}): {reason}" if index else reason


def card_summary(raw_settings):
    """First condition in short form, the remaining count and the combinator, or None if invalid."""
    try:
        valid = group(raw_settings)
    except conditions.ConditionError:
        return None
    return {"first": conditions.short_label(valid.conditions[0]),
            "more": len(valid.conditions) - 1, "combinator": valid.combinator}


def editor_rows(raw_settings):
    """Rows for the server-rendered editor; invalid stored rows stay editable as text."""
    merged = settings(raw_settings)
    rows = merged.get("conditions")
    if not isinstance(rows, list) or not rows:
        rows = [dict(DEFAULTS["conditions"][0])]
    result = []
    for row in rows[:conditions.MAX_CONDITIONS]:
        row = row if isinstance(row, dict) else {}
        operator = row.get("operator") if row.get("operator") in conditions.OPERATORS else "equals"
        result.append({
            "path": row.get("path") if isinstance(row.get("path"), str) else "",
            "operator": operator,
            "value_text": "" if operator in conditions.VALUELESS or "value" not in row
                          else conditions.value_text(row.get("value")),
            "value_type": row.get("value_type") if row.get("value_type") in conditions.VALUE_TYPES else "auto",
            "case_sensitive": row.get("case_sensitive", True) is not False,
        })
    return result


def dumps(value):
    """Stable compact JSON for metadata and last-message previews."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
