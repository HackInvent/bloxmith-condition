"""FB1/FB3/FB4/FB5/FB6: real graph routes in both runtimes, all package origins, bursts and Stop."""

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from blocs.condition.block import ConditionBlock
from blocs.list.block import ListBlock
from block_test_packages import install_test_package, surface_payload
from ui_smoke_common import (create_run_api, data_edge, display_node, graph_payload, isolated_server, play_run_api,
                             prepare_run_api, stop_run_api, text_node, wait_for_run_predicate, wait_for_run_terminal)

BLOCK = ConditionBlock()
PAID = '{ "status": "paid", "id": 7,\n  "note": "café" }'
STRICT = {"conditions": [{"path": "amount", "operator": "greater_than", "value": 10,
                          "value_type": "number", "case_sensitive": True}]}


def if_node(node_id, y, version, config=None):
    node = BLOCK.build_node_payload(node_id=node_id, position={"x": 380, "y": y})
    node["config"] = {**BLOCK.default_config(), **(config or {})}
    if version:
        node["block_version"] = version
    return node


def chain(prefix, source, version, y, config=None):
    """source -> If -> yes/no displays, with stable ids derived from the prefix."""
    node = if_node(f"{prefix}-if", y, version, config)
    nodes = [source, node, display_node(f"{prefix}-yes", "Yes", 760, y - 50), display_node(f"{prefix}-no", "No", 760, y + 50)]
    edges = [data_edge(f"{prefix}-in", source["id"], 1, node["id"], 1),
             data_edge(f"{prefix}-t", node["id"], 1, f"{prefix}-yes", 1),
             data_edge(f"{prefix}-f", node["id"], 2, f"{prefix}-no", 1)]
    return nodes, edges


def document(title, *chains):
    nodes, edges = [], []
    for chain_nodes, chain_edges in chains:
        nodes += chain_nodes
        edges += chain_edges
    return graph_payload(title, nodes, edges)


def routed(run, node_id):
    """Branch values actually published by one If node."""
    outputs = run.get("output_values") or {}
    return {name: outputs[f"{node_id}:{port}"] for port, name in ((1, "true"), (2, "false"))
            if (outputs.get(f"{node_id}:{port}") or {}).get("value")}


def received(run, node_id):
    """Display preview of one node (single line: the worker row collapses whitespace)."""
    text = str(((run.get("worker_rows") or {}).get(node_id) or {}).get("received") or "")
    return "" if text == "-" else " ".join(text.split())


def flat(text):
    return " ".join(text.split())


def success_graph(mode, version):
    """# - FB1 - FB5 - FB6 - several independent routes in one run, payload and content type unchanged."""
    items = ListBlock().build_node_payload(node_id="list-src", position={"x": 80, "y": 420},
                                           config_overrides={"items": ["paid", "late"]})
    graph = document("If routes",
                     chain("paid", text_node("paid-src", "Paid", PAID, 80, 80), version, 80),
                     chain("pending", text_node("pending-src", "Pending", '{"status":"pending"}', 80, 250), version, 250),
                     chain("list", items, version, 420, {"conditions": [
                         {"path": "[0].item", "operator": "equals", "value": "paid", "value_type": "auto", "case_sensitive": True},
                         {"path": "[1].item", "operator": "in_list", "value": ["late", "lost"], "value_type": "string",
                          "case_sensitive": True}]}),
                     chain("soft", text_node("soft-src", "Soft", '{"amount":"lots"}', 80, 590), version, 590,
                           {**STRICT, "on_error": "no_match"}),
                     chain("raw", text_node("raw-src", "Raw", "hello world", 80, 760), version, 760,
                           {"parse_json": "never", "conditions": [{"path": "", "operator": "contains", "value": "WORLD",
                                                                  "value_type": "string", "case_sensitive": False}]}))
    return graph


def check_success(server, mode, version, origin):
    created = create_run_api(server, success_graph(mode, version), runtime_mode=mode)
    run = wait_for_run_terminal(server, created["run_id"], timeout_sec=60)
    assert run["status"] == "success", (mode, origin, run.get("logs"))
    paid = routed(run, "paid-if")
    assert list(paid) == ["true"] and paid["true"]["value"] == PAID, (mode, origin, paid)
    assert paid["true"]["content_type"] == "text/plain"
    assert flat(PAID) in received(run, "paid-yes") and not received(run, "paid-no")
    pending = routed(run, "pending-if")
    assert list(pending) == ["false"] and pending["false"]["value"] == '{"status":"pending"}'
    assert '"pending"' in received(run, "pending-no") and not received(run, "pending-yes")
    listed = routed(run, "list-if")
    source = run["output_values"]["list-src:1"]
    assert list(listed) == ["true"] and listed["true"]["value"] == source["value"], (listed, source)
    assert "\n" in source["value"] and listed["true"]["content_type"] == source["content_type"] == "application/json"
    soft = routed(run, "soft-if")
    assert list(soft) == ["false"] and soft["false"]["value"] == '{"amount":"lots"}'
    raw = routed(run, "raw-if")
    assert list(raw) == ["true"] and raw["true"]["value"] == "hello world"
    logs = "\n".join(run.get("logs") or [])
    assert "[condition-warning] Condition 1 (amount greater_than): the value is not a finite number." in logs, logs[-3000:]
    assert "Routed to true" in logs and "Routed to false" in logs


