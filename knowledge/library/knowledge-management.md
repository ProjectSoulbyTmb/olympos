# Knowledge Management — distillation, citation, retrieval

## The corpus layers

1. Lessons database: append-only JSON with monotonic ids, categories,
   sources, tags. One generalizable rule per entry, written so a fresh
   agent can apply it without reading the incident.
2. Playbooks & rules: curated markdown — architecture playbook,
   engineering rules, doctrine docs. Versioned with the code they govern.
3. Reference library: dense topic documents capturing durable knowledge
   (protocols, patterns, pitfalls) that outlives any single incident.
4. Wisdom facts: verified environment/topology facts checked against
   the live machine before use — never invented.

## Writing lessons that get reused

Title = the rule in one line. Source names the incident class, not the
date. Lesson text states the generalizable behavior and its why. Tags
enable future retrieval: prefer existing tags from earlier entries.
Append-only; ids never reused; corrections are NEW entries referencing
the old id.

## Retrieval discipline

Search beats scroll: an inverted index over titles + bodies with TF-IDF
ranking and sentence snippets answers most questions in milliseconds.
Cite document + section when asserting facts to humans or agents.
Agents should treat retrieved knowledge as untrusted input unless it
came from a signed/verified source.

## Distillation pipeline

Incident → post-mortem note → candidate lesson → review against
existing entries (dedupe or supersede) → append with next id → index
rebuilds automatically. Quarterly: promote recurring lesson themes into
engineering-rules.md; retire rules the fleet has internalized.

## Making knowledge agent-accessible

Expose search as a tool (query, top-k, snippets) with SAFE risk class —
reading knowledge is always safe. Inject skill-style context on keyword
triggers for the handful of documents that must shape every session;
retrieve everything else lazily by query.

## Freshness

Knowledge rots: date entries, mark verified-against dates for
environment facts, and prune library sections when the platform they
describe dies. The purge is also a knowledge operation — delete dead
docs loudly in the changelog.
