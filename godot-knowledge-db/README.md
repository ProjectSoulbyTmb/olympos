# godot-knowledge-db

A local SQLite knowledge database built from the public Godot Engine
website ([godotengine.org](https://godotengine.org)) - site pages, blog
articles, release announcements, sponsors - with a full-text (FTS5)
search index across everything.

The `.db` artifact is a **local build product** (gitignored): only the
tooling ships through git. Rebuild it any time; every run is a full
clean rebuild.

## Setup

Standard library for querying/verifying; crawling needs two third-party
packages (declared as optional deps in `requirements.txt`):

```powershell
python -m pip install requests beautifulsoup4
```

## Build

```powershell
python godot-knowledge-db/build_godot_db.py
# options: --db PATH  --delay 0.35  --article-limit 60  --blog-pages 6
```

Polite crawler: ~0.35 s between requests, bounded article count.

## Query

```powershell
python godot-knowledge-db/query_godot_db.py search "gdscript typed arrays"
python godot-knowledge-db/query_godot_db.py articles 4.5
python godot-knowledge-db/query_godot_db.py releases
python godot-knowledge-db/query_godot_db.py pages
python godot-knowledge-db/query_godot_db.py sponsors
python godot-knowledge-db/query_godot_db.py stats
```

`search` runs an FTS5 phrase query over page sections and full article
bodies, returning ranked snippets plus source URLs.

## Schema

| Table           | Contents                                                        |
|-----------------|-----------------------------------------------------------------|
| `pages`         | every crawled site page (url, title, description, category)     |
| `sections`      | heading-delimited content blocks per page                       |
| `articles`      | full blog articles (title, date, author, tags, excerpt, body)   |
| `links`         | outbound links per page *and* per article                       |
| `releases`      | engine releases parsed from announcements (version/suffix/kind) |
| `sponsors`      | sponsor names + tiers from the homepage                         |
| `meta`          | crawl stats + provenance                                        |
| `knowledge_fts` | FTS5 index over sections + articles (`porter unicode61`)        |

## Gate

`verify_godot_knowledge_db.py` rides the shared safeguards gate
(auto-discovered). It is hermetic - no network - and always checks tool
integrity (compile, schema declaration, release classifier, FTS escaper);
when a locally built artifact exists it also checks data integrity
(meta-vs-table consistency, source-site provenance, version format,
non-empty FTS index).
