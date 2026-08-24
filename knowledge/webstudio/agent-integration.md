# Webstudio Agent Integration (CLI + MCP)

*The core reference for Hermes driving Webstudio. Source: docs.webstudio.is
`/university/cli.md` + `/university/mcp.md` (v0.293.x).*

## 0. Setup rules

- CLI package is **`webstudio`**, run via npx: `npx --yes webstudio@latest <cmd>`.
  Node >= 22.12. Never use old `@webstudio-is/cli` / `wstd`; never install
  globally (stale binary bugs).
- **A Builder share link with Build access is the credential.** Treat it like a
  secret: never commit, log, screenshot, or paste it into issues.
- Link non-interactively: `npx webstudio init --link "<share-link>" --json`.
- Check scope: `npx webstudio permissions --json`.
- All commands run from the **linked project root** (the dir containing
  `.webstudio/config.json`). Copying `.webstudio` does NOT clone a project -
  config still points at the remote.
- Do NOT run `webstudio sync` for MCP editing sessions; MCP syncs itself.

## 1. Calling tools without an MCP client

```sh
npx webstudio meta.index                                   # discovery
npx webstudio meta.guide '{"brief":"Create a pricing page"}'
npx webstudio components.search '{"brief":"radix select"}'
npx webstudio insert-fragment --input-file .temp/fr.json --dry-run
```

- One-shot form: `webstudio <tool> '<json>'`; explicit: `webstudio mcp single-op-call <tool> '<json>'`.
- Batch with shared session: `webstudio mcp run '[{"tool":"meta.index"},{"tool":"components.find","input":{"brief":"button"}}]'`
  (or pass a manifest file; `preview.start`+`screenshot`+`preview.stop` MUST share one run/process).
- stdout prints `{ok:true,data,meta}` on success and `{ok:false,error:{code,message}}`
  + nonzero exit on failure. Progress goes to stderr.
- Sequential calls only against the same project folder; `PROJECT_SESSION_BUSY`
  = another process owns the session - wait, retry.

## 2. Discovery before mutation

1. `meta.index` - capability catalog.
2. `meta.guide {"brief":"..."}` - workflow guidance for a goal.
3. Focused lookups: `components.list/search/find/get`, `templates.list/get`,
   `list-pages`, `get-page-by-path`, `list-instances`, `inspect-instance`,
   `search-project {"query":"..."}` (paged, credential-aware).
4. Never dump full resources (`webstudio://project/components|tools`) when the
   compact tools answer the question.

## 3. Mutation discipline

- **Read ids before writing.**
- Prefer **semantic tools** over raw `apply-patch`:
  `insert-component`, `insert-fragment`, `insert-collection`,
  `update-text`, `update-styles`, `update-props`, `bind-props`,
  page/folder/token/variable/resource/asset/domain CRUD,
  `extract-slot`, `move/reparent/clone/wrap/unwrap` element ops.
- Use `--dry-run` to get the computed transaction plan without committing;
  check `meta.session.commitStatus` (`planned|committed|failed|unchanged`;
  reads report `not-applicable`).
- **Checkpoint protocol**: on `checkpoint.required`, stop mutations, report to
  parent/user, then `checkpoint.ack {"reported":true,"continueAfterReport":true,"summary":"..."}`.
  State persists across processes until acked.
- Cross-project batches: `mcp run` manifest with `projects:[{id,root}]`,
  concurrency <=16, resume support; interrupted committed mutations become
  `AMBIGUOUS_MUTATION_RESULT` and are NEVER auto-replayed; batched mutations
  need explicit `--approve-mutations`.

### insert-fragment JSX dialect

```
<ws.element ws:tag="section" ws:style={css`padding:32px; display:grid; gap:16px;`}>
  <ws.element ws:tag="h2">Title</ws.element>
</ws.element>
```

- Styles: `` ws:style={css`...`} `` (declarations + `@media` only - no
  selectors/@keyframes) or React-style objects (`style={{padding:24}}`).
- Tokens: `ws:tokens={[token('accent', css`color:#0f766e;`)]}`.
- Events: `onClick={new ActionValue(["event"], expression`console.log(event)`)}` -
  never arrow functions.
- Prop names are HTML-ish: `class`, `for` (not className/htmlFor). Values must
  be JSON-compatible. No host globals (`process`, `eval`, ...).
- Radix templates need their child parts spelled out:
  `<radix.Switch><radix.SwitchThumb /></radix.Switch>` (or just use
  `insert-component` which applies the registered template).
- Big fragments -> `--input-file`. Keep artifacts under `<project root>/.temp/`.

## 4. Verify visually before finishing

1. Mutate in focused steps.
2. In ONE `mcp run`: `preview.start` -> `screenshot {path:"/", viewport:{width:1440,height:900}}`
   (+ `{width:375,height:812}` mobile, per changed path) -> `preview.stop`.
3. Call `list-breakpoints` first when doing responsive work.
4. Inspect every PNG with vision; compare against user intent.
5. Baselines: `screenshot.diff {baselinePath,currentPath,outputDir,expectedText?,expectedVisual?}`;
   read its `textAnalysis` (OCR optional via `vision.install-ocr {confirm:true}`
   - ask permission first).
6. Mismatch -> focused fix -> screenshot again. Loop until match.
7. Port busy (`PREVIEW_PORT_IN_USE`) -> pick another port or shoot the running
   preview with `{baseUrl:"http://127.0.0.1:<port>", path:"/"}`.

## 5. Quality gates & publish

- `audit {"scopes":["accessibility","seo"]}` (+security/performance) per page.
- `publish {"target":"production"|"staging"}`; domain CRUD+verify; unpublish;
  publish job status checks.
- Report upstream friction via `report-issue {...}` (structured) or the Discord
  #help template - always redacting secrets.

## 6. Native MCP client registration (optional)

Only when persistent client integration is explicitly wanted:
`npx webstudio connect claude|codex|cursor|vscode` (use `--print` to inspect
without changing config; follow client reload instructions).

## Error-code cheat sheet

| Code | Meaning | Action |
|---|---|---|
| `PROJECT_SESSION_BUSY` | another CLI/MCP owns session | wait, serialize calls |
| `CHECKPOINT_REQUIRED` | mutation gated behind report+ack | report, `checkpoint.ack` |
| `AMBIGUOUS_MUTATION_RESULT` | committed mutation, unknown outcome | inspect project manually; never auto-replay |
| `PREVIEW_PORT_IN_USE` | port occupied | change port / use baseUrl |
| `SCREENSHOT_TIMEOUT` | capture timed out; browser session reset | retry; check wait strategy |
| `PREVIEW_ASSET_DOWNLOAD_FAILED` | asset fetch failed | restore network, retry |
