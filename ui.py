"""Package-owned editor surfaces, sharing only the framework's public rendering helpers."""

from html import escape
import json
import re
import secrets

from bloxsmith_app.block_api import render_inspector_template
from . import conditions, logic

ROW_TYPES = {operator: " ".join(conditions.ALLOWED_TYPES[operator]) for operator in conditions.OPERATORS}


def replace_config(result, node):
    """Replace edited settings exactly; generic graph patches otherwise deep-merge objects."""
    patch = result.get("node_patch") if isinstance(result, dict) else None
    if not isinstance(patch, dict) or not isinstance(patch.get("config"), dict):
        return result
    settings = {**(node.get("config") or {}), **patch.pop("config")}
    result.setdefault("graph_operations", []).append({"op": "update_node_config",
        "node_id": str(node.get("id") or ""), "config": settings, "replace": True})
    return result


def _text(block, key, fallback, tag="span", attrs=""):
    """Catalog-owned text with its marker; never used for user content."""
    name = f"block.{block.kind}.{key}"
    return f'<{tag}{attrs} data-i18n="{name}">{escape(block.translate(name, fallback=fallback))}</{tag}>'


def _attr(block, name, key, fallback):
    """Translated attribute plus its marker, e.g. aria-label."""
    full = f"block.{block.kind}.{key}"
    return f' {name}="{escape(block.translate(full, fallback=fallback), quote=True)}" data-i18n-{name}="{full}"'


def _options(values, selected, extra=None):
    html = []
    for value in values:
        data = f' {extra[value]}' if extra and value in extra else ""
        chosen = " selected" if value == selected else ""
        html.append(f'<option value="{escape(value, quote=True)}"{data}{chosen}>{escape(value)}</option>')
    return "".join(html)


def row_html(block, prefix, row, number):
    """One condition row; field labels are technical keys, help and actions are translated."""
    operator_data = {operator: f'data-types="{ROW_TYPES[operator]}"'
                     + (' data-valueless="true"' if operator in conditions.VALUELESS else "")
                     for operator in conditions.OPERATORS}
    move_up = _attr(block, "aria-label", "move_up", "Move this condition up") + _attr(block, "title", "move_up", "Move this condition up")
    move_down = _attr(block, "aria-label", "move_down", "Move this condition down") + _attr(block, "title", "move_down", "Move this condition down")
    checked = " checked" if row["case_sensitive"] else ""
    return (
        '<li class="cond-row" data-condition-row>'
        '<div class="cond-row-head">'
        f'<span class="cond-row-title">{_text(block, "condition_label", "Condition")} '
        f'<span data-condition-number>{number}</span></span>'
        '<span class="cond-row-actions">'
        f'<button type="button" class="ghost-btn cond-icon" data-condition-move="up" data-block-mutation-control{move_up}>'
        '<span aria-hidden="true">↑</span></button>'
        f'<button type="button" class="ghost-btn cond-icon" data-condition-move="down" data-block-mutation-control{move_down}>'
        '<span aria-hidden="true">↓</span></button>'
        '<button type="button" class="ghost-btn cond-remove" data-condition-remove data-block-mutation-control>'
        f'{_text(block, "remove", "Remove")}</button>'
        '</span></div>'
        '<div class="cond-fields">'
        '<label class="cond-field cond-field-path"><span class="cond-key">path</span>'
        f'<input type="text" data-condition-field="path" value="{escape(row["path"], quote=True)}" spellcheck="false" '
        f'autocomplete="off" placeholder="customer.email" aria-describedby="{prefix}-help-path"></label>'
        '<label class="cond-field cond-field-operator"><span class="cond-key">operator</span>'
        f'<select data-condition-field="operator">{_options(conditions.OPERATORS, row["operator"], operator_data)}</select></label>'
        '<label class="cond-field cond-field-value" data-condition-value-field><span class="cond-key">value</span>'
        f'<input type="text" data-condition-field="value_text" value="{escape(row["value_text"], quote=True)}" '
        f'spellcheck="false" autocomplete="off" aria-describedby="{prefix}-help-value"></label>'
        '<label class="cond-field cond-field-type" data-condition-type-field><span class="cond-key">value_type</span>'
        f'<select data-condition-field="value_type" aria-describedby="{prefix}-help-type">'
        f'{_options(conditions.VALUE_TYPES, row["value_type"])}</select></label>'
        '<label class="cond-check" data-condition-case-field>'
        f'<input type="checkbox" data-condition-field="case_sensitive"{checked}><span class="cond-key">case_sensitive</span></label>'
        '</div>'
        '<p class="field-hint cond-row-error" data-condition-row-error hidden></p>'
        '</li>'
    )


