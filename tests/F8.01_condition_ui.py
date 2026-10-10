"""FB7: real release UI — condition rows, reordering, live validation, sample test, drafts, EN/FR, responsive."""

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from playwright.sync_api import expect, sync_playwright
from block_test_artifacts import artifact_path
from block_test_packages import install_test_package
from ui_smoke_common import create_project_api, graph_payload, isolated_server, project_editor_url
from blocs.condition.block import ConditionBlock

VIEWPORTS = ((1440, 900), (800, 700), (390, 740), (320, 568))
GEOMETRY = """(el, bodySelector) => {
  const r = el.getBoundingClientRect(), body = el.querySelector(bodySelector) || el;
  const actions = [...el.querySelectorAll('[data-close-block-modal], [data-owned-apply]')].filter(a => a.getClientRects().length);
  const rows = [...el.querySelectorAll('[data-condition-row]')];
  return {
    inside: r.left >= -1 && r.right <= innerWidth + 1 && r.top >= -1 && r.bottom <= innerHeight + 1,
    overflow: el.scrollWidth > el.clientWidth + 2 || body.scrollWidth > body.clientWidth + 2
      || rows.some(row => row.scrollWidth > row.clientWidth + 2),
    controls: actions.every(a => { const b = a.getBoundingClientRect(); return b.top >= 0 && b.bottom <= innerHeight + 1; }),
    background: getComputedStyle(el).backgroundColor,
    unlabeled: [...el.querySelectorAll('input, select, textarea')].filter(c => !c.labels?.length
      && !c.getAttribute('aria-label') && !c.getAttribute('aria-labelledby')).length,
    small: [...el.querySelectorAll('[data-condition-row] button, [data-condition-add], [data-condition-test]')]
      .filter(b => b.getClientRects().length && b.getBoundingClientRect().height < 32).length,
  };
}"""


def geometry(panel, body=".owned-body"):
    """Opaque panel inside the viewport, reachable actions, no horizontal overflow, labeled controls."""
    measured = panel.evaluate(GEOMETRY, body)
    assert measured["inside"] and measured["controls"] and not measured["overflow"], measured
    assert not measured["unlabeled"] and not measured["small"], measured
    assert measured["background"] not in {"transparent", "rgba(0, 0, 0, 0)"}, measured


class Renders:
    """Track in-flight inspector renders: the shell re-renders the inspector after selection and card refreshes."""

    def __init__(self, page):
        self.pending, self.last = 0, time.monotonic()
        page.on("request", lambda request: self.track(request, 1))
        page.on("requestfinished", lambda request: self.track(request, -1))
        page.on("requestfailed", lambda request: self.track(request, -1))

    def track(self, request, delta):
        if request.url.endswith("/inspector-panel"):
            self.pending, self.last = max(0, self.pending + delta), time.monotonic()

    def settle(self, page, quiet=1.2, timeout=45):
        """Return once no inspector render is pending or has finished for ``quiet`` seconds."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            page.wait_for_timeout(100)
            if self.pending == 0 and time.monotonic() - self.last >= quiet:
                return
        raise AssertionError("Inspector renders did not settle")


def row(scope, number):
    return scope.locator("[data-condition-row]").nth(number - 1)


def field(item, name):
    return item.locator(f'[data-condition-field="{name}"]')


def edit_conditions(page, modal):
    """# - FB7 - FB3 - rows, operator-aware fields, live validation, reordering and removal."""
    first = row(modal, 1)
    field(first, "path").fill("amount")
    field(first, "operator").select_option("greater_than")
    expect(field(first, "value_type").locator('option[value="string"]')).to_have_js_property("disabled", True)
    expect(field(first, "value_type").locator('option[value="number"]')).to_have_js_property("disabled", False)
    field(first, "value_text").fill("100")
    field(first, "value_type").select_option("number")
    modal.locator("[data-condition-add]").click()
    expect(modal.locator("[data-condition-row]")).to_have_count(2)
    second = row(modal, 2)
    expect(field(second, "path")).to_be_focused()
    field(second, "path").fill("country")
    field(second, "operator").select_option("in_list")
    field(second, "value_text").fill('["FR","BE"]')
    field(second, "case_sensitive").uncheck()
    modal.locator("[data-condition-add]").click()
    third = row(modal, 3)
    field(third, "path").fill("email")
    field(third, "operator").select_option("exists")
    expect(field(third, "value_text")).to_be_hidden()
    field(third, "operator").select_option("matches_regex")
    expect(field(third, "value_text")).to_be_visible()
    field(third, "value_text").fill("(")
    error = third.locator("[data-condition-row-error]")
    expect(error).to_be_visible()
    expect(error).to_contain_text("regular expression")
    expect(field(third, "value_text")).to_have_attribute("aria-invalid", "true")
    field(second, "value_text").fill("FR, BE")
    expect(second.locator("[data-condition-row-error]")).to_contain_text('in_list needs a JSON array')
    field(second, "value_text").fill('["FR","BE"]')
    expect(second.locator("[data-condition-row-error]")).to_be_hidden()
    second.locator('[data-condition-move="up"]').click()
    expect(field(row(modal, 1), "path")).to_have_value("country")
    expect(row(modal, 1).locator("[data-condition-number]")).to_have_text("1")
    expect(row(modal, 1).locator('[data-condition-move="up"]')).to_be_disabled()
    row(modal, 1).locator('[data-condition-move="down"]').click()
    expect(field(row(modal, 1), "path")).to_have_value("amount")
    row(modal, 3).locator("[data-condition-remove]").click()
    expect(modal.locator("[data-condition-row]")).to_have_count(2)
    expect(modal.locator("[data-condition-count]")).to_have_text("2 / 32")
    expect(modal.locator("[data-condition-group-error]")).to_be_hidden()
    expect(row(modal, 2).locator("[data-condition-row-error]")).to_be_hidden()
    modal.locator(".cond-segment-option", has_text="any").click()
    modal.locator("[data-condition-advanced] > summary").click()
    modal.locator('[data-condition-setting="on_error"]').select_option("no_match")


