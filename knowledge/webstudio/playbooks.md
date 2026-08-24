# Webstudio Playbooks for Websystems

*Concrete recipes. Preconditions: Node >= 22.12, a Builder share link with
Build access (treated as a secret), project linked via
`npx webstudio init --link "<link>" --json` in an empty project root.*

## PB-1 Bootstrap & health check

```sh
npx webstudio permissions --json          # what may we do?
npx webstudio meta.index                  # capability catalog
npx webstudio status                      # session/namespace freshness
```

Read `meta.session.commitStatus` after every mutation; expect `committed`.

## PB-2 Landing page from scratch

1. `list-pages` -> find home page id (`get-page-by-path {"path":"/"}`).
2. Draft section JSX offline (`.temp/hero.json`) - semantic tags, tokens for
   theme colors, `css` templates for styles.
3. `insert-fragment --input-file .temp/hero.json --dry-run` -> review plan ->
   run without `--dry-run`.
4. Interactive bits: `components.search` the radix piece ->
   `insert-component` (template applies child parts automatically).
5. Text pass: `update-text` / `replace-text {"find":"Start free","replace":"Get started"}`.
6. Verify: one `mcp run` [preview.start, screenshot /, preview.stop] + vision.

## PB-3 Blog with zero backend (Content Engine)

1. Upload markdown posts: `upload-asset {name,type:"document",format:"md",...}`
   with front-matter properties (title/slug/publishedAt/draft); organize into
   asset folders.
2. List resource: `create-assets-resource` query many/md/not-draft sorted by
   publishedAt desc, fields-only output -> bind into **Collection**.
3. Detail page `/blog/:slug`: query one by slug eq `system.params.slug`,
   content mode `markdown-body-ref` -> **Markdown Embed**.
4. 404 pattern on the detail page (status code + conditional Show) - see
   `data-and-cms.md`.
5. Sitemap: XML Node component listing posts; verify `audit {"scopes":["seo"]}`.

## PB-4 Frontend for an existing API (Supabase/Airtable/etc.)

1. `create-resource` REST (or GraphQL control) with expression headers;
   `exposeAsDataSource:true`, scoped to body instance.
2. Collection bound to `Posts.data.items`; item fragment references
   `collectionItem.field` expressions.
3. Filters: JSON data variable `filters` + searchParams expressions reading it.
4. Dynamic detail pages per record + 404 pattern.
5. Secrets NEVER inline: headers use `auth.token` style bindings set through
   the Builder by the operator, not committed literals in automation logs.

## PB-5 Visual verification gate (mandatory before publish)

```
mcp run [
  {"tool":"preview.start"},
  {"tool":"screenshot","input":{"path":"/","viewport":{"width":1440,"height":900},"output":".temp/home-desktop.png"}},
  {"tool":"screenshot","input":{"path":"/","viewport":{"width":375,"height":812},"output":".temp/home-mobile.png"}},
  {"tool":"screenshot.diff","input":{"baselinePath":".temp/baseline-home.png","currentPath":".temp/home-desktop.png","outputDir":".temp/diff","expectedText":["<must-appear>"]}},
  {"tool":"preview.stop"}
]
```

- `list-breakpoints` first when responsive work happened.
- Inspect every PNG with vision; read `textAnalysis`; iterate until clean.

## PB-6 Audit + ship

```sh
npx webstudio audit '{"scopes":["accessibility","seo","performance"]}'
# then via MCP:
publish {"target":"staging"}     -> verify staging URL + screenshots
publish {"target":"production"}
```

Domain work: `create-domain` -> verify DNS -> publish to selected domains.

## PB-7 Self-host export

```sh
npx webstudio sync
npx webstudio build --template ssg      # static; or docker template
cd <generated> && npm ci && npm run build
```

Deploy per `publishing-hosting.md` matrix. Remember static limitations list -
if any apply, use the docker/Remix route instead.

## PB-8 Multi-site fleet sweep

Manifest `.temp/fleet.json`:

```json
{
  "concurrency": 4,
  "projects": [
    {"id":"site-a","root":"../clients/site-a","calls":[{"tool":"audit"},{"tool":"status"}]},
    {"id":"site-b","root":"../clients/site-b","calls":[{"tool":"audit"}]}
  ]
}
```

`webstudio mcp run .temp/fleet.json` - reads only; add `--approve-mutations`
only after reviewing the full manifest; rely on resume after interruptions.

## Hard rules recap

- Share link = credential. Never commit/log/render it.
- Read ids before writes; semantic tools over patches; dry-run risky shapes.
- Checkpoints: stop -> report -> ack. Never bypass.
- Sequential CLI calls per project folder; batches via `mcp run`.
- No visual change ships without screenshot verification.
