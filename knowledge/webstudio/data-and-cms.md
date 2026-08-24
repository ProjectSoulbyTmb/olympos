# Webstudio Data Layer & CMS Patterns

*Source: docs.webstudio.is foundations/cms.md, content-engine, variables.*

## Mental model

Webstudio has **no built-in CMS**. It is backend-agnostic: three primitives
turn any HTTP API into site content.

1. **Dynamic pages** - one page template whose path carries params
   (`/blog/:slug`, optional `:slug?`, wildcard `/*`).
2. **Resources** - fetch variables: REST, GraphQL, or system resources.
3. **Bindings** - Expression editor maps resource data onto ANY component
   field (text, props, meta title, status code, show conditions).

Param values arrive in expressions as `system.params.slug`. The Builder's
Address Bar takes test param values for previewing.

## Resource patterns

```jsonc
// REST with expression-driven auth + params
{
  "name": "Posts",
  "method": "get",
  "url": "https://api.example.com/posts",
  "searchParams": [
    {"name":"tag","value":"filters.tag"},
    {"name":"page","value":"(filters.page ?? 1).toString()"}
  ],
  "headers": [
    {"name":"Authorization","value":"\"Bearer \" + auth.token"}
  ]
}
```

- GraphQL: `control:"graphql"`, POST body template, variables from
  `system.params.*`.
- System resources: `/ $resources/current-date`, sitemap, assets.
- Data variables (string/number/boolean/JSON) hold local state, scoped per
  instance; `filters` object pattern drives search/filter UIs.

## Dynamic 404 pattern (do this on every dynamic page)

Bind **Page Settings > Status Code**: `` cmsData.data[0].id ? 200 : 404 ``

Then EITHER:

- conditional blocks - 404 box `Show = !cmsData.data[0].id`, content box
  `Show = cmsData.data[0].id`; reuse a shared design via Slot sourced from the
  custom 404 page; OR
- redirect - bind Page Settings > Redirect to `!cmsData.data[0].id ? "/404" : ""`.

Never render empty shells for missing records - it leaks soft-404s into SEO.

## Content Engine: backend-free blog from assets

Markdown/JSON **assets are queryable as a CMS** (`create-assets-resource`):

```jsonc
{
  "name": "Published posts",
  "query": {
    "result": "many",
    "where": { "all": [
      {"field":["extension"],"operator":"eq","value":{"type":"literal","value":"md"}},
      {"field":["properties","draft"],"operator":"ne","value":{"type":"literal","value":true}}
    ]},
    "sort": [{"field":["properties","publishedAt"],"direction":"desc"}],
    "limit": {"type":"literal","value":20},
    "output": {"mode":"fields","fields":[["properties","title"],["properties","slug"]]},
    "content": {"mode":"none"}          // list view: skip bodies
  }
}
```

Detail page: `result:"one"` + slug eq `system.params.slug` +
`content.mode:"markdown-body-ref"`.

Always `validate-asset-query` / `preview-asset-query` before committing.

## Rich text rules

- Render HTML rich text via **Content Embed**, Markdown via **Markdown Embed**.
- Verified-compatible backends: Hygraph, Contentful, WordPress, Drupal,
  Directus, Airtable, Baserow, Ghost, Flotiq, Hashnode.
- Known gaps: Sanity rich text NO; Notion pages broken (#3709); Strapi needs
  CKEditor HTML field; Payload needs an HTML-mirror field/hook; Coda multiple
  issues (#3708).
- Exotic formats -> proxy through a Cloudflare Worker that normalizes to HTML.

## Iterating data into UI

**Collection** component repeats its children per array item:
bind data to `Posts.data.items`, reference fields via the
`collectionItem.<field>` scope inside items. Pair with dynamic-page links
(`/blog/{{collectionItem.slug}}`) and sitemap generation via XML Node.

## Backend selection heuristics for our websystems

| Need | Pick |
|---|---|
| Zero-backend marketing/blog site | Content Engine (Markdown assets) |
| Structured records + forms | Airtable / Baserow / Supabase |
| Existing headless CMS | Hygraph / WordPress / Ghost |
| Internal tool frontend | Notion / Airtable over REST |

Full how-tos live under docs `/university/integrations/*` - re-fetch before
building a new integration type.
