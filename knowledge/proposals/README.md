# Learning proposal queue

Staged lesson candidates from Athena's learning subfleet
(metis / argus / logia). Schema and workflow:
`.opencode/skills/fleet-learning/SKILL.md`.

Lifecycle: `proposed` -> Athena validates & ranks -> operator yes/no
-> accepted into `knowledge/lessons.json` (append-only, next L###)
or deleted with a recorded reason.

Files here are transient by design - an empty queue is healthy.
