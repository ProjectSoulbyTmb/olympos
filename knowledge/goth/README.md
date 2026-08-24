# goth/ — Gothic culture corpus

`corpus.json` is the structured knowledge pack consumed by the DAEDALUS
`goth-oracle` blueprint and the VENUS `goth` plugin (see `assistant/plugins/goth.js`).

**Content policy (in-file, enforced):** cultural and aesthetic material only —
history, music, fashion, and academic summaries of mature themes as *fashion
history / sociology*. No sexualized content of anyone; nothing erotic;
mature aesthetics apply to adult-coded contexts only.

Sources synthesized: Wikipedia (Goth subculture, Batcave, Gothic fashion),
The Conversation (Spooner 2023), Vampire Freaks style guide, Dazed (2015),
Duke UP *Goth: Undead Subculture*, Gender & Society (Wilkins), Manchester
Gothic Studies (2018), Journal of Fashion Business (2013).

Regenerate mirrors after editing:
- `assistant/data/goth-corpus.json` (offline fallback for the plugin)
- embedded snapshot inside `daedalus/blueprints.py` (`GOTH_CORPUS_SNAPSHOT`)
