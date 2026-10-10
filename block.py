"""If: route each message to exactly one of two branches from explicit, declarative conditions."""

from bloxsmith_app.block_api import BlockDefinition, BlockRuntimeOutput, BlockRuntimePreparation, BlockRuntimeResult, TEXT_PLAIN
from . import conditions, logic, ui


# FB1 - Evaluate the configured all/any condition group on each message and route it to exactly one of true or false.
# FB2 - Apply the shared condition language: paths, operators, value types, coercion and missing-field rules.
# FB3 - Validate settings when they are applied (UI action) and at run preparation; invalid settings never execute.
# FB4 - Apply on_error: fail stops the activation without publishing; no_match counts the condition false with a warning.
# FB5 - Publish the received message unchanged with its content type; never execute code, fetch or mutate data.
# FB6 - Behave identically in centralized and zeromq_active runtimes and in bundled, managed and linked packages.
# FB7 - Own translated responsive surfaces: row editor, live validation, sample preview, draft and Apply.
class ConditionBlock(BlockDefinition):
    """Routing policy lives in the block configuration, never in incoming messages."""

    kind = "condition"

    def ui_assets(self, surface="modal"):
        """Use the manifest's asset list for bundled surfaces as well as hosted releases."""
        return list(self.model.get("ui_assets", {}).get(surface, []))

    def prepare_runtime(self, context):
        """Refuse invalid settings before any activation, without side effects."""
        try:
            logic.group(context.config)
        except conditions.ConditionError as exc:
            raise ValueError(f"Invalid If settings: {exc}") from None
        return BlockRuntimePreparation()

    def execute_runtime(self, context):
        """Route one message: the chosen branch carries it unchanged, the other branch is cleared."""
        if not context.has_input_value("in", "1"):
            return BlockRuntimeResult(status="skipped", outputs=[], logs=["[condition] No message to route."])
        raw = context.input_value("in", "1")
        content_type = self._content_type(context)
        try:
            result = logic.route(raw, context.config)
            payload = logic.output_text(raw)
        except conditions.ConditionError as exc:
            return BlockRuntimeResult(status="failed", outputs=[], error=self._settings_error(exc), exit_code=1,
                                      logs=[f"[condition-error] Invalid If settings: {exc} Nothing was published."])
        if context.services.get("cancel_requested", lambda: False)():
            return BlockRuntimeResult(status="skipped", outputs=self._outputs(context, None, "", content_type),
                                      logs=["[condition] Cancelled before routing; nothing was published."])
        settings = logic.settings(context.config)
        if result["branch"] is None:
            failure = result["failure"]
            detail = logic.describe_failure(failure, settings)
            reason = self.translate(f"block.condition.err_{failure['code']}", failure["params"], fallback=failure["message"])
            return self._failed(detail, "block.condition.eval_failed",
                                {"index": failure["index"], "where": logic.where(failure["index"], settings), "reason": reason},
                                "Condition {index} ({where}) could not be evaluated: {reason}")
        summary = logic.summary(result)
        logs = [f"[condition-warning] {logic.describe_failure(warning, settings)} Counted as false (on_error no_match)."
                for warning in result["warnings"]]
        logs.append(f"[condition] Routed to {result['branch']}: {len(summary['matched'])} of "
                    f"{summary['conditions']} condition(s) matched ({settings['combinator']}).")
        return BlockRuntimeResult(status="success", outputs=self._outputs(context, result["branch"], payload, content_type),
                                  content_type=content_type, last_message=logic.dumps(summary),
                                  worker_received=result["branch"], metadata={self.kind: summary}, logs=logs)

    @staticmethod
    def _content_type(context):
        """Source content type: the delivering event keeps it in both runtimes; the attribute is the fallback."""
        port_ids = {int(port.id) for port in context.input_ports if str(port.name) == "in"} or {1}
        events = [event for event in (context.input_events or ()) if int(event.input_port_id) in port_ids]
        if len(events) == 1 and str(events[0].content_type or "").strip():
            return str(events[0].content_type)
        return context.input_content_type("in", "1", default=TEXT_PLAIN)

    def _outputs(self, context, branch, payload, content_type):
        """Emit on the chosen port only; an explicit non-emission clears the other port's stale value."""
        return [BlockRuntimeOutput(port_id=int(port.id), port_name=str(port.name),
                                   value=payload if str(port.name) == branch else "",
                                   content_type=content_type, emitted=str(port.name) == branch)
                for port in context.output_ports if str(port.name) in {"true", "false"}]

    def _failed(self, detail, key, params, fallback):
        """Explicit failure: English trace, translated display text, nothing published."""
        message = self.translate(key, params, fallback=fallback)
        return BlockRuntimeResult(status="failed", outputs=[], error=message, exit_code=1,
                                  logs=[f"[condition-error] {detail} Nothing was published."])

    def handle_ui_action(self, *, node, action, values, payload=None):
        """Validate and canonicalize editor drafts before persisting them; refuse invalid settings."""
        if action in {"save_settings", "modal_update_fields", "inspector_update_fields"}:
            patch = dict((values or {}).get("node_patch") or {})
            if "config" in patch:
                try:
                    draft = logic.editor_settings(patch["config"] if isinstance(patch["config"], dict) else {})
                    group = logic.group({**(node.get("config") or {}), **draft})
                except conditions.ConditionError as exc:
                    return {"error": self._settings_error(exc)}
                patch["config"] = group.to_config()
                values = {**(values or {}), "node_patch": patch}
        result = super().handle_ui_action(node=node, action="modal_update_fields" if action == "save_settings" else action,
                                          values=values, payload=payload)
        return ui.replace_config(result, node)

    def handle_ui_request(self, *, node, route, method, values, payload=None):
        """Read-only draft checks: live validation and the sample preview call the same condition code."""
        draft = (values or {}).get("config")
        draft = draft if isinstance(draft, dict) else {}
        stored = node.get("config") if isinstance(node.get("config"), dict) else {}
        if route == "validate":
            errors = logic.validation(draft, stored)
            return {"valid": not errors, "errors": errors}
        if route == "preview":
            return logic.preview(draft, (values or {}).get("sample", ""), stored)
        return super().handle_ui_request(node=node, route=route, method=method, values=values, payload=payload)

    def _settings_error(self, error):
        """Translated, index-aware message for settings refused on Apply or found invalid at run time."""
        detail = self.translate(f"block.condition.err_{error.code}", error.params, fallback=error.message)
        if error.index:
            detail = self.translate("block.condition.invalid_condition", {"index": error.index, "reason": detail},
                                    fallback="Condition {index}: {reason}")
        return self.translate("block.condition.invalid_settings", {"detail": detail}, fallback="Invalid If settings: {detail}")

    def render_modal(self, *, node, payload=None):
        """Render the owned condition editor inside the opaque modal contract."""
        return ui.modal(self, node, payload)

    def render_inspector_panel(self, *, node, payload=None):
        """Keep the same editor usable in the narrow inspector, with the Ports tab."""
        return ui.inspector(self, node, payload)

    def render_node_card(self, *, node, payload=None):
        """Show the first condition in short form and how many follow."""
        return ui.card(self, node)
