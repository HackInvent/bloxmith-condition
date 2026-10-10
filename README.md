# If

Route each message to true or false from explicit conditions. If is the generic
two-way branch of a workflow: every message received on `in` is published,
unchanged, on exactly one of the `true` and `false` outputs. It is deterministic
and declarative: conditions are settings, not code, and nothing is ever evaluated,
fetched or modified.

<!-- block-metadata:start -->
[![Block version: 0.1.0](https://img.shields.io/badge/block-0.1.0-blue)](model.json)
[![BloxSmith compatibility: 1.0.9](https://img.shields.io/badge/BloxSmith-1.0.9-brightgreen)](compatibility.json)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Verified BloxSmith versions: **1.0.9** (bundled-block tests; see [test evidence](compatibility.json)).
<!-- block-metadata:end -->

[![If — route each message to true or false](media/thumbnail.webp)](media/cover.png)

## Ports

| Direction | Port | Meaning |
| --- | --- | --- |
| Input | `in` | Required message: JSON or text (`message/*`, `application/json`, `text/plain`) |
| Output | `true` | The received message, unchanged, when the condition group matches |
| Output | `false` | The received message, unchanged, when the group does not match |

Exactly one output is published per message, with the received text and its
content type. The other output publishes nothing (its previous value is cleared).
An empty or whitespace-only message is not routed. Use **Switch** for more than
two branches and **Filter** to drop non-matching messages instead of routing them.

## Settings

| Setting | Values | Default |
| --- | --- | --- |
| `combinator` | `all` (every condition must match) or `any` (at least one) | `all` |
| `conditions` | 1 to 32 condition objects, evaluated in order | `status equals "paid"` |
| `parse_json` | `auto`, `always` or `never` (see below) | `auto` |
| `on_error` | `fail` or `no_match` (see below) | `fail` |

A condition object:

```json
{"path": "customer.email", "operator": "ends_with", "value": "@example.com",
 "value_type": "auto", "case_sensitive": true}
```

- `path`: empty for the whole message, otherwise names separated by dots with
  `[index]` for array items: `customer.email`, `items[0].price`, `rows[2]`, or
  `[0].name` when the message itself is an array. Names are matched exactly
  (case included), at most 32 steps (each name or index counts), 512 characters.
  A path that does not resolve is **missing**, never an error.
- `operator`: one of the operators below.
- `value`: the JSON value to compare with. Ignored by `exists`, `not_exists`,
  `is_empty`, `is_not_empty`, `is_true` and `is_false`.
- `value_type`: `auto` (default), `string`, `number`, `boolean` or `datetime`.
- `case_sensitive`: `true` (default) or `false`, for text comparisons.

### Operators

| Operator | Matches when the value at `path`… |
| --- | --- |
| `exists`, `not_exists` | resolves (even to `null`) / does not resolve |
| `is_empty`, `is_not_empty` | is missing, `null`, `""`, `[]` or `{}` / is anything else |
| `equals`, `not_equals` | equals `value` under `value_type` / does not |
| `contains`, `not_contains` | contains `value`: substring of a text, member of an array, key of an object |
| `starts_with`, `ends_with` | as text, starts or ends with `value` |
| `greater_than`, `greater_or_equal`, `less_than`, `less_or_equal` | compares as a number or a date |
| `matches_regex` | Python `re.search` finds the pattern `value` (≤ 256 characters) in its text (≤ 10,000 characters) |
| `in_list`, `not_in_list` | equals one of the items of `value`, a JSON array of at most 256 items / none |
| `is_true`, `is_false` | is true / false after boolean conversion |

### Value types

- `auto`: JSON types as received. A number against text that holds a finite number
  compares numerically (`5` equals `"5.0"`, `"5"` is greater than `3`). Otherwise
  values compare as text: objects and arrays as compact JSON, `true`, `false` and
  `null` as those words. Arrays and objects of the same type compare structurally
  (key order ignored, `1` equals `1.0`, `true` never equals `1`).
- `string`: both sides as text (objects and arrays in compact JSON, as received).
- `number`: both sides must be finite numbers or numeric text, otherwise an
  evaluation error. Integer text is compared exactly, so long identifiers keep
  every digit.
- `boolean`: `true`/`false`, the words `true|false|yes|no|1|0` in any case, or the
  numbers 1 and 0; anything else is an evaluation error.
- `datetime`: ISO 8601 dates or date-times (`2026-01-02`, `2026-01-02T10:00:00Z`,
  `2026-01-02T12:00:00+02:00`). A value without offset is UTC. Instants are compared.

For `number`, `boolean` and `datetime`, spaces around the received text are ignored.
Case-insensitive comparisons use Unicode case folding (`STRASSE` equals `straße`).

### Message parsing (`parse_json`)

- `auto`: text that is valid standard JSON is parsed (whatever its content type);
  other text, including `NaN`, stays text. A text message such as `1.50` therefore
  becomes the number 1.5: use `never` to test the exact characters.
- `always`: the message must be valid JSON, otherwise every condition is an
  evaluation error.
- `never`: conditions read the raw text; only the empty path resolves.

### Errors (`on_error`)

An evaluation error is a message that cannot be compared as configured, such as
`"abc"` with `value_type: number`, a text longer than 10,000 characters for
`matches_regex`, or a non-JSON message with `parse_json: always`.

- `fail` (default): the activation fails with an explicit English message naming
  the condition and the reason, for example `Condition 1 (amount greater_than) could
  not be evaluated: the value is not a finite number.` Nothing is published. In
  Active Runtime, like any failed block, this stops the block's worker for the run.
- `no_match`: the failing condition counts as false, a warning trace is logged
  (`[condition-warning] …`) and the message is routed normally.

Error messages and traces name the condition, its path and operator, but never
copy message content.

## Framing decisions

The shared condition language (also used by Switch and Filter) leaves a few choices
to each block. If makes these:

- **Every condition is evaluated**, so the order of conditions never changes the
  result, and a `fail` error is never hidden by an earlier decisive condition.
- **Missing fields**: positive operators are false, their negations (`not_equals`,
  `not_contains`, `not_in_list`) true; ordering, `matches_regex`, `starts_with`,
  `ends_with`, `is_true` and `is_false` are false. A missing field is never an error.
- **Ordering operators compare numbers or dates only.** With `value_type: auto`,
  both sides must be numbers or numeric text, otherwise an evaluation error asks
  for `datetime`; text is never ordered alphabetically. `string` and `boolean` are
  refused for these operators, and `number`, `boolean` and `datetime` are refused
  for `contains`, `not_contains`, `starts_with`, `ends_with` and `matches_regex`.
- **Settings are checked when applied and when a run is prepared**: unknown
  operators, invalid paths, regular expressions, lists, configured values that do
  not fit their `value_type` (for example `abc` for `number`, or a date with `auto`
  ordering), unknown fields inside a condition, and empty values for `contains`,
  `starts_with`, `ends_with` and `matches_regex` (an empty needle would always
  match). Names in a path cannot start or end with a space (usually a typo).
  Unknown top-level settings are ignored, so framework-owned settings never break
  a run.
- The default condition is `status equals "paid"`, an example to replace.

## Editing

The modal and the inspector share one editor:

- a combinator switch (`all` / `any`);
- one row per condition (`path`, `operator`, `value`, `value_type`,
  `case_sensitive`) with **Add a condition**, move up/down and **Remove**; fields
  an operator ignores are hidden and unsupported value types disabled;
- the value field takes JSON (`100`, `true`, `null`, `["FR","BE"]`, `"quoted text"`)
  and keeps anything else as plain text, so `paid` is the text `paid` and `"3"` the
  text `3`;
- live validation: each row shows its problem in the current language while you
  type, using the same Python code as the run;
- **Test the conditions**: paste a sample message and see where it would be routed
  and how each condition evaluated, with the settings being edited, before Apply.
  The sample is evaluated like a text message; nothing is saved, sent or run.

Changes stay local until **Apply**; Cancel/Close discards them. Restart a loaded
Run to use new settings. The node card shows the first condition and how many
follow, for example `status equals "paid" and 2 more (any)`.

## Example

Settings that send large or priority orders to `true`:

```json
{
  "combinator": "any",
  "conditions": [
    {"path": "total", "operator": "greater_or_equal", "value": 500, "value_type": "number", "case_sensitive": true},
    {"path": "customer.tier", "operator": "in_list", "value": ["gold", "platinum"], "value_type": "auto", "case_sensitive": false}
  ],
  "parse_json": "auto",
  "on_error": "no_match"
}
```

`{"total": "620.00", "customer": {"tier": "Silver"}}` goes to `true` (620 ≥ 500).
`{"total": 80, "customer": {"tier": "Gold"}}` also goes to `true`.
`{"total": "n/a"}` goes to `false` with a warning, because `n/a` is not a number.

## Execution, limits and dependencies

- One activation per message in One Shot and Active Runtime (Active Runtime uses
  the `on_each_event` policy, so a burst of messages is routed one by one).
- One Shot hands blocks each message trimmed of surrounding whitespace; If forwards
  exactly the text it receives and the content type of the delivering connection.
- No files, no persistent state, no network, no secrets, no third-party package:
  Python standard library only (`re`, `json`, `datetime`).
- `matches_regex` uses Python's `re`, which has no time limit. Patterns are trusted
  settings: avoid nested quantifiers such as `(a+)+` on long texts.
- Limits: 32 conditions, 32 path steps, 512-character paths, 256-character
  patterns, 10,000-character regex subjects, 256-item lists, 262,144-character editor samples.

## Security

Conditions are trusted block settings, never read from incoming messages. Messages
are untrusted data: they are parsed as JSON at most, never executed, and are not
copied into errors, warnings, logs or run metadata by this block. The routed
payload itself is of course the message.

## Tests

Three package-owned suites run against a disposable, pinned BloxSmith 1.0.9 in the
private workspace:

- `F5.01`: the shared canonical vectors, every operator and value type, paths,
  parsing modes, settings validation, routing results, the editor contract and the
  English/French catalogs;
- `F5.02`: real graph runs in One Shot and Active Runtime, with bundled, managed
  and linked package installations: both branches, unchanged payloads and content
  types (including JSON from the List block), `fail` and `no_match`, refusal at
  preparation, a two-message burst through Event OR, and Stop of a loaded run;
- `F8.01`: the real modal and inspector in Chromium for managed and linked
  packages: rows, reordering, live validation, the sample test, Apply/Cancel,
  persistence, keyboard use, English and French at desktop and mobile widths.

Not qualified: browsers other than Chromium, other BloxSmith versions, and regular
expression execution time.