def preview(scope, sample, branch, *texts):
    """# - FB7 - the sample test evaluates the draft with the same Python code as a run."""
    result = scope.locator("[data-condition-preview-result]")
    scope.locator("[data-condition-sample]").fill(sample)
    scope.locator("[data-condition-test]").click()
    expect(result).to_have_attribute("data-branch", branch)
    for text in texts:
        expect(result).to_contain_text(text)


def main():
    expect.set_options(timeout=20_000)
    for origin in ("managed", "linked"):
        with isolated_server() as server, sync_playwright() as playwright:
            model = install_test_package(server, "condition", origin=origin)
            candidate = ConditionBlock().build_node_payload(node_id="ui-case", position={"x": 160, "y": 160})
            candidate["block_version"] = model["version"]
            project = create_project_api(server, document=graph_payload("If editor", [candidate], []))["project"]
            url = project_editor_url(server.base_url, project["project_id"], workspace_project_id=project["workspace_project_id"])
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                renders = Renders(page)
                page.add_init_script("window.localStorage.setItem('bloxsmith.inspectorPinned','true')")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url)
                card = page.locator('.canvas-node[data-node-id="ui-case"]')
                expect(card.locator(".node-data-preview")).to_contain_text('status equals "paid"')
                card.locator("h3").dblclick()
                modal = page.locator(".cond-modal")
                expect(modal).to_be_visible()
                apply = modal.locator("[data-owned-apply]")
                expect(apply).to_be_disabled()
                expect(modal.locator("[data-condition-row]")).to_have_count(1)
                expect(field(row(modal, 1), "value_text")).to_have_value("paid")
                # Cancel discards a draft.
                field(row(modal, 1), "path").fill("state")
                expect(apply).to_be_enabled()
                modal.locator(".owned-footer [data-close-block-modal]").click()
                card.locator("h3").dblclick()
                expect(field(row(modal, 1), "path")).to_have_value("status")
                expect(apply).to_be_disabled()
                edit_conditions(page, modal)
                preview(modal, '{"amount": 150, "country": "de"}', "true", "routed to true", "amount greater_than 100 (number)")
                preview(modal, '{"amount": "lots", "country": "DE"}', "false", "routed to false",
                        "the value is not a finite number", "count as false")
                with page.expect_response(lambda r: r.url.endswith("/ui-action") and r.request.method == "POST") as saved:
                    apply.click()
                assert not saved.value.json().get("error"), saved.value.json()
                expect(modal.locator("[data-condition-status]")).to_have_text("Settings applied.")
                expect(apply).to_be_disabled()
                modal.locator(".owned-footer [data-close-block-modal]").click()
                expect(card.locator(".node-data-preview")).to_contain_text("amount greater_than 100 (number) and 1 more (any)")
                page.reload()
                card.locator("h3").dblclick()
                expect(modal.locator("[data-condition-row]")).to_have_count(2)
                expect(field(row(modal, 1), "value_text")).to_have_value("100")
                expect(field(row(modal, 1), "value_type")).to_have_value("number")
                expect(field(row(modal, 2), "value_text")).to_have_value('["FR","BE"]')
                expect(field(row(modal, 2), "case_sensitive")).not_to_be_checked()
                expect(modal.locator('[data-condition-setting="combinator"][value="any"]')).to_be_checked()
                expect(modal.locator('[data-condition-setting="on_error"]')).to_have_value("no_match")
                for width, height in VIEWPORTS:
                    page.set_viewport_size({"width": width, "height": height})
                    page.wait_for_timeout(150)
                    geometry(modal)
                    page.screenshot(path=artifact_path(f"condition-{origin}-{width}.png"))
                # Keyboard: add then remove a row without the mouse.
                page.set_viewport_size({"width": 1440, "height": 900})
                modal.locator("[data-condition-add]").focus()
                page.keyboard.press("Enter")
                expect(modal.locator("[data-condition-row]")).to_have_count(3)
                expect(field(row(modal, 3), "path")).to_be_focused()
                row(modal, 3).locator("[data-condition-remove]").focus()
                page.keyboard.press("Enter")
                expect(modal.locator("[data-condition-row]")).to_have_count(2)
                modal.locator(".owned-footer [data-close-block-modal]").click()
                # Inspector: same editor, Ports tab, sample test and Apply from the sticky toolbar.
                card.click(position={"x": 20, "y": 20})
                inspector = page.locator('[data-properties-surface="inspector"][data-node-id="ui-case"]:visible')
                expect(inspector).to_be_visible()
                renders.settle(page)
                expect(inspector.locator("[data-condition-row]")).to_have_count(2)
                assert inspector.evaluate("el => el.scrollWidth <= el.clientWidth + 2")
                preview(inspector, '{"amount": 101}', "true", "routed to true")
                field(row(inspector, 1), "value_text").fill("200")
                with page.expect_response(lambda r: r.url.endswith("/ui-action") and r.request.method == "POST") as saved:
                    inspector.locator("[data-owned-apply]").click()
                assert not saved.value.json().get("error"), saved.value.json()
                expect(card.locator(".node-data-preview")).to_contain_text("amount greater_than 200 (number)")
                inspector.locator('[data-inspector-tab="ports"]').click()
                expect(inspector.locator('[data-inspector-panel-tab="ports"]')).to_be_visible()
                inspector.locator('[data-inspector-tab="general"]').click()
                expect(inspector.locator('[data-inspector-panel-tab="general"]')).to_be_visible()
                page.screenshot(path=artifact_path(f"condition-{origin}-inspector.png"))
                # French: translated chrome, live validation and card text follow the language.
                page.goto(server.base_url + "/")
                page.locator("#homeApplicationSettingsButton").click()
                page.locator("#applicationLanguageSelect").select_option("fr")
                page.wait_for_function("window.CWMessages.getLanguage() === 'fr'")
                page.goto(url)
                expect(card.locator(".node-data-preview")).to_contain_text("et 1 autre (any)")
                card.locator("h3").dblclick()
                expect(modal.locator("[data-condition-add]")).to_have_text("Ajouter une condition")
                expect(modal.locator("[data-condition-test]")).to_have_text("Tester les conditions")
                expect(modal.locator("[data-condition-advanced] > summary")).to_have_text("Réglages avancés")
                field(row(modal, 1), "value_text").fill("abc")
                expect(row(modal, 1).locator("[data-condition-row-error]")).to_have_text(
                    "La valeur doit être un nombre fini pour value_type number.")
                preview(modal, '{"amount": 500}', "invalid", "Corrigez les réglages signalés pour les tester.")
                for width, height in ((1440, 900), (390, 740)):
                    page.set_viewport_size({"width": width, "height": height})
                    page.wait_for_timeout(150)
                    geometry(modal)
                    page.screenshot(path=artifact_path(f"condition-{origin}-fr-{width}.png"))
                page.set_viewport_size({"width": 1440, "height": 900})
                modal.locator(".owned-footer [data-close-block-modal]").click()
                card.click(position={"x": 20, "y": 20})
                expect(inspector).to_be_visible()
                renders.settle(page)
                expect(inspector.locator("[data-condition-add]")).to_have_text("Ajouter une condition")
                page.screenshot(path=artifact_path(f"condition-{origin}-fr-inspector.png"))
                assert not errors, errors
                assert page.evaluate("!window.CWBlockUiBlocks?.condition")
            finally:
                browser.close()
        print(f"[ok] condition {origin} UI", flush=True)


if __name__ == "__main__":
    main()
