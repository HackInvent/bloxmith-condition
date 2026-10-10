"""Condition language, routing decisions, settings validation and editor contracts (no server)."""

from pathlib import Path
from types import MappingProxyType, SimpleNamespace
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from bloxsmith_app.block_api import BlockRuntimeContext, BlockRuntimePreparation
from blocs.condition import conditions, logic
from blocs.condition.block import ConditionBlock

PACKAGE = Path(__file__).resolve().parents[1]
EN = json.loads((PACKAGE / "locales/en.json").read_text(encoding="utf-8"))
FR = json.loads((PACKAGE / "locales/fr.json").read_text(encoding="utf-8"))


def cond(path, operator, value=None, value_type="auto", case_sensitive=True):
    item = {"path": path, "operator": operator, "value_type": value_type, "case_sensitive": case_sensitive}
    if operator not in conditions.VALUELESS:
        item["value"] = value
    return item


def run(message, items, combinator="all", on_error="fail", parse_json="auto"):
    group = conditions.configuration({"combinator": combinator, "conditions": items,
                                      "on_error": on_error, "parse_json": parse_json})
    return conditions.evaluate(group, message)


def matched(message, *items, **options):
    result = run(message, list(items), **options)
    assert result["failure"] is None, result
    return result["matched"]


def failure(message, *items, **options):
    result = run(message, list(items), **options)
    assert result["matched"] is None and result["failure"], result
    return result["failure"]["code"]


def config_error(raw):
    try:
        conditions.configuration(raw)
    except conditions.ConditionError as exc:
        assert EN["block.condition.err_" + exc.code] == exc.template, exc.code
        return exc
    raise AssertionError(f"Accepted invalid settings: {raw}")


def canonical_vectors():
    """# - FB1 - FB2 - FB4 - the fourteen shared vectors, identical in If, Switch and Filter."""
    assert matched('{"a":5}', cond("a", "greater_than", 3, "number")) is True
    assert matched('{"a":"5"}', cond("a", "greater_than", 3)) is True
    assert failure('{"a":"abc"}', cond("a", "greater_than", 3, "number")) == "not_number"
    no_match = run('{"a":"abc"}', [cond("a", "greater_than", 3, "number")], on_error="no_match")
    assert no_match["matched"] is False and no_match["warnings"][0]["code"] == "not_number"
    assert matched('{"name":"Alice"}', cond("name", "equals", "alice", case_sensitive=False)) is True
    assert matched('{"tags":["x","y"]}', cond("tags", "contains", "y")) is True
    assert matched('{"tags":[]}', cond("tags", "is_empty")) is True
    assert matched("{}", cond("missing", "exists")) is False
    assert matched("{}", cond("missing", "not_exists")) is True
    assert matched("{}", cond("missing", "is_empty")) is True
    assert matched("hello world", cond("", "contains", "world")) is True
    assert matched('{"d":"2026-01-02T00:00:00Z"}', cond("d", "greater_than", "2026-01-01T12:00:00+02:00", "datetime")) is True
    assert matched('{"items":[{"p":1},{"p":9}]}', cond("items[1].p", "greater_or_equal", 9)) is True
    assert matched('{"s":"order-123"}', cond("s", "matches_regex", r"^order-\d+$")) is True
    assert matched('{"flag":"yes"}', cond("flag", "is_true", value_type="boolean")) is True
    assert matched('{"c":"FR"}', cond("c", "in_list", ["FR", "BE"])) is True
    pair = [cond("x", "greater_than", 10), cond("y", "equals", "ok")]
    assert matched('{"x":1,"y":"ok"}', *pair, combinator="any") is True
    assert matched('{"x":1,"y":"ok"}', *pair, combinator="all") is False


