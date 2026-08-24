# Webstudio Publishing & Hosting

*Source: docs.webstudio.is university/self-hosting.md, publishing-and-custom-domains, cli.*

## Decision tree

```
Need dynamic features? (CMS fetch at request time, webhook forms,
redirects, status codes, image optimization, sitemap/robots)
├─ yes -> JavaScript app export (Remix)
│         ├- easiest: Webstudio Cloud (Cloudflare-backed) or
│         │   serverless Netlify / Vercel
│         └- containers: Docker template -> AWS Flightcontrol /
│             Coolify (DigitalOcean/Hetzner) / any VPS (min 1GB RAM, 1 core)
└─ no  -> static export (`build --template ssg`)
          -> Cloudflare Pages / GitHub Pages / Netlify / Vercel
```

## Export type tradeoffs

| Capability | JS app | Static |
|---|---|---|
| Dynamic pages (`:slug`) | yes | **no** |
| Redirects + status codes | yes | **no** |
| Webhook forms | yes | **no** |
| Image optimization | yes | **no** |
| robots.txt / sitemap.xml | yes | **no** |
| Client navigation | yes | **no** |
| Hosting requirements | app runtime | any file host |

Static gotchas:

- Trailing-slash behavior is host-owned: Cloudflare Pages redirects
  `/about` -> `/about/`; Netlify normalizes to slash BEFORE redirect rules;
  Vercel serves both unless `"trailingSlash": false` in vercel.json. If exact
  non-slash URLs matter, ship the JS app.
- Local preview requires a server (`npx serve .`) - assets use absolute URLs.

## Agent publish flow (cloud)

1. Gate: `audit {"scopes":["accessibility","seo"]}` clean on changed pages.
2. Vision loop green (see `agent-integration.md` §4).
3. `publish {"target":"staging"}` -> verify staging URL.
4. `publish {"target":"production"}`; check job status; unpublish if rollback needed.
5. Domains: `create-domain {"domain":"www.example.com"}` then verify DNS;
   per-domain publish targets supported.

## Self-host pipeline (CLI)

```sh
npx webstudio link --link "<share-link>"        # or init --link --json
npx webstudio sync                              # bundle -> .webstudio/data.json + assets
npx webstudio build --template ssg              # or --template docker
# generated project has its own package.json scripts -> build/deploy
```

Publish to Webstudio Cloud first if the export must include the newest
Builder state. Disable atomic CSS in Project Settings for readable class names
in exports. Never add generated-preview dependencies to a repo root manifest.

## Fleet notes

- Multiple sites = multiple linked roots; orchestrate with cross-project
  `mcp run` manifests (`projects:[{id,root}]`, concurrency<=16, resume).
- Custom domains live per project; verification is part of the API surface.
