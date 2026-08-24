---
name: ptah-workflow
triggers: ptah, plan, refactor, debug
---
How to work as PTAH inside this workspace:

1. Plan first: register steps with task_tracker and keep states current.
2. Prefer file_editor over shell rewrites; it refuses silent overwrites
   and ambiguous replacements on purpose.
3. Explore before editing: grep the workspace for existing patterns and
   follow them (this fleet values uniformity).
4. Prove your work: finish every code change by running the relevant
   realm gate via verify_gate (ptah changes -> realm ptah), then report
   the PASS line verbatim.
5. If an action is denied or confirmation is requested, do not retry it
   silently - explain the situation in your final answer instead.
6. Remember durable lessons with memory(remember); recall them at the
   start of similar tasks.
