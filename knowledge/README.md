# Knowledge Base

Distilled, durable lessons extracted from every system this workspace
has built and operated - engines, protection kernels, automation
sandboxes, message buses, provenance systems, and the development
process around them. This is the seed corpus for future app
development: read it before designing anything new here.

## Layout

| File | What it is |
|---|---|
| `lessons.json` | Machine-readable database: one object per lesson (`id`, `title`, `category`, `source`, `lesson`, `tags`). Query it with any JSON tooling; treat it as append-only. |
| `architecture-playbook.md` | Proven architecture patterns with when-to-use guidance. |
| `engineering-rules.md` | Hard-won rules that prevent repeat failures. |
| `webstudio/` | External-product DB: Webstudio website builder - agent/MCP integration, data/CMS patterns, design system, publishing, playbooks. Pull from here before building or editing any public-facing site. |

## Conventions

- Lessons are written to outlive their original context: they name the
  *pattern*, not the old project.
- New lessons are appended with a fresh `id` (`L###`, monotonic).
  Never renumber; deletions go through a deprecation note instead.
- Every lesson cites its `source` (organ/module or incident) so the
  operating code remains the living example.