def operators_and_coercion():
    """# - FB2 - operators, value types, coercion, missing fields and complements."""
    # auto: JSON types as received, number against numeric text compares numerically.
    assert matched('{"n":2}', cond("n", "equals", "2.0")) and matched('{"n":"2.0"}', cond("n", "equals", 2))
    assert not matched('{"n":"2.0"}', cond("n", "equals", "2")), "two texts compare as text"
    assert not matched('{"b":true}', cond("b", "equals", 1)) and matched('{"b":true}', cond("b", "equals", "true"))
    assert matched('{"v":null}', cond("v", "equals", None)) and matched('{"v":null}', cond("v", "exists"))
    assert matched('{"o":{"a":1,"b":[1,2]}}', cond("o", "equals", {"b": [1.0, 2], "a": 1}))
    assert not matched('{"o":[true]}', cond("o", "equals", [1]))
    assert matched('{"s":"STRASSE"}', cond("s", "equals", "straße", case_sensitive=False))
    assert not matched('{"s":"Paid"}', cond("s", "equals", "paid"))
    assert matched('{"id":12345678901234567890}', cond("id", "equals", "12345678901234567890"))
    assert not matched('{"id":12345678901234567890}', cond("id", "equals", 12345678901234567891))
    # string, number, boolean and datetime convert both sides.
    assert matched('{"n":5}', cond("n", "equals", "5", "string"))
    assert matched('{"o":{"a":1}}', cond("o", "equals", '{"a":1}', "string"))
    assert matched('{"n":" 1e3 "}', cond("n", "equals", 1000, "number"))
    assert failure('{"n":true}', cond("n", "equals", 1, "number")) == "not_number"
    assert failure('{"n":"1e999"}', cond("n", "equals", 1, "number")) == "not_number"
    assert matched('{"b":"YES"}', cond("b", "equals", True, "boolean"))
    assert matched('{"b":0}', cond("b", "equals", "false", "boolean"))
    assert failure('{"b":"maybe"}', cond("b", "equals", True, "boolean")) == "not_boolean"
    assert matched('{"d":"2026-01-01T10:00:00Z"}', cond("d", "equals", "2026-01-01T12:00:00+02:00", "datetime"))
    assert matched('{"d":"2026-01-01"}', cond("d", "equals", "2026-01-01T00:00:00", "datetime"))
    assert failure('{"d":20260101}', cond("d", "equals", "2026-01-01", "datetime")) == "not_datetime"
    # contains: substring, array member, object key; not_contains is the exact complement.
    assert matched('{"t":"Hello World"}', cond("t", "contains", "world", case_sensitive=False))
    assert matched('{"a":[1,2,3]}', cond("a", "contains", "2")) and matched('{"a":["X"]}', cond("a", "contains", "x", case_sensitive=False))
    assert matched('{"o":{"Key":1}}', cond("o", "contains", "key", case_sensitive=False)) and not matched('{"o":{"Key":1}}', cond("o", "contains", "key"))
    assert matched('{"n":12345}', cond("n", "contains", 234))
    assert matched('{"a":[1]}', cond("a", "not_contains", 2)) and not matched('{"a":[1]}', cond("a", "not_contains", 1))
    assert matched('{"a":["x,y"]}', cond("a", "contains", '"x,y"', "string")), "string compares the compact JSON text"
    assert not matched("{}", cond("m", "contains", "x")) and matched("{}", cond("m", "not_contains", "x"))
    assert matched("{}", cond("m", "not_equals", "x")) and matched("{}", cond("m", "not_in_list", ["x"]))
    assert matched('{"e":"a@EXAMPLE.com"}', cond("e", "ends_with", "@example.com", case_sensitive=False))
    assert matched('{"n":4200}', cond("n", "starts_with", 42)) and not matched('{"s":"ab"}', cond("s", "starts_with", "b"))
    # ordering: numbers or datetimes only.
    assert matched('{"n":"10"}', cond("n", "greater_than", "9")), "numeric text is ordered numerically"
    assert matched('{"n":" 7 "}', cond("n", "less_or_equal", 7, "number")) and matched('{"n":7}', cond("n", "less_than", 7.5))
    assert failure('{"n":"abc"}', cond("n", "greater_than", 3)) == "not_numeric_auto"
    assert failure('{"n":true}', cond("n", "greater_than", 0)) == "not_numeric_auto"
    assert matched('{"d":"2026-01-01"}', cond("d", "less_than", "2025-12-31T23:59:59-01:00", "datetime")), "instants, not text"
    assert not matched("{}", cond("n", "greater_than", 1)), "missing never orders"
    # matches_regex: re.search, case option, bounded subject.
    assert matched('{"s":"ID-7"}', cond("s", "matches_regex", "id-[0-9]", case_sensitive=False))
    assert not matched('{"s":"ID-7"}', cond("s", "matches_regex", "id-[0-9]"))
    assert matched('{"n":2026}', cond("n", "matches_regex", r"^\d{4}$"))
    assert matched(json.dumps({"s": "a" * 10_000}), cond("s", "matches_regex", "a$"))
    assert failure(json.dumps({"s": "a" * 10_001}), cond("s", "matches_regex", "a$")) == "subject_too_long"
    # in_list: same equality as equals for each item.
    assert matched('{"n":"2"}', cond("n", "in_list", [1, 2])) and matched('{"n":"2.0"}', cond("n", "in_list", ["1", 2], "number"))
    assert not matched('{"c":"fr"}', cond("c", "in_list", ["FR"])) and matched('{"c":"fr"}', cond("c", "in_list", ["FR"], case_sensitive=False))
    assert failure('{"n":"x"}', cond("n", "in_list", [1], "number")) == "not_number"
    # booleans and emptiness.
    for value, flag in (('"TRUE"', True), ('"no"', False), ("1", True), ("0.0", False), ("true", True)):
        assert matched('{"f":%s}' % value, cond("f", "is_true")) is flag
        assert matched('{"f":%s}' % value, cond("f", "is_false")) is (not flag)
    assert failure('{"f":"maybe"}', cond("f", "is_true")) == "not_boolean"
    assert failure('{"f":null}', cond("f", "is_false")) == "not_boolean"
    assert not matched("{}", cond("f", "is_true")) and not matched("{}", cond("f", "is_false"))
    for value, empty in (("null", True), ('""', True), ("[]", True), ("{}", True), ("0", False), ("false", False), ('" "', False)):
        assert matched('{"v":%s}' % value, cond("v", "is_empty")) is empty
        assert matched('{"v":%s}' % value, cond("v", "is_not_empty")) is (not empty)
    # paths: exact keys, indices, leading index, wrong container types are missing.
    assert matched('[{"name":"a"}]', cond("[0].name", "equals", "a"))
    assert matched('{"a":{"b":[[0,{"c":1}]]}}', cond("a.b[0][1].c", "equals", 1))
    assert not matched('{"a":[1]}', cond("a.0", "exists")) and not matched('{"a":{"0":1}}', cond("a[0]", "exists"))
    assert matched('{"first name":"x"}', cond("first name", "equals", "x"))
    assert not matched('{"Status":"paid"}', cond("status", "exists"))
    # parse_json: auto, always and never.
    assert matched("hello", cond("", "equals", "hello")) and matched("NaN", cond("", "equals", "NaN"))
    assert matched("1.50", cond("", "matches_regex", r"^1\.5$")), "auto parses numeric text"
    assert matched("1.50", cond("", "matches_regex", r"^1\.50$"), parse_json="never")
    assert not matched('{"a":1}', cond("a", "exists"), parse_json="never")
    assert failure("not json", cond("", "exists"), parse_json="always") == "message_not_json"
    soft = run("not json", [cond("", "exists"), cond("", "not_exists")], combinator="any", on_error="no_match", parse_json="always")
    assert soft["matched"] is False and len(soft["warnings"]) == 2
    assert matched({"a": [1, 2]}, cond("a", "contains", 2)), "native structured values are used as received"
    deep = current = []
    for _ in range(100_000):
        current.append([])
        current = current[0]
    assert failure(deep, cond("", "equals", "x")) == "too_deep", "deep values fail explicitly, never crash"
    assert matched("[" * 5000 + "]" * 5000, cond("", "starts_with", "[[[")), "unparsable deep JSON text stays text"