def _hint(block, key, element_id, tag="p"):
    """Translated help paragraph with a stable id for aria-describedby."""
    return _text(block, f"help_{key}", HELP[key], tag, f' id="{element_id}" class="field-hint"')


def editor_html(block, node, surface):
    """The complete condition editor shared by the modal and the inspector."""
    config = logic.settings(node.get("config") or {})
    prefix = escape(re.sub(r"[^A-Za-z0-9_-]", "-", f"{block.kind}-{node.get('id', '')}-{surface}"), quote=True)
    rows = logic.editor_rows(node.get("config") or {})
    empty = {"path": "", "operator": "equals", "value_text": "", "value_type": "auto", "case_sensitive": True}
    combinator = config.get("combinator") if config.get("combinator") in conditions.COMBINATORS else "all"
    radios = "".join(
        f'<label class="cond-segment-option"><input type="radio" name="{prefix}-combinator" value="{value}" '
        f'data-condition-setting="combinator"{" checked" if value == combinator else ""} '
        f'aria-describedby="{prefix}-help-combinator"><span>{value}</span></label>'
        for value in conditions.COMBINATORS)
    selects = []
    for key, values in (("parse_json", conditions.PARSE_MODES), ("on_error", conditions.ERROR_POLICIES)):
        chosen = config.get(key) if config.get(key) in values else values[0]
        selects.append(
            f'<div class="field-group"><label for="{prefix}-{key}">{key}</label>'
            f'<select id="{prefix}-{key}" data-condition-setting="{key}" aria-describedby="{prefix}-help-{key}">'
            f'{_options(values, chosen)}</select>{_hint(block, key, f"{prefix}-help-{key}")}</div>')
    row_items = "".join(row_html(block, prefix, row, number) for number, row in enumerate(rows, start=1))
    sample_attrs = (f'id="{prefix}-sample" data-condition-sample rows="4" spellcheck="false" '
                    f'placeholder="{escape(json.dumps({"status": "paid"}), quote=True)}" '
                    f'aria-describedby="{prefix}-help-sample"')
    return (
        f'<div class="cond-editor" data-condition-editor data-surface="{escape(surface, quote=True)}" '
        f'data-max="{conditions.MAX_CONDITIONS}">'
        '<fieldset class="cond-combinator"><legend class="cond-key">combinator</legend>'
        f'<div class="cond-segment">{radios}</div>{_hint(block, "combinator", f"{prefix}-help-combinator")}'
        '</fieldset>'
        f'<section class="cond-section" aria-labelledby="{prefix}-conditions">'
        f'<div class="cond-section-head"><h3 id="{prefix}-conditions" class="cond-key">conditions</h3>'
        f'<span class="field-hint cond-count" data-condition-count>{len(rows)} / {conditions.MAX_CONDITIONS}</span></div>'
        f'<ol class="cond-rows" data-condition-rows>{row_items}</ol>'
        f'<template data-condition-row-template>{row_html(block, prefix, empty, 1)}</template>'
        '<div class="cond-add-line"><button type="button" class="ghost-btn cond-add" data-condition-add '
        f'data-block-mutation-control>{_text(block, "add", "Add a condition")}</button></div>'
        '<p class="field-hint cond-group-error" data-condition-group-error role="status" aria-live="polite" hidden></p>'
        f'<div class="cond-help">{_hint(block, "path", f"{prefix}-help-path")}'
        f'{_hint(block, "value", f"{prefix}-help-value")}{_hint(block, "value_type", f"{prefix}-help-type")}</div>'
        '</section>'
        '<details class="owned-advanced" data-condition-advanced>'
        f'{_text(block, "advanced", "Advanced settings", "summary")}'
        f'<div class="owned-fields">{"".join(selects)}</div></details>'
        f'<section class="cond-preview" aria-labelledby="{prefix}-preview">'
        f'{_text(block, "preview_title", "Test with a sample message", "h3", f' id="{prefix}-preview"')}'
        f'<div class="field-group"><label for="{prefix}-sample">{_text(block, "sample", "Sample message")}</label>'
        f'<textarea {sample_attrs}></textarea>{_hint(block, "sample", f"{prefix}-help-sample")}</div>'
        '<div class="cond-preview-actions"><button type="button" class="ghost-btn" data-condition-test>'
        f'{_text(block, "test", "Test the conditions")}</button></div>'
        '<div class="cond-preview-result" data-condition-preview-result role="status" aria-live="polite"></div>'
        '</section></div>'
    )


