# JavaScript diagnostic input roles

Three original diagnostic paths are non-program inputs. Their roles are established
by the pinned corpus consumers, not by their `.js` suffix or Node rejection alone.
No JavaScript grammar correction or future-language exclusion is justified here.

| Language / input grammar | Language version | Repository | Relative path | Role and evidence |
| --- | --- | --- | --- | --- |
| JavaScript output with Django template syntax | Raw template has no ECMAScript version; minimum output version not declared | django | `django/views/templates/i18n_catalog.js` | `django/views/i18n.py:214–233` reads this file through `Engine().from_string`, renders catalog/plural/format context, and returns JavaScript. `{% ... %}` / `{{ ... }}` are generator input, not JavaScript statements. |
| JavaScript gettext extraction input | Not an executable JavaScript program; no applicable ECMAScript version for `print mysub();` | django | `tests/i18n/commands/javascript.js` | `tests/i18n/test_extraction.py:680–699` runs `makemessages(domain="djangojs")` and asserts extracted literals, including `okkkk` adjacent to the non-JS line. This is an extraction fixture; no claim that it deliberately tests parser rejection. |
| JavaScript output with literal data placeholder | Raw template has no ECMAScript version; minimum output version not declared | cpython | `Lib/profiling/sampling/_flamegraph_assets/flamegraph.js` | `Lib/profiling/sampling/stack_collector.py:497–507,551–566` loads this component and replaces `{{FLAMEGRAPH_DATA}}` with JSON in generated HTML. |

Node v26.3.0 rejects all three original inputs in syntax-only checks. The CPython
component passes the same check after exactly the generator's literal replacement
with synthetic JSON. That is a component-only probe, not a full HTML generation or
JavaScript execution test. Django rendering was not run: Django and its dependencies
are absent from the isolated environment. The source-level generator/consumer
proof is sufficient to establish the input roles; it does not qualify rendering.

The corpus is unchanged. These entries must be counted separately from verified
parser fixes. Two are template inputs and one is an extraction-only fixture;
none is classified as unsupported future JavaScript syntax. Parsing ordinary
JavaScript and its diagnostics remains unchanged.

Evidence under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `javascript-input-role-probes-r1/results.json`: original source/tool hashes,
  exact Node commands, exit statuses and retained stderr;
- `javascript-input-role-probes-r1/consumer-evidence.json`: source hashes and
  exact generator/consumer excerpts, rechecked against the current corpus;
- `javascript-rendered-component-r1/result.json`: synthetic data, exact output
  digest and passing component syntax check.

The overall correction goal remains open. Supported-version Python and the large
C/C++ population still need investigation and correction.