def evaluation_order():
    """# - FB1 - every condition is evaluated; order never changes the result."""
    items = [cond("a", "greater_than", 1, "number"), cond("b", "equals", "ok")]
    for ordered in (items, items[::-1]):
        assert failure('{"a":"x","b":"ok"}', *ordered, combinator="any") == "not_number"
    result = run('{"a":"x","b":"ok"}', items, combinator="any", on_error="no_match")
    assert result["matched"] is True and [o["outcome"] for o in result["outcomes"]] == ["error", "true"]
    assert result["outcomes"][0]["label"] == "a greater_than 1 (number)" and result["outcomes"][1]["label"] == 'b equals "ok"'


def settings_validation():
    """# - FB3 - invalid settings are refused with stable codes, at save and at prepare."""
    base = {"combinator": "all", "parse_json": "auto", "on_error": "fail"}
    one = [cond("a", "exists")]
    cases = [
        ("conditions_empty", {**base, "conditions": []}, None),
        ("conditions_too_many", {**base, "conditions": one * 33}, None),
        ("conditions_type", {**base, "conditions": {"a": 1}}, None),
        ("combinator_invalid", {**base, "combinator": "none", "conditions": one}, None),
        ("parse_json_invalid", {**base, "parse_json": "yes", "conditions": one}, None),
        ("on_error_invalid", {**base, "on_error": "ignore", "conditions": one}, None),
        ("condition_type", {**base, "conditions": ["a equals 1"]}, 1),
        ("condition_unknown_key", {**base, "conditions": [*one, {**cond("a", "exists"), "case_sensitve": False}]}, 2),
        ("operator_invalid", {**base, "conditions": [cond("a", "like", "x")]}, 1),
        ("path_invalid", {**base, "conditions": [cond("a..b", "exists")]}, 1),
        ("path_spaces", {**base, "conditions": [cond("a. b", "exists")]}, 1),
        ("path_too_deep", {**base, "conditions": [cond(".".join(["k"] * 33), "exists")]}, 1),
        ("path_too_long", {**base, "conditions": [cond("k" * 513, "exists")]}, 1),
        ("path_type", {**base, "conditions": [{"path": 3, "operator": "exists"}]}, 1),
        ("value_type_invalid", {**base, "conditions": [cond("a", "equals", 1, "integer")]}, 1),
        ("type_unsupported", {**base, "conditions": [cond("a", "greater_than", 1, "string")]}, 1),
        ("type_unsupported", {**base, "conditions": [cond("a", "contains", "x", "number")]}, 1),
        ("case_sensitive_type", {**base, "conditions": [cond("a", "equals", "x", case_sensitive="no")]}, 1),
        ("value_missing", {**base, "conditions": [{"path": "a", "operator": "equals"}]}, 1),
        ("list_type", {**base, "conditions": [cond("a", "in_list", "FR, BE")]}, 1),
        ("list_too_long", {**base, "conditions": [cond("a", "in_list", list(range(257)))]}, 1),
        ("pattern_type", {**base, "conditions": [cond("a", "matches_regex", 123)]}, 1),
        ("pattern_too_long", {**base, "conditions": [cond("a", "matches_regex", "a" * 257)]}, 1),
        ("pattern_invalid", {**base, "conditions": [cond("a", "matches_regex", "(")]}, 1),
        ("value_empty", {**base, "conditions": [cond("a", "contains", "")]}, 1),
        ("value_not_numeric_auto", {**base, "conditions": [cond("a", "greater_than", "2026-01-01")]}, 1),
        ("value_not_number", {**base, "conditions": [cond("a", "equals", "abc", "number")]}, 1),
        ("value_not_boolean", {**base, "conditions": [cond("a", "in_list", [True, "maybe"], "boolean")]}, 1),
        ("value_not_datetime", {**base, "conditions": [cond("a", "less_than", "soon", "datetime")]}, 1),
        ("value_not_json", {**base, "conditions": [cond("a", "equals", float("nan"))]}, 1),
    ]
    for code, raw, index in cases:
        error = config_error(raw)
        assert (error.code, error.index) == (code, index), (code, error.code, error.index, error.message)
    assert conditions.configuration({**base, "conditions": [cond("a", "less_than", "1e2"), cond("b", "matches_regex", "^[a-z]+$")]})
    many = conditions.problems({"conditions": [cond("a", "like"), cond("ok", "exists"), cond("b..", "exists")]})
    assert [(item.index, item.code) for item in many] == [(1, "operator_invalid"), (3, "path_invalid")]
    group = conditions.configuration({"conditions": [cond("a", "exists")], "execution": {"inhibited": False},
                                      "runtime_path": [{"id": "x"}], "future_framework_key": 1})
    assert group.to_config() == {"combinator": "all", "parse_json": "auto", "on_error": "fail",
                                 "conditions": [{"path": "a", "operator": "exists", "value": None,
                                                 "value_type": "auto", "case_sensitive": True}]}
    frozen = MappingProxyType({"conditions": (MappingProxyType(cond("c", "in_list", ("FR", "BE"))),)})
    assert conditions.configuration(frozen).conditions[0].value == ["FR", "BE"], "prepare snapshots are thawed"
    block = ConditionBlock()
    assert isinstance(block.prepare_runtime(SimpleNamespace(config=frozen)), BlockRuntimePreparation)
    try:
        block.prepare_runtime(SimpleNamespace(config=MappingProxyType({"conditions": ()})))
    except ValueError as exc:
        assert str(exc) == "Invalid If settings: Add at least one condition."
    else:
        raise AssertionError("prepare accepted an empty group")
    try:
        block.prepare_runtime(SimpleNamespace(config={"conditions": [cond("a", "exists"), cond("b", "matches_regex", "[")]}))
    except ValueError as exc:
        assert str(exc).startswith("Invalid If settings: Condition 2: The pattern is not a valid regular expression")
    else:
        raise AssertionError("prepare accepted an invalid regex")
    assert block.default_config() == logic.DEFAULTS and conditions.configuration(block.default_config())