HELP = {
    "combinator": "all: every condition must match. any: at least one condition must match.",
    "path": "path: names separated by dots, with [index] for arrays, e.g. customer.email or items[0].price. "
            "Leave empty for the whole message. A path that does not resolve is missing, not an error.",
    "value": "value: JSON such as 100, true, null, [\"FR\",\"BE\"] or \"quoted text\"; anything else is plain text. "
             "Ignored by exists, not_exists, is_empty, is_not_empty, is_true and is_false.",
    "value_type": "value_type: auto keeps JSON types (a number against numeric text compares as numbers); "
                  "string, number, boolean and datetime convert both sides. case_sensitive applies to text.",
    "parse_json": "auto parses text that is valid JSON and keeps other text; always requires JSON; never compares the raw text.",
    "on_error": "fail stops the activation without publishing when a condition cannot be evaluated; "
                "no_match counts that condition as false and logs a warning.",
    "sample": "Evaluated like a text message with the settings being edited, including unapplied changes. "
              "Nothing is saved, sent or run.",
}


def _with_editor(template, render, editor):
    """Insert the editor after generic placeholder rendering, through an unguessable marker."""
    marker = f"<!--condition-editor-{secrets.token_hex(8)}-->"
    return render(template.replace("{{ editor }}", marker)).replace(marker, editor)


def modal(block, node, payload):
    """Use the generic draft host; refreshing runtime must not replace pending settings."""
    template = (block.directory / "block_modal.html").read_text(encoding="utf-8")
    html = _with_editor(template, lambda text: block._render_generic_modal_template(
        template=text, node=node, payload=payload or {}), editor_html(block, node, "modal"))
    return {"html": html, "context": {"node_id": str(node.get("id", "")), "node_kind": block.kind}}


def inspector(block, node, payload):
    """Render the same editor with the standard Ports tab and sticky Apply control."""
    template = (block.directory / "inspector_panel.html").read_text(encoding="utf-8")
    html = _with_editor(template, lambda text: render_inspector_template(
        template=text, node={**node, "kind": block.kind, "type": block.kind}, payload=payload),
        editor_html(block, node, "inspector"))
    return {"html": html, "context": {"node_id": str(node.get("id", "")), "full_panel": True}}


def card(block, node):
    """First condition in short form plus "and N more"; single-pass so content is never re-substituted."""
    summary = logic.card_summary(node.get("config") or {})
    if summary is None:
        detail = _text(block, "card_invalid", "Invalid settings: open the block to fix them.", "span", ' class="cond-card-invalid"')
    else:
        detail = f'<span class="cond-card-first">{escape(summary["first"])}</span>'
        if summary["more"]:
            params = {"count": summary["more"], "combinator": summary["combinator"]}
            name = f"block.{block.kind}.card_more"
            text = block.translate(name, params, fallback="and {count} more ({combinator})")
            detail += (f' <span class="cond-card-more" data-i18n="{name}" '
                       f'data-i18n-params="{escape(json.dumps(params), quote=True)}">{escape(text)}</span>')
    values = {"title": escape(str(node.get("title") or block.default_title())),
              "purpose": escape(block.description(), quote=True), "detail": detail}
    template = (block.directory / "node_card.html").read_text(encoding="utf-8")
    html = re.sub(r"__(title|purpose|detail)__", lambda match: values[match.group(1)], template)
    return {"html": html, "context": {"node_id": str(node.get("id") or ""), "node_classes": [block.kind + "-node"]}}
