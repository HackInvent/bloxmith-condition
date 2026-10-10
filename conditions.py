"""Shared condition language of the If, Switch and Filter blocks (block-local copy).

Pure functions only: no framework import, no I/O, no evaluation of code and no
mutation of the message. Every error carries a stable machine ``code``, its
``params`` and an English ``message``; user interfaces translate the code.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
import re

COMBINATORS = ("all", "any")
PARSE_MODES = ("auto", "always", "never")
ERROR_POLICIES = ("fail", "no_match")
VALUE_TYPES = ("auto", "string", "number", "boolean", "datetime")
OPERATORS = (
    "equals", "not_equals", "exists", "not_exists", "is_empty", "is_not_empty",
    "contains", "not_contains", "starts_with", "ends_with",
    "greater_than", "greater_or_equal", "less_than", "less_or_equal",
    "matches_regex", "in_list", "not_in_list", "is_true", "is_false",
)
# Operators whose configured value is ignored, as stated by the shared specification.
VALUELESS = frozenset({"exists", "not_exists", "is_empty", "is_not_empty", "is_true", "is_false"})
ORDERING = frozenset({"greater_than", "greater_or_equal", "less_than", "less_or_equal"})
TEXTUAL = frozenset({"contains", "not_contains", "starts_with", "ends_with", "matches_regex"})
LISTS = frozenset({"in_list", "not_in_list"})
NEGATED = {"not_equals": "equals", "not_contains": "contains", "not_in_list": "in_list"}
ALLOWED_TYPES = {
    **{operator: VALUE_TYPES for operator in OPERATORS},
    **{operator: ("auto", "number", "datetime") for operator in ORDERING},
    **{operator: ("auto", "string") for operator in TEXTUAL},
}
CONDITION_KEYS = frozenset({"path", "operator", "value", "value_type", "case_sensitive"})

MAX_CONDITIONS = 32
MAX_PATH_SEGMENTS = 32
MAX_PATH_LENGTH = 512
MAX_PATTERN = 256
MAX_SUBJECT = 10_000
MAX_LIST = 256
MAX_NUMBER_TEXT = 1_000

MISSING = object()
_KEY = re.compile(r"[^.\[\]]+")
_INDEX = re.compile(r"0|[1-9][0-9]{0,8}")
_INTEGER = re.compile(r"[+-]?[0-9]+", re.ASCII)
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)
_TRUE_WORDS = frozenset({"true", "yes", "1"})
_FALSE_WORDS = frozenset({"false", "no", "0"})


class ConditionError(ValueError):
    """Explicit configuration or evaluation failure, never a silent fallback.

    ``index`` is the 1-based condition position (None for group settings) and
    ``field`` the condition field or setting at fault.
    """

    def __init__(self, code, template, params=None, *, index=None, field=None):
        self.code = code
        self.template = template
        self.params = dict(params or {})
        self.message = template.format(**self.params)
        self.index = index
        self.field = field
        super().__init__(self.message)

    def describe(self):
        """Return a JSON-safe description for UI responses and logs."""
        return {"index": self.index, "field": self.field, "code": self.code,
                "params": self.params, "message": self.message}

    def __str__(self):
        return f"Condition {self.index}: {self.message}" if self.index else self.message


def _error(code, message, params=None, **where):
    return ConditionError(code, message, params, **where)


# --------------------------------------------------------------------------- values


def thaw(value):
    """Return plain dicts/lists for read-only mappings and tuples (prepare-time snapshots)."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(item) for item in value]
    return value


def _finite_float(text):
    number = float(text)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def _reject_constant(_name):
    raise ValueError("NaN and Infinity are not JSON")


def strict_json(text):
    """Parse standard JSON only: no NaN/Infinity, finite numbers. Return (ok, value)."""
    try:
        return True, json.loads(text, parse_float=_finite_float, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError):
        return False, None


def is_number(value):
    """JSON number: int or finite float, never a boolean."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def json_kind(value):
    """Name the JSON type of a native value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if is_number(value):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "other"


def compact(value):
    """Compact JSON text, keeping non-ASCII characters and the received key order."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def text_form(value):
    """Text used when comparing as strings: objects and arrays become compact JSON."""
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return compact(value)


def to_number(value):
    """JSON number, or text holding a finite decimal number (surrounding spaces ignored)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip()
        if not text or len(text) > MAX_NUMBER_TEXT or not _DECIMAL.fullmatch(text):
            return None
        if _INTEGER.fullmatch(text):
            return int(text)
        number = float(text)
        return number if math.isfinite(number) else None
    return None


