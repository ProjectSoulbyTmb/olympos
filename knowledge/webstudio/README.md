# Webstudio Knowledge Database

Distilled knowledge of [Webstudio](https://webstudio.is/) - the open-source,
agent-first visual website builder we integrate into our websystems. Learned
from webstudio.is, docs.webstudio.is (`llms.txt` corpus), and the CLI/MCP
reference (v0.293.x era). Read `overview.md` first if Webstudio is new to you;
Hermes sessions doing site work should jump straight to `agent-integration.md`
and `playbooks.md`.

## Layout

| File | What it is |
|---|---|
| `webstudio.json` | Machine-readable database: one object per entry (`id`, `title`, `category`, `summary`, `details`, `sources`, `tags`). Append-only; ids are `WS-###`, monotonic, never renumbered. |
| `overview.md` | Product model: Builder vs Projects split, open-core stance, what makes it agent-friendly. |
| `agent-integration.md` | THE integration reference: CLI setup, linking, MCP tools, safety rules, vision verification loop. |
| `data-and-cms.md` | Data layer: Resources, bindings, dynamic pages, assets-as-CMS, 404 patterns. |
| `design-system.md` | Tokens, CSS variables, breakpoints, Radix components, copy-paste ingestion. |
| `publishing-hosting.md` | Cloud hosting, custom domains, static vs dynamic exports, platform matrix. |
| `playbooks.md` | Step-by-step recipes Hermes runs against real websystems. |

## How agents pull from this DB

1. **Task is "build/edit a site"** -> `agent-integration.md` + `playbooks.md`.
2. **Task touches content/data plumbing** -> `data-and-cms.md`.
3. **Task touches look/theme consistency** -> `design-system.md`.
4. **Task ships or hosts** -> `publishing-hosting.md`.
5. Programmatic lookup -> filter `webstudio.json` by `category` or `tags`.

### Wired surfaces

- **Search**: every topic file and every JSON entry is indexed by
  `python knowledge/engine.py` (TF-IDF). Query examples:
  `search "webstudio mcp checkpoint"` -> `ws:WS-009`,
  `search "share link credential"` -> `ws:WS-004`.
- **PTAH tool**: the `knowledge` tool hits this corpus automatically
  (same engine).
- **Verify gate**: `knowledge/verify_knowledge.py` validates schema,
  unique monotonic `WS-###` ids, https sources, and retrieval hits;
  wired into `doctor.py --ci`.

Adding entries: append with the next free `WS-###`, keep ids strictly
increasing (the gate enforces it), cite https sources.

## Refresh policy

Webstudio ships fast (docs regenerate from CLI source every release). Before a
non-trivial site engagement, re-check the live corpus:

- Doc index: `https://docs.webstudio.is/llms.txt` (append `.md` to any doc URL)
- Ask-the-docs: `GET https://docs.webstudio.is/<page>.md?ask=<question>`
- CLI truth: `npx --yes webstudio@latest --help`

Then append new facts here as fresh `WS-###` entries instead of rewriting old ones.