def check_failure(server, mode, version, origin):
    """# - FB4 - fail stops the activation: failed run, explicit English reason, nothing published."""
    graph = document("If fails", chain("fail", text_node("fail-src", "Fail", '{"amount":"lots-of-private-data"}', 80, 80),
                                       version, 80, STRICT))
    created = create_run_api(server, graph, runtime_mode=mode)
    run = wait_for_run_terminal(server, created["run_id"], timeout_sec=60)
    assert run["status"] == "failed", (mode, origin, run.get("logs"))
    assert not routed(run, "fail-if") and not received(run, "fail-yes") and not received(run, "fail-no")
    state = json.dumps(run, ensure_ascii=False)
    assert "Condition 1 (amount greater_than) could not be evaluated: the value is not a finite number." in state, state[-4000:]
    # The framework may echo the received input in its own worker preview; the block's own text never does.
    own = [line for line in run.get("logs") or [] if line.startswith("[condition")]
    error = str(((run.get("results") or {}).get("fail-if") or {}).get("error") or "")
    assert own and "lots-of-private-data" not in "".join(own) + error, own


def check_prepare(server, mode, version, origin):
    """# - FB3 - invalid settings are refused at preparation, before any activation."""
    graph = document("If invalid", chain("bad", text_node("bad-src", "Bad", '{"status":"paid"}', 80, 80), version, 80,
                                         {"conditions": [{"path": "a..b", "operator": "exists"}]}))
    created = create_run_api(server, graph, runtime_mode=mode)
    run = wait_for_run_terminal(server, created["run_id"], timeout_sec=60)
    assert run["status"] == "failed", (mode, origin, run.get("logs"))
    logs = "\n".join(run.get("logs") or [])
    assert "[prepare-error] bad-if" in logs and "Invalid If settings: Condition 1: path is not valid" in logs, logs[-3000:]
    assert not routed(run, "bad-if") and not received(run, "bad-yes")


def check_burst(server, version, origin):
    """# - FB1 - FB6 - Active Runtime routes every message of a burst individually (on_each_event)."""
    from blocs.event_or.block import EventOrBlock
    merge = EventOrBlock().build_node_payload(node_id="mix", position={"x": 260, "y": 120})
    node = if_node("burst-if", 120, version)
    graph = graph_payload("If burst", [
        text_node("a-src", "A", '{"status":"paid","n":1}', 40, 40), text_node("b-src", "B", '{"status":"late","n":2}', 40, 200),
        merge, node, display_node("burst-yes", "Yes", 760, 60), display_node("burst-no", "No", 760, 200)], [
        data_edge("a-mix", "a-src", 1, "mix", 1), data_edge("b-mix", "b-src", 1, "mix", 2),
        data_edge("mix-if", "mix", 1, "burst-if", 1),
        data_edge("burst-t", "burst-if", 1, "burst-yes", 1), data_edge("burst-f", "burst-if", 2, "burst-no", 1)])
    created = create_run_api(server, graph, runtime_mode="zeromq_active")
    run = wait_for_run_terminal(server, created["run_id"], timeout_sec=60)
    assert run["status"] == "success", (origin, run.get("logs"))
    assert '"n":1' in received(run, "burst-yes") and '"n":2' in received(run, "burst-no"), (
        received(run, "burst-yes"), received(run, "burst-no"))
    logs = "\n".join(run.get("logs") or [])
    assert logs.count("[condition] Routed to") >= 2, logs[-3000:]


def check_stop(server, version, origin):
    """# - FB6 - a loaded Active Runtime keeps routing new waves, then stops cleanly on Stop."""
    graph = document("If stop", chain("stop", text_node("stop-src", "Paid", '{"status":"paid"}', 80, 80), version, 80))
    prepared = prepare_run_api(server, graph)
    run_id = prepared["run_id"]
    play_run_api(server, run_id)
    wait_for_run_predicate(server, run_id, lambda state: '"paid"' in received(state, "stop-yes"),
                           "The If block did not route after Play.", timeout_sec=60)
    play_run_api(server, run_id)
    second = wait_for_run_predicate(server, run_id, lambda state: "\n".join(state.get("logs") or []).count(
        "[condition] Routed to true") >= 2, "A second wave was not routed.", timeout_sec=60)
    assert second["status"] == "running", second.get("status")
    stop_run_api(server, run_id)
    final = wait_for_run_terminal(server, run_id, timeout_sec=60)
    assert final["status"] == "cancelled", (origin, final.get("status"))
    assert "[condition-error]" not in "\n".join(final.get("logs") or [])
    assert not received(final, "stop-no")


def check_surfaces(server, model, version):
    """Release surfaces render through the package host and satisfy the locale contract."""
    node = if_node("surface-if", 80, version, {"combinator": "any", "conditions": [
        {"path": "status", "operator": "equals", "value": "paid", "value_type": "auto", "case_sensitive": True},
        {"path": "tags", "operator": "contains", "value": "vip", "value_type": "auto", "case_sensitive": False}]})
    for surface in ("modal", "inspector_panel", "node_card"):
        html = surface_payload(server, model, node, surface=surface)["html"]
        assert "{{" not in html and "__title__" not in html
        if surface == "node_card":
            assert 'status equals &quot;paid&quot;' in html and "and 1 more (any)" in html, html
        else:
            assert html.count("data-condition-row>") == 3 and "data-owned-apply" in html and "data-condition-test" in html


def main():
    for origin in (None, "managed", "linked"):
        with isolated_server() as server:
            version = None
            if origin:
                model = install_test_package(server, "condition", origin=origin)
                version = model["version"]
                check_surfaces(server, model, version)
            for mode in ("centralized", "zeromq_active"):
                check_success(server, mode, version, origin)
                check_failure(server, mode, version, origin)
                check_prepare(server, mode, version, origin)
            check_burst(server, version, origin)
            check_stop(server, version, origin)
        print(f"[ok] If runtime routes, failures, burst and Stop ({origin or 'bundled'})", flush=True)


if __name__ == "__main__":
    main()