def context(value, config=None, content_type="text/plain", services=None, events=()):
    ports = (SimpleNamespace(id=1, name="true"), SimpleNamespace(id=2, name="false"))
    inputs = {} if value is None else {"in": value}
    return BlockRuntimeContext(run_id="unit", node_id="if", kind="condition", title="If",
                               config={**ConditionBlock().default_config(), **(config or {})},
                               inputs=inputs, input_content_types={"in": content_type},
                               input_ports=(SimpleNamespace(id=1, name="in", required=True,
                                                            execution_requirement="required_for_execution"),),
                               output_ports=ports, root_dir=ROOT, services=services or {}, input_events=events)


def routing():
    """# - FB1 - FB4 - FB5 - one branch per message, unchanged payload and content type, explicit failures."""
    block = ConditionBlock()
    text = '{ "status" : "paid",\n  "note": "café ☕", "secret": "private-value" }'
    for content_type in ("application/json", "text/plain", "application/vnd.example+json"):
        result = block.execute_runtime(context(text, content_type=content_type))
        assert result.status == "success" and result.worker_received == "true"
        emitted = [output for output in result.outputs if output.emitted]
        assert [(o.port_name, o.port_id) for o in emitted] == [("true", 1)]
        assert emitted[0].value == text and emitted[0].content_type == content_type, "payload must be unchanged"
        silent = [output for output in result.outputs if not output.emitted]
        assert [(o.port_name, o.value) for o in silent] == [("false", "")]
        assert "private-value" not in json.dumps(result.metadata) + result.last_message + "".join(result.logs)
        assert result.metadata["condition"] == {"branch": "true", "matched": [1], "errors": [], "conditions": 1}
    # One Shot rewrites the attribute content type to text/plain; the delivering event keeps the source one.
    event = SimpleNamespace(edge_id="e", input_port_id=1, input_port_name="in", source_node_id="src",
                            source_port_id=1, value=text, content_type="application/json", sequence=1)
    typed = block.execute_runtime(context(text, content_type="text/plain", events=(event,)))
    assert typed.outputs[0].emitted and typed.outputs[0].content_type == "application/json" and typed.content_type == "application/json"
    pending = block.execute_runtime(context('{"status":"pending"}'))
    assert [(o.port_name, o.emitted) for o in pending.outputs] == [("true", False), ("false", True)]
    assert pending.outputs[1].value == '{"status":"pending"}' and pending.logs[-1].startswith("[condition] Routed to false")
    native = block.execute_runtime(context({"status": "paid", "n": [1, 2]}))
    assert native.outputs[0].value == '{"status":"paid","n":[1,2]}' and native.outputs[0].emitted
    strict = {"conditions": [cond("amount", "greater_than", 10, "number")]}
    failed = block.execute_runtime(context('{"amount":"secret-amount"}', strict))
    assert failed.status == "failed" and failed.outputs == [] and failed.exit_code == 1
    assert failed.error == "Condition 1 (amount greater_than) could not be evaluated: the value is not a finite number."
    assert failed.logs == ["[condition-error] Condition 1 (amount greater_than): the value is not a finite number. Nothing was published."]
    assert "secret-amount" not in failed.error + "".join(failed.logs)
    soft = block.execute_runtime(context('{"amount":"secret-amount"}', {**strict, "on_error": "no_match"}))
    assert soft.status == "success" and [o.port_name for o in soft.outputs if o.emitted] == ["false"]
    assert soft.logs[0] == ("[condition-warning] Condition 1 (amount greater_than): the value is not a finite number. "
                            "Counted as false (on_error no_match).") and "secret-amount" not in "".join(soft.logs)
    invalid = block.execute_runtime(context('{"a":1}', {"conditions": []}))
    assert invalid.status == "failed" and invalid.error == "Invalid If settings: Add at least one condition." and not invalid.outputs
    skipped = block.execute_runtime(context(None))
    assert skipped.status == "skipped" and not skipped.outputs
    assert block.execute_runtime(context("   ")).status == "skipped", "a blank message is not routed"
    cancelled = block.execute_runtime(context('{"status":"paid"}', services={"cancel_requested": lambda: True}))
    assert cancelled.status == "skipped" and not any(output.emitted for output in cancelled.outputs)


