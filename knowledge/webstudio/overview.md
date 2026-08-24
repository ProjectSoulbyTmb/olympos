# Webstudio Overview

*Source: webstudio.is landing + docs corpus, learned 2026-08-24.*

## What it is

Webstudio is an **open-source visual website builder** - the community's
"open-source Webflow" - explicitly positioned as a **professional builder for
Agents and Humans**. Humans design in the Visual Editor; agents (like Hermes)
build and modify the same projects through CLI and MCP. Both edit the same
native project model, so agent work stays fully editable in the Builder.

Key properties:

- **Frontend-only by philosophy**: it intentionally leaves the backend to
  external systems (CMS, CRM, databases) over HTTP APIs.
- **Radix UI primitives**: interactive components are accessible by default.
- **Full CSS**: every property/unit/breakpoint exposed in the visual tool -
  no proprietary styling abstraction to fight.
- **Open core**: public roadmap (`wstd.us/roadmap`), code
  (`webstudio-is/webstudio`), Discord community. Scale: ~230K projects,
  ~145K users, ~8.9K GitHub stars.

## Architecture: Builder vs Projects

| System | Where | Self-host? |
|---|---|---|
| Builder | hosted at apps.webstudio.is | possible but not recommended in production |
| Project site | published to Webstudio Cloud OR exported anywhere | yes - first-class |

This split is why automation works well: we target a *Project* through its
share-link credential while designers keep their hosted Builder workflow.
Exports come in two flavors - dynamic Remix app or static site (see
`publishing-hosting.md`).

## Why we picked it as websystem frontend

1. Agent-native: MCP tools cover pages, instances, styles, tokens, resources,
   assets, domains, publishing, screenshots - full lifecycle without scraping.
2. Backend-agnostic: plugs onto Supabase/Airtable/Notion/any REST/GraphQL API;
   also runs backend-free with its file-based Content Engine.
3. Performance posture: Cloudflare-backed cloud, automatic WebP/AVIF +
   responsive images, scroll-driven animations on the Scroll Timeline API
   (off main thread), Lighthouse-perfect sites are attainable.
4. Escape hatches everywhere: HTML/CSS/Tailwind/Webflow paste conversion,
   HTML embeds for arbitrary JS (GSAP etc.), static export when we need zero
   runtime.

## Ecosystem map

- Docs for agents: `https://docs.webstudio.is/llms.txt` (every page has `.md`)
- Ask-the-docs: `GET https://docs.webstudio.is/<page>.md?ask=<question>`
- Marketplace templates, Gallery of production builds
- Inception: built-in AI design-direction generation/comparison
- Headless CMS Finder tool for backend selection
