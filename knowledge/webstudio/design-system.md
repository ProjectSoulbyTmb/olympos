# Webstudio Design System Primitives

*Source: docs.webstudio.is foundations (tokens, css-variables, breakpoints,
style-panel, states-and-selectors), core-components, radix.*

## Styling stack

| Primitive | What | Agent surface (MCP) |
|---|---|---|
| Local styles | per-instance CSS, every property/unit exposed | `update-styles`, `delete-styles` |
| Design tokens | named style packages applied like classes; edit once = sync everywhere | token/style-source CRUD: create/attach/detach/extract/duplicate/rename/lock/reorder/clear |
| CSS variables | reusable values feeding style inputs | `list-css-variables`, `define-css-variable`, `delete-css-variable` (withUsage) |
| Data variables | typed state (string/number/bool/JSON) scoped to an instance | `create-variable`, `update-variable` |
| States & selectors | `:hover :focus ...`, `::before/::after` variants in style panel | styles carry state keys |
| Breakpoints | responsive cascade; base breakpoint + custom widths | `list-breakpoints`, breakpoint CRUD |

Theme recipe for fleet sites: define CSS variables for palette/spacing ->
wrap into design tokens (`accent-button`, `card`, `section`) -> apply tokens
in fragments -> override locally only when truly exceptional.

## Component inventory (highlights)

**Core**: Element (layout box), Text/Heading/Paragraph/Inline Text,
Link, Image (auto WebP/AVIF + responsive srcset), Video/Vimeo/YouTube,
Form + Webhook Form (email + Zapier/n8n/Airtable pipes), Collection,
Slot (shared regions e.g. nav), Content Block (editable regions in
Content mode), HTML Embed / Content Embed / Markdown Embed,
List, Separator, Blockquote, Code Text, Time.

**SEO/structured**: Head Slot (per-page head), JSON-LD component,
XML Node + XML Time (sitemaps/RSS).

**Animation family**: Animation Group (foundation), Text Animation
(auto word/char splitting), Stagger Animation (cascades), Video Animation.
Scroll-driven via Scroll Timeline API - GPU-friendly, off main thread.
GSAP possible through HTML embed when needed.

**Radix UI** (accessible primitives): Accordion, Collapsible, Dialog,
Popover, Tooltip, Tabs, Navigation Menu, Select, Radio Group, Checkbox,
Switch, Sheet, Label.

Component ids look like `@webstudio-is/sdk-components-react-radix:Select`.
Discover with `components.search {"brief":"..."}`, inspect with
`components.get`. When hand-writing fragments, template-backed components
must include required children explicitly.

## Custom-code hooks

Custom classes, IDs, and `data-*` attributes can be attached to any instance -
the supported path for external scripts/animation libraries. Disable **atomic
CSS** in Project Settings when exports need human-readable class names.

## Ingesting existing design work

Paste converts foreign inputs to native editable structures:

- Webflow elements (site migration lever)
- HTML + CSS blocks (classes -> style sources)
- Tailwind utility classes -> native styles
- Markdown -> component tree; SVG code -> native SVG components

Use this to port existing websystem pages instead of rebuilding from zero.
