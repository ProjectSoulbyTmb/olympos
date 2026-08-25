# HAVEN - the cumulative shared knowledge base of the three sisters

One SQLite brain that **VENUS**, **APHRODITE** and **RILEY** — and only
those three kernels — learn from. Built from live workspace sources so
the curriculum can never silently drift from reality; extensible for
future additions by design.

## Access law

Exactly three consumers, enforced twice:

1. **Capability tokens** — one secret per kernel, stored sha256-hashed
   in the DB and dropped as plain text into each kernel's private data
   dir (`assistant/data/haven.token`, `D:\aphrodite\data\haven.token`,
   `D:\riley\data\haven.token`). The server answers only requests whose
   `X-Haven-Token` hashes to an enabled consumer row; everyone else gets
   a 403 before seeing one byte of curriculum.
2. **Loopback bind** — `server.py` refuses any non-127.0.0.1 host at
   startup. HAVEN is not reachable off this machine even by accident.

Tokens survive rebuilds (kernels stay authenticated); `--rotate` re-mints.

## Build & run

```powershell
python haven\build_haven_db.py            # cumulative upsert build
python haven\build_haven_db.py --list     # what the sisters know
python haven\build_haven_db.py --rotate   # re-mint all tokens
python haven\server.py                    # 127.0.0.1:43910
```

Query:

```powershell
$t = Get-Content assistant\data\haven.token
curl.exe -s -H "X-Haven-Token: $t" "http://127.0.0.1:43910/search?q=controlnet"
```

## Adding knowledge (future additions)

```powershell
python haven\build_haven_db.py --add studio-suite "New feature X" `
    --body-file note.md --keywords "x,feature"
```

Code-side: extend `build_corpus()` in `build_haven_db.py` — cards carry
`source_path` + `source_sha256`, so the verify gate flags drift whenever
a source file changes underneath the curriculum.

## Curriculum today

| Domain | Contents |
|---|---|
| `studio-suite` | riley-studio engine API, generation kinds, model tiers & pulls |
| `roadmap` | the full studio-grade phase plan |
| `fleet` | sibling port map, Venus teacher-packet protocol |
| `kernels` | the shared registries+heart architecture all three run on |
| `house-rules` | loopback law, acceptable-use hard line, gates discipline |
| `culture` | goth corpus index (policy-safe pointer card) |

## Verify gate

```powershell
python verify_haven.py    # repo root; offline-safe; exit code = verdict
```