def editor_contract():
    """# - FB3 - FB7 - editor text round trip, Apply canonicalization, live validation and preview."""
    for value in ("paid", "3", "", " x", '"q"', "true", "null", "[1]", 3, 2.5, True, None, ["FR", "BE"],
                  {"a": [1, {"b": None}]}, r"^order-\d+$", "NaN", "café", 12345678901234567890):
        assert conditions.parse_value_text(conditions.value_text(value)) == value, value
    assert conditions.value_text("3") == '"3"' and conditions.value_text("paid") == "paid"
    block = ConditionBlock()
    node = block.build_node_payload(node_id="if-1")
    node["config"]["execution"] = {"inhibited": False}
    rows = [{"path": "amount", "operator": "greater_than", "value_text": "100", "value_type": "number", "case_sensitive": True},
            {"path": "country", "operator": "in_list", "value_text": '["FR","BE"]', "value_type": "auto", "case_sensitive": False},
            {"path": "code", "operator": "equals", "value_text": '"007"', "value_type": "auto", "case_sensitive": True},
            {"path": "email", "operator": "exists", "value_text": "ignored", "value_type": "auto", "case_sensitive": True}]
    saved = block.handle_ui_action(node=node, action="save_settings", values={"node_patch": {
        "title": "Large orders", "config": {"combinator": "any", "conditions": rows, "parse_json": "always", "on_error": "no_match"}}})
    assert saved["node_patch"]["title"] == "Large orders"
    operation = saved["graph_operations"][0]
    assert operation["op"] == "update_node_config" and operation["replace"] is True and operation["node_id"] == "if-1"
    assert operation["config"]["execution"] == {"inhibited": False}
    assert [item["value"] for item in operation["config"]["conditions"]] == [100, ["FR", "BE"], "007", None]
    assert operation["config"]["combinator"] == "any" and operation["config"]["on_error"] == "no_match"
    refused = block.handle_ui_action(node=node, action="save_settings", values={"node_patch": {"config": {
        "conditions": [rows[0], {**rows[1], "value_text": "FR, BE"}]}}})
    assert refused == {"error": 'Invalid If settings: Condition 2: in_list needs a JSON array of values, for example ["FR","BE"].'}
    typed = block.handle_ui_action(node=node, action="save_settings", values={"node_patch": {"config": {
        "conditions": [rows[0], {**rows[1], "value_text": ["FR"]}]}}})
    assert typed == {"error": "Invalid If settings: Condition 2: The value must be text in the editor."}
    check = block.handle_ui_request(node=node, route="validate", method="POST", values={"config": {
        "conditions": [{**rows[0], "path": "a..b"}, rows[1], {**rows[2], "operator": "matches_regex", "value_text": "("}]}})
    assert not check["valid"] and [(e["index"], e["field"], e["code"]) for e in check["errors"]] == [
        (1, "path", "path_invalid"), (3, "value", "pattern_invalid")]
    assert block.handle_ui_request(node=node, route="validate", method="POST", values={"config": {"conditions": rows}}) == {
        "valid": True, "errors": []}
    preview = block.handle_ui_request(node=node, route="preview", method="POST", values={
        "config": {"combinator": "all", "conditions": rows[:2]}, "sample": '{"amount": 150, "country": "be"}'})
    assert preview["valid"] and preview["branch"] == "true" and [o["outcome"] for o in preview["outcomes"]] == ["true", "true"]
    failing = block.handle_ui_request(node=node, route="preview", method="POST", values={
        "config": {"conditions": rows[:1]}, "sample": '{"amount": "lots"}'})
    assert failing["branch"] is None and failing["failure"]["code"] == "not_number" and failing["failure"]["index"] == 1
    big = block.handle_ui_request(node=node, route="preview", method="POST", values={
        "config": {"conditions": rows[:1]}, "sample": "x" * (logic.MAX_SAMPLE_CHARS + 1)})
    assert big["sample_error"]["code"] == "sample_too_large"
    try:
        block.handle_ui_request(node=node, route="unknown", method="POST", values={})
    except NotImplementedError:
        pass
    else:
        raise AssertionError("unknown routes must be refused")


