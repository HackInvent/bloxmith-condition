/** Condition row editor: drafts stay local until Apply; checks call the block's own read-only routes. */
const KEY = "block.condition.";

export function bindEditor(root, api) {
  const editor = root.querySelector("[data-condition-editor]");
  const apply = root.querySelector("[data-owned-apply]");
  if (!editor || !apply) return () => {};
  const controller = new AbortController();
  const { signal } = controller;
  const list = editor.querySelector("[data-condition-rows]");
  const template = editor.querySelector("template[data-condition-row-template]");
  const add = editor.querySelector("[data-condition-add]");
  const count = editor.querySelector("[data-condition-count]");
  const groupError = editor.querySelector("[data-condition-group-error]");
  const status = root.querySelector("[data-condition-status]");
  const sample = editor.querySelector("[data-condition-sample]");
  const test = editor.querySelector("[data-condition-test]");
  const result = editor.querySelector("[data-condition-preview-result]");
  const max = Number(editor.dataset.max) || 32;
  // IDs are DOM references for aria-describedby, not security tokens.
  const base = `condition-${Math.random().toString(36).slice(2)}`;
  let serial = 0, dirty = false, pending = false, generation = 0, timer = 0, checkSeq = 0, testSeq = 0;
  const readOnly = () => Boolean(api.isReadOnly?.());

  /** Translated text that follows a language change; fallback is the English text. */
  const say = (element, key, fallback, params = {}) => {
    if (!element) return;
    if (globalThis.CWI18n?.set) globalThis.CWI18n.set(element, KEY + key, params, fallback);
    else element.textContent = api.t?.(KEY + key, params, fallback) || fallback;
  };
  /** Raw content (labels built from user settings) never carries a translation marker. */
  const raw = (element, text) => {
    if (globalThis.CWI18n?.setText) globalThis.CWI18n.setText(element, text);
    else element.textContent = text;
  };
  const rows = () => [...list.querySelectorAll(":scope > [data-condition-row]")];
  const field = (row, name) => row.querySelector(`[data-condition-field="${name}"]`);

  /** Show only the fields the operator reads; allowed value types come from server-rendered data. */
  function syncRow(row) {
    const option = field(row, "operator").selectedOptions[0];
    const valueless = option?.dataset.valueless === "true";
    const types = new Set((option?.dataset.types || "").split(" ").filter(Boolean));
    row.querySelector("[data-condition-value-field]").hidden = valueless;
    row.querySelector("[data-condition-type-field]").hidden = valueless;
    row.querySelector("[data-condition-case-field]").hidden = valueless;
    for (const choice of field(row, "value_type").options) choice.disabled = types.size > 0 && !types.has(choice.value);
  }

  function prepare(row) {
    const error = row.querySelector("[data-condition-row-error]");
    if (!error.id) error.id = `${base}-${++serial}-error`;
    syncRow(row);
  }

  /** Positions, counts and the availability of every row action. */
  function renumber() {
    const items = rows();
    items.forEach((row, index) => {
      raw(row.querySelector("[data-condition-number]"), String(index + 1));
      row.querySelector('[data-condition-move="up"]').disabled = readOnly() || index === 0;
      row.querySelector('[data-condition-move="down"]').disabled = readOnly() || index === items.length - 1;
      row.querySelector("[data-condition-remove]").disabled = readOnly() || items.length === 1;
    });
    add.disabled = readOnly() || items.length >= max;
    raw(count, `${items.length} / ${max}`);
  }

  function sync() {
    apply.disabled = !dirty || pending || readOnly();
  }

  /** The draft sent to the server; value_text is converted by the block, exactly like Apply. */
  function draft() {
    const setting = name => editor.querySelector(`[data-condition-setting="${name}"]:checked`)?.value
      ?? editor.querySelector(`select[data-condition-setting="${name}"]`)?.value;
    return {
      combinator: setting("combinator"),
      parse_json: setting("parse_json"),
      on_error: setting("on_error"),
      conditions: rows().map(row => ({
        path: field(row, "path").value,
        operator: field(row, "operator").value,
        value_text: field(row, "value_text").value,
        value_type: field(row, "value_type").value,
        case_sensitive: field(row, "case_sensitive").checked,
      })),
    };
  }

  function clearErrors() {
    for (const row of rows()) {
      const error = row.querySelector("[data-condition-row-error]");
      error.hidden = true;
      raw(error, "");
      for (const control of row.querySelectorAll("[aria-invalid]")) {
        control.removeAttribute("aria-invalid");
        control.setAttribute("aria-describedby", (control.getAttribute("aria-describedby") || "").replace(error.id, "").trim());
        if (!control.getAttribute("aria-describedby")) control.removeAttribute("aria-describedby");
      }
    }
    groupError.hidden = true;
    raw(groupError, "");
  }

  /** One message per row (the first problem found) and one for group settings. */
  function showErrors(errors) {
    clearErrors();
    const items = rows();
    for (const error of errors || []) {
      const row = error.index ? items[error.index - 1] : null;
      const target = row ? row.querySelector("[data-condition-row-error]") : groupError;
      if (!target || !target.hidden) continue;
      target.hidden = false;
      say(target, `err_${error.code}`, error.message, error.params || {});
      const name = error.field === "value" ? "value_text" : error.field;
      const control = row && name ? field(row, name) : null;
      if (control) {
        control.setAttribute("aria-invalid", "true");
        control.setAttribute("aria-describedby", `${control.getAttribute("aria-describedby") || ""} ${target.id}`.trim());
      }
    }
  }

  /** Server-side validation of the current draft, ignoring answers to older drafts. */
  async function check() {
    const sequence = ++checkSeq;
    const response = await api.blockRequest("validate", { payload: { values: { config: draft() } } });
    if (signal.aborted || sequence !== checkSeq) return null;
    showErrors(response?.errors || []);
    return response;
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => { check().catch(() => {}); }, 350);
  }

  function changed() {
    generation += 1;
    checkSeq += 1; // answers about an older draft (row indices may have moved) are ignored
    dirty = true;
    raw(status, "");
    sync();
    schedule();
  }

  function addRow() {
    if (readOnly() || rows().length >= max) return;
    const row = template.content.firstElementChild.cloneNode(true);
    list.append(row);
    prepare(row);
    globalThis.CWI18n?.apply?.(row);
    renumber();
    changed();
    field(row, "path").focus();
  }

  function move(row, direction) {
    const sibling = direction === "up" ? row.previousElementSibling : row.nextElementSibling;
    if (!sibling) return;
    if (direction === "up") sibling.before(row); else sibling.after(row);
    renumber();
    changed();
    const button = row.querySelector(`[data-condition-move="${direction}"]`);
    (button.disabled ? row.querySelector(`[data-condition-move="${direction === "up" ? "down" : "up"}"]`) : button).focus();
  }

  function remove(row) {
    if (rows().length <= 1) return;
    const next = row.nextElementSibling || row.previousElementSibling;
    row.remove();
    renumber();
    changed();
    (next?.querySelector("[data-condition-remove]:not(:disabled)") || add).focus();
  }

  async function save() {
    if (!dirty || pending || readOnly()) return;
    const started = generation;
    pending = true;
    sync();
    say(status, "checking", "Checking the settings…");
    try {
      let verdict = null;
      try { verdict = await check(); } catch { verdict = null; }
      if (signal.aborted) return;
      if (verdict && !verdict.valid) {
        say(status, "fix_errors", "Not applied: fix the highlighted settings first.");
        return;
      }
      const title = root.querySelector("[data-block-title-field]");
      const result = await api.applyAction("save_settings", { node_patch: { ...(title ? { title: title.value } : {}), config: draft() } });
      if (result?.error) throw new Error(result.error);
      if (signal.aborted) return;
      if (started === generation) dirty = false;
      say(status, "saved", "Settings applied.");
    } catch (error) {
      if (!signal.aborted) raw(status, String(error?.message || error));
    } finally {
      pending = false;
      if (!signal.aborted) sync();
    }
  }

  /** Render one preview outcome line: the condition as written, then its translated result. */
  function outcomeLine(outcome) {
    const item = document.createElement("li");
    item.className = `cond-outcome cond-outcome-${outcome.outcome}`;
    const label = document.createElement("code");
    raw(label, outcome.label || "");
    const verdict = document.createElement("span");
    item.append(label, " ", verdict);
    result.querySelector("ol").append(item);
    if (outcome.outcome === "error") {
      say(verdict, "outcome_error", "error:");
      const reason = document.createElement("span");
      item.append(" ", reason);
      say(reason, `err_${outcome.code}`, outcome.message, outcome.params || {});
    } else {
      say(verdict, `outcome_${outcome.outcome}`, outcome.outcome === "true" ? "matches" : "does not match");
    }
  }

  async function preview() {
    const sequence = ++testSeq;
    result.replaceChildren();
    delete result.dataset.branch;
    const head = document.createElement("p");
    head.className = "cond-preview-head";
    result.append(head);
    say(head, "testing", "Testing…");
    try {
      const response = await api.blockRequest("preview", { payload: { values: { config: draft(), sample: sample.value } } });
      if (signal.aborted || sequence !== testSeq) return;
      if (!response?.valid) {
        result.dataset.branch = "invalid";
        showErrors(response?.errors || []);
        say(head, "preview_invalid", "Fix the highlighted settings to test them.");
        return;
      }
      showErrors([]);
      if (response.sample_error) {
        result.dataset.branch = "invalid";
        say(head, `err_${response.sample_error.code}`, response.sample_error.message, response.sample_error.params || {});
        return;
      }
      result.dataset.branch = response.branch || "failed";
      if (response.failure) say(head, "preview_failed", "The activation would fail and publish nothing (on_error fail).");
      else say(head, "preview_branch", "The message would be routed to {branch}.", { branch: response.branch });
      result.append(document.createElement("ol"));
      for (const outcome of response.outcomes || []) outcomeLine(outcome);
      if ((response.warnings || []).length) {
        const note = document.createElement("p");
        note.className = "field-hint";
        result.append(note);
        say(note, "preview_warnings", "Conditions in error count as false (on_error no_match).");
      }
    } catch (error) {
      if (signal.aborted || sequence !== testSeq) return;
      result.dataset.branch = "unavailable";
      say(head, "preview_unavailable", "The test could not run.");
    }
  }

  for (const row of rows()) prepare(row);
  renumber();
  root.addEventListener("input", event => {
    if (event.target.matches("[data-condition-field], [data-condition-setting], [data-block-title-field]")) changed();
  }, { signal });
  root.addEventListener("change", event => {
    const target = event.target;
    if (!target.matches("[data-condition-field], [data-condition-setting], [data-block-title-field]")) return;
    if (target.matches('[data-condition-field="operator"]')) syncRow(target.closest("[data-condition-row]"));
    changed();
  }, { signal });
  list.addEventListener("click", event => {
    const button = event.target.closest("button");
    const row = button?.closest("[data-condition-row]");
    if (!row || button.disabled || readOnly()) return;
    if (button.matches("[data-condition-move]")) move(row, button.dataset.conditionMove);
    else if (button.matches("[data-condition-remove]")) remove(row);
  }, { signal });
  add.addEventListener("click", event => { event.preventDefault(); addRow(); }, { signal });
  apply.addEventListener("click", event => { event.preventDefault(); void save(); }, { signal });
  test.addEventListener("click", event => { event.preventDefault(); void preview(); }, { signal });
  root.querySelector("[data-block-title-field]")?.addEventListener("keydown", event => {
    if (event.key === "Enter") { event.preventDefault(); void save(); }
  }, { signal });
  if (readOnly()) {
    for (const control of editor.querySelectorAll("[data-condition-field], [data-condition-setting]")) control.disabled = true;
  }
  sync();
  return () => {
    controller.abort();
    clearTimeout(timer);
  };
}