def to_boolean(value):
    """true/false, the words true|false|yes|no|1|0 in any case, or the numbers 1/0."""
    if isinstance(value, bool):
        return value
    if is_number(value):
        return True if value == 1 else False if value == 0 else None
    if isinstance(value, str):
        word = value.strip().lower()
        return True if word in _TRUE_WORDS else False if word in _FALSE_WORDS else None
    return None


def to_instant(value):
    """ISO 8601 date or date-time text; a value without offset is UTC."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def json_equal(left, right):
    """Structural JSON equality: 1 equals 1.0, booleans never equal numbers, key order ignored."""
    pending = [(left, right)]
    while pending:
        a, b = pending.pop()
        kind = json_kind(a)
        if kind != json_kind(b):
            return False
        if kind == "array":
            if len(a) != len(b):
                return False
            pending.extend(zip(a, b))
        elif kind == "object":
            if a.keys() != b.keys():
                return False
            pending.extend((a[key], b[key]) for key in a)
        elif a != b:
            return False
    return True


def _fold(text, case_sensitive):
    return text if case_sensitive else text.casefold()


def text_equal(left, right, case_sensitive):
    return _fold(left, case_sensitive) == _fold(right, case_sensitive)


def auto_equal(left, right, case_sensitive):
    """``auto``: JSON types as received; number against numeric text compares numerically."""
    if is_number(left) and is_number(right):
        return left == right
    if is_number(left) and isinstance(right, str) and to_number(right) is not None:
        return left == to_number(right)
    if isinstance(left, str) and is_number(right) and to_number(left) is not None:
        return to_number(left) == right
    if json_kind(left) == json_kind(right):
        if isinstance(left, str):
            return text_equal(left, right, case_sensitive)
        return json_equal(left, right)
    return text_equal(text_form(left), text_form(right), case_sensitive)


# --------------------------------------------------------------------------- paths


def parse_path(path, *, index=None):
    """Parse ``customer.email``, ``items[0].price``, ``rows[2]`` or ``[0].name`` into steps."""
    if not isinstance(path, str):
        raise _error("path_type", "path must be text.", index=index, field="path")
    if path == "":
        return ()
    if len(path) > MAX_PATH_LENGTH:
        raise _error("path_too_long", "path is longer than {max} characters.", {"max": MAX_PATH_LENGTH},
                     index=index, field="path")
    invalid = _error("path_invalid", "path is not valid: separate names with dots and use [index] "
                     "brackets, for example items[0].price.", index=index, field="path")
    steps, position = [], 0
    while position < len(path):
        char = path[position]
        if char == "[":
            end = path.find("]", position)
            if end < 0 or not _INDEX.fullmatch(path[position + 1:end]):
                raise invalid
            steps.append(int(path[position + 1:end]))
            position = end + 1
        else:
            if char == ".":
                if not steps:
                    raise invalid
                position += 1
            elif steps:
                raise invalid
            match = _KEY.match(path, position)
            if not match:
                raise invalid
            key = match.group()
            if key != key.strip():
                raise _error("path_spaces", "A name in path starts or ends with a space.", index=index, field="path")
            steps.append(key)
            position = match.end()
        if len(steps) > MAX_PATH_SEGMENTS:
            raise _error("path_too_deep", "path has more than {max} segments.", {"max": MAX_PATH_SEGMENTS},
                         index=index, field="path")
    return tuple(steps)


def resolve(value, steps):
    """Follow parsed steps; anything that does not resolve is MISSING, not an error."""
    for step in steps:
        if isinstance(step, int):
            if not isinstance(value, list) or step >= len(value):
                return MISSING
            value = value[step]
        else:
            if not isinstance(value, dict) or step not in value:
                return MISSING
            value = value[step]
    return value


# --------------------------------------------------------------------------- configuration


class Condition:
    """One validated condition with its parsed path and compiled pattern."""

    __slots__ = ("index", "path", "operator", "value", "value_type", "case_sensitive", "steps", "pattern")

    def __init__(self, index, data, steps, pattern):
        self.index = index
        self.path = data["path"]
        self.operator = data["operator"]
        self.value = data["value"]
        self.value_type = data["value_type"]
        self.case_sensitive = data["case_sensitive"]
        self.steps = steps
        self.pattern = pattern

    def to_dict(self):
        return {"path": self.path, "operator": self.operator, "value": self.value,
                "value_type": self.value_type, "case_sensitive": self.case_sensitive}


def _check_value(data, index):
    """Validate the configured value for its operator and value_type; return a compiled pattern."""
    operator, value_type, value = data["operator"], data["value_type"], data["value"]
    where = {"index": index, "field": "value"}
    if operator in LISTS:
        if not isinstance(value, list):
            raise _error("list_type", "{operator} needs a JSON array of values, for example [\"FR\",\"BE\"].",
                         {"operator": operator}, **where)
        if len(value) > MAX_LIST:
            raise _error("list_too_long", "The list has more than {max} items.", {"max": MAX_LIST}, **where)
        items = value
    else:
        items = [value]
    if operator == "matches_regex":
        if not isinstance(value, str) or not value:
            raise _error("pattern_type", "matches_regex needs a non-empty text pattern; wrap it in double "
                         "quotes if it looks like JSON.", **where)
        if len(value) > MAX_PATTERN:
            raise _error("pattern_too_long", "The pattern is longer than {max} characters.", {"max": MAX_PATTERN}, **where)
        try:
            return re.compile(value, 0 if data["case_sensitive"] else re.IGNORECASE)
        except (re.error, RecursionError, OverflowError) as exc:
            raise _error("pattern_invalid", "The pattern is not a valid regular expression: {detail}.",
                         {"detail": str(getattr(exc, "msg", "") or "invalid pattern")}, **where) from None
    if operator in TEXTUAL and value == "":
        raise _error("value_empty", "{operator} needs a non-empty value.", {"operator": operator}, **where)
    if operator in ORDERING and value_type == "auto":
        if to_number(value) is None:
            raise _error("value_not_numeric_auto", "{operator} with value_type auto compares numbers: enter a "
                         "number, or choose value_type datetime to compare dates.", {"operator": operator}, **where)
        return None
    checks = {"number": (to_number, "value_not_number", "The value must be a finite number for value_type number."),
              "boolean": (to_boolean, "value_not_boolean", "The value must be true/false, yes/no or 1/0 for value_type boolean."),
              "datetime": (to_instant, "value_not_datetime", "The value must be an ISO 8601 date or date-time for value_type datetime.")}
    if value_type in checks:
        convert, code, message = checks[value_type]
        if any(convert(item) is None for item in items):
            raise _error(code, message, **where)
    return None


def condition(raw, index):
    """Validate one condition object and return a :class:`Condition`."""
    if not isinstance(raw, dict):
        raise _error("condition_type", "Each condition must be an object.", index=index, field="condition")
    unknown = sorted(set(raw) - CONDITION_KEYS)
    if unknown:
        raise _error("condition_unknown_key", "Unknown condition field: {key}.", {"key": str(unknown[0])[:80]},
                     index=index, field="condition")
    data = {"path": raw.get("path", ""), "operator": raw.get("operator"),
            "value_type": raw.get("value_type", "auto"), "case_sensitive": raw.get("case_sensitive", True)}
    steps = parse_path(data["path"], index=index)
    if data["operator"] not in OPERATORS:
        raise _error("operator_invalid", "Unknown operator: {operator}.",
                     {"operator": str(data["operator"])[:80]}, index=index, field="operator")
    operator = data["operator"]
    if data["value_type"] not in VALUE_TYPES:
        raise _error("value_type_invalid", "value_type must be auto, string, number, boolean or datetime.",
                     index=index, field="value_type")
    if data["value_type"] not in ALLOWED_TYPES[operator]:
        raise _error("type_unsupported", "{operator} does not support value_type {value_type}.",
                     {"operator": operator, "value_type": data["value_type"]}, index=index, field="value_type")
    if not isinstance(data["case_sensitive"], bool):
        raise _error("case_sensitive_type", "case_sensitive must be true or false.", index=index, field="case_sensitive")
    if operator in VALUELESS:
        data["value"] = None
        return Condition(index, data, steps, None)
    if "value" not in raw:
        raise _error("value_missing", "{operator} needs a value.", {"operator": operator}, index=index, field="value")
    data["value"] = raw["value"]
    try:
        compact(data["value"])
    except (TypeError, ValueError, RecursionError):
        raise _error("value_not_json", "The value must be finite JSON.", index=index, field="value") from None
    return Condition(index, data, steps, _check_value(data, index))


class Group:
    """A validated condition group plus the message and error policies."""

    __slots__ = ("combinator", "conditions", "parse_json", "on_error")

    def __init__(self, combinator, conditions, parse_json, on_error):
        self.combinator = combinator
        self.conditions = conditions
        self.parse_json = parse_json
        self.on_error = on_error

    def to_config(self):
        return {"combinator": self.combinator, "conditions": [item.to_dict() for item in self.conditions],
                "parse_json": self.parse_json, "on_error": self.on_error}


def _settings(raw):
    settings = {"combinator": raw.get("combinator", "all"), "parse_json": raw.get("parse_json", "auto"),
                "on_error": raw.get("on_error", "fail"), "conditions": raw.get("conditions")}
    for key, allowed, code, message in (
            ("combinator", COMBINATORS, "combinator_invalid", "combinator must be all or any."),
            ("parse_json", PARSE_MODES, "parse_json_invalid", "parse_json must be auto, always or never."),
            ("on_error", ERROR_POLICIES, "on_error_invalid", "on_error must be fail or no_match.")):
        if settings[key] not in allowed:
            yield _error(code, message, field=key)
    conditions = settings["conditions"]
    if not isinstance(conditions, list):
        yield _error("conditions_type", "conditions must be a list of condition objects.", field="conditions")
    elif not conditions:
        yield _error("conditions_empty", "Add at least one condition.", field="conditions")
    elif len(conditions) > MAX_CONDITIONS:
        yield _error("conditions_too_many", "Use at most {max} conditions.", {"max": MAX_CONDITIONS}, field="conditions")


def problems(raw):
    """Return every detectable configuration error: group settings first, then one per condition."""
    raw = thaw(raw)
    if not isinstance(raw, dict):
        return [_error("config_type", "The settings must be a JSON object.", field="config")]
    found = list(_settings(raw))
    conditions = raw.get("conditions")
    if isinstance(conditions, list) and len(conditions) <= MAX_CONDITIONS:
        for index, item in enumerate(conditions, start=1):
            try:
                condition(item, index)
            except ConditionError as exc:
                found.append(exc)
    return found


def configuration(raw):
    """Validate settings and return a :class:`Group`; raise the first ConditionError otherwise.

    Unknown top-level keys (framework-owned execution or composite metadata) are ignored;
    unknown keys inside a condition are rejected because they would silently change semantics.
    """
    found = problems(raw)
    if found:
        raise found[0]
    raw = thaw(raw)
    return Group(raw.get("combinator", "all"),
                 [condition(item, index) for index, item in enumerate(raw["conditions"], start=1)],
                 raw.get("parse_json", "auto"), raw.get("on_error", "fail"))


# --------------------------------------------------------------------------- evaluation


def message_value(raw, mode):
    """Turn the received message into the value conditions read, according to parse_json."""
    if mode == "never":
        if isinstance(raw, str):
            return raw
        try:
            return compact(raw)
        except (TypeError, ValueError, RecursionError):
            raise _error("message_not_text", "the message is not text or JSON.") from None
    if not isinstance(raw, str):
        return raw
    parsed, value = strict_json(raw)
    if parsed:
        return value
    if mode == "always":
        raise _error("message_not_json", "the message is not valid JSON and parse_json is always.")
    return raw


def _number(value, code, message):
    number = to_number(value)
    if number is None:
        raise _error(code, message)
    return number


def _typed(value, value_type):
    """Coerce one message-side value for number/boolean/datetime comparisons."""
    if value_type == "number":
        return _number(value, "not_number", "the value is not a finite number.")
    if value_type == "boolean":
        result = to_boolean(value)
        if result is None:
            raise _error("not_boolean", "the value is not true/false, yes/no or 1/0.")
        return result
    result = to_instant(value)
    if result is None:
        raise _error("not_datetime", "the value is not an ISO 8601 date or date-time.")
    return result


def _equal(actual, expected, item):
    if item.value_type == "auto":
        return auto_equal(actual, expected, item.case_sensitive)
    if item.value_type == "string":
        return text_equal(text_form(actual), text_form(expected), item.case_sensitive)
    left = _typed(actual, item.value_type)
    return left == _typed(expected, item.value_type)


def _contains(actual, item):
    needle = text_form(item.value)
    if item.value_type == "auto" and isinstance(actual, list):
        return any(auto_equal(member, item.value, item.case_sensitive) for member in actual)
    if item.value_type == "auto" and isinstance(actual, dict):
        return any(text_equal(key, needle, item.case_sensitive) for key in actual)
    return _fold(needle, item.case_sensitive) in _fold(text_form(actual), item.case_sensitive)


def _order(actual, item):
    if item.value_type == "datetime":
        return _typed(actual, "datetime"), to_instant(item.value)
    if item.value_type == "number":
        return _typed(actual, "number"), to_number(item.value)
    left = _number(actual, "not_numeric_auto", "the value is not numeric; choose value_type datetime to compare dates.")
    return left, to_number(item.value)


def _positive(operator, actual, item):
    if operator == "equals":
        return _equal(actual, item.value, item)
    if operator == "in_list":
        if item.value_type in {"number", "boolean", "datetime"}:
            left = _typed(actual, item.value_type)
            return any(left == _typed(member, item.value_type) for member in item.value)
        return any(_equal(actual, member, item) for member in item.value)
    if operator == "contains":
        return _contains(actual, item)
    if operator in {"starts_with", "ends_with"}:
        subject = _fold(text_form(actual), item.case_sensitive)
        needle = _fold(text_form(item.value), item.case_sensitive)
        return subject.startswith(needle) if operator == "starts_with" else subject.endswith(needle)
    if operator == "matches_regex":
        subject = text_form(actual)
        if len(subject) > MAX_SUBJECT:
            raise _error("subject_too_long", "the text is longer than {max} characters.", {"max": MAX_SUBJECT})
        return item.pattern.search(subject) is not None
    left, right = _order(actual, item)
    return {"greater_than": left > right, "greater_or_equal": left >= right,
            "less_than": left < right, "less_or_equal": left <= right}[operator]


def check(item, message):
    """Evaluate one validated condition against a message value: True, False or ConditionError."""
    actual = resolve(message, item.steps)
    operator = item.operator
    if operator in {"exists", "not_exists"}:
        return (actual is not MISSING) == (operator == "exists")
    if operator in {"is_empty", "is_not_empty"}:
        empty = actual is MISSING or actual is None or (isinstance(actual, (str, list, dict)) and len(actual) == 0)
        return empty == (operator == "is_empty")
    if operator in {"is_true", "is_false"}:
        if actual is MISSING:
            return False
        flag = to_boolean(actual)
        if flag is None:
            raise _error("not_boolean", "the value is not true/false, yes/no or 1/0.")
        return flag == (operator == "is_true")
    base = NEGATED.get(operator, operator)
    if actual is MISSING:
        return operator in NEGATED
    try:
        result = _positive(base, actual, item)
    except RecursionError:
        raise _error("too_deep", "the value is too deeply nested to compare.") from None
    return not result if operator in NEGATED else result


def short_label(item):
    """Compact human form, e.g. ``status equals "paid"``, used by cards, logs and previews."""
    data = item.to_dict() if isinstance(item, Condition) else item
    path = data.get("path") or "$"
    operator = str(data.get("operator") or "?")
    if operator in VALUELESS:
        return f"{path} {operator}"
    try:
        value = compact(data.get("value"))
    except (TypeError, ValueError, RecursionError):
        value = "?"
    if len(value) > 48:
        value = value[:47] + "…"
    suffix = "" if data.get("value_type", "auto") == "auto" else f" ({data.get('value_type')})"
    return f"{path} {operator} {value}{suffix}"


def evaluate(group, raw):
    """Evaluate every condition of a validated group on one raw message.

    Every condition is evaluated, so the order of conditions never changes the result.
    Returns a dict with ``matched`` (bool or None when the activation must fail),
    per-condition ``outcomes``, the ``failure`` that stops a ``fail`` policy and the
    ``warnings`` of conditions counted as false under ``no_match``.
    """
    outcomes, errors = [], []
    try:
        message = message_value(raw, group.parse_json)
        message_error = None
    except ConditionError as exc:
        message, message_error = None, exc
    for item in group.conditions:
        try:
            if message_error is not None:
                raise ConditionError(message_error.code, message_error.template, message_error.params)
            outcomes.append({"index": item.index, "outcome": "true" if check(item, message) else "false"})
        except ConditionError as exc:
            exc.index = item.index
            exc.field = "message"
            errors.append(exc)
            outcomes.append({"index": item.index, "outcome": "error", **_public(exc)})
    for outcome, item in zip(outcomes, group.conditions):
        outcome["label"] = short_label(item)
    if errors and group.on_error == "fail":
        return {"matched": None, "outcomes": outcomes, "failure": _public(errors[0]), "warnings": []}
    truths = [outcome["outcome"] == "true" for outcome in outcomes]
    matched = all(truths) if group.combinator == "all" else any(truths)
    return {"matched": matched, "outcomes": outcomes, "failure": None, "warnings": [_public(exc) for exc in errors]}


def _public(error):
    return {"index": error.index, "code": error.code, "params": error.params, "message": error.message}


# --------------------------------------------------------------------------- editor text


def value_text(value):
    """Editor text for a configured value: plain text unless it would read back as other JSON."""
    if isinstance(value, str) and not strict_json(value)[0]:
        return value
    try:
        return compact(value)
    except (TypeError, ValueError, RecursionError):
        return ""


def parse_value_text(text):
    """Inverse of :func:`value_text`: standard JSON when it parses, otherwise the text itself."""
    if not isinstance(text, str):
        raise _error("value_text_type", "The value must be text in the editor.", field="value")
    parsed, value = strict_json(text)
    return value if parsed else text