def surfaces_and_language():
    """# - FB7 - escaped surfaces, node card summary and a complete, consistent EN/FR catalog."""
    assert EN.keys() == FR.keys()
    for key, text in EN.items():
        assert key.startswith("block.condition.") and text and FR[key]
        assert set(re.findall(r"{(\w+)}", text)) == set(re.findall(r"{(\w+)}", FR[key])), key
    model = json.loads((PACKAGE / "model.json").read_text(encoding="utf-8"))
    assert EN["block.condition.model.title"] == model["title"] and EN["block.condition.model.description"] == model["description"]
    used = set()
    for path in [*PACKAGE.glob("*.py"), *PACKAGE.glob("*.html"), *PACKAGE.glob("assets/js/*.js")]:
        source = path.read_text(encoding="utf-8")
        used |= set(re.findall(r'"block\.condition\.([a-z_.]*[a-z_])"', source))
        used |= set(re.findall(r'_text\(block, "([a-z_]+)"', source))
        used |= set(re.findall(r'_attr\(block, "[a-z-]+", "([a-z_]+)"', source))
        used |= {"help_" + key for key in re.findall(r'_hint\(block, "([a-z_]+)"', source)}
        used |= set(re.findall(r'say\([a-zA-Z]+, "([a-z_]+)"', source))
    used |= {"outcome_true", "outcome_false", "card_more"}
    for key in used:
        assert f"block.condition.{key}" in EN or f"block.condition.{key}.other" in EN, key
    source = (PACKAGE / "conditions.py").read_text(encoding="utf-8") + (PACKAGE / "logic.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'(?:_error|ConditionError|_number)\([^"]*"([a-z_]+)", "', source)) | {"combinator_invalid",
            "parse_json_invalid", "on_error_invalid", "value_not_number", "value_not_boolean", "value_not_datetime",
            "sample_type", "sample_too_large"}
    assert len(codes) >= 40, sorted(codes)
    for code in codes:
        assert f"block.condition.err_{code}" in EN, code
    from blocs.condition import ui
    for key, text in ui.HELP.items():
        assert EN[f"block.condition.help_{key}"] == text, key
    block = ConditionBlock()
    node = block.build_node_payload(node_id="x<1>")
    node["title"] = "<b>{{ editor }}</b>"
    node["config"]["conditions"] = [cond("<script>", "equals", "</option>"), cond("b", "exists")]
    node["config"]["combinator"] = "any"
    for surface in (block.render_modal(node=node), block.render_inspector_panel(node=node)):
        html = surface["html"]
        assert "{{" not in html.replace("&lt;b&gt;{{ editor }}&lt;/b&gt;", "") and "<script>" not in html
        assert html.count("data-condition-editor") == 1 and "&lt;/option&gt;" in html and 'data-owned-apply' in html
        assert 'data-condition-row-template' in html and html.count("data-condition-row>") == 3
        assert 'data-properties-surface=' in html
    card = block.render_node_card(node=node)["html"]
    assert '&lt;script&gt; equals &quot;&lt;/option&gt;&quot;' in card and "and 1 more (any)" in card
    assert ConditionBlock().render_node_card(node=ConditionBlock().build_node_payload(node_id="d"))["html"].count('status equals &quot;paid&quot;') == 1
    broken = block.build_node_payload(node_id="b")
    broken["config"]["conditions"] = []
    assert "Invalid settings" in block.render_node_card(node=broken)["html"]


def readme_example():
    """# - FB1 - FB4 - the README example routes exactly as documented."""
    text = (PACKAGE / "README.md").read_text(encoding="utf-8")
    section = text.split("## Example", 1)[1]
    example = json.loads(section.split("```json", 1)[1].split("```", 1)[0])
    group = conditions.configuration(example)
    for message, expected, warnings in (('{"total": "620.00", "customer": {"tier": "Silver"}}', True, 0),
                                        ('{"total": 80, "customer": {"tier": "Gold"}}', True, 0),
                                        ('{"total": "n/a"}', False, 1)):
        result = conditions.evaluate(group, message)
        assert (result["matched"], len(result["warnings"])) == (expected, warnings), (message, result)
    assert 'status equals "paid"' in text and "and 2 more (any)" in text


def main():
    readme_example()
    canonical_vectors()
    operators_and_coercion()
    evaluation_order()
    settings_validation()
    routing()
    editor_contract()
    surfaces_and_language()
    print("[ok] If condition language, routing, settings and editor contracts")


if __name__ == "__main__":
    main()
