"""PTAH skills - reusable knowledge cards injected by keyword trigger.

A skill is a markdown file with a tiny frontmatter header:

    ---
    name: Olympos-conventions
    triggers: Olympos, realm, gate, verify
    ---

    Body text injected into the system prompt when any trigger appears.

No YAML dependency: frontmatter is strict `key: value` lines between
`---` fences. Unknown keys are ignored; missing name falls back to the
filename. Skills are knowledge only - they never carry code.
"""

import os
from dataclasses import dataclass, field


@dataclass
class Skill:
    name: str
    triggers: list = field(default_factory=list)
    body: str = ""
    source: str = ""

    def matches(self, text):
        low = text.lower()
        return any(t and t in low for t in self.triggers)


def parse_skill(text, source=""):
    """Parse one skill card; raises ValueError on malformed structure."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{source}: missing frontmatter opening '---'")
    try:
        close = next(i for i in range(1, len(lines))
                     if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError(f"{source}: unterminated frontmatter") from None
    meta = {}
    for line in lines[1:close]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"{source}: bad frontmatter line {line!r}")
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip()
    name = meta.get("name") or (
        os.path.splitext(os.path.basename(source))[0] if source else "")
    if not name:
        raise ValueError(f"{source}: skill needs a name")
    triggers = [t.strip().lower()
                for t in re_split(meta.get("triggers", "")) if t.strip()]
    body = "\n".join(lines[close + 1:]).strip()
    if not body:
        raise ValueError(f"{source}: empty skill body")
    return Skill(name=name, triggers=triggers, body=body, source=source)


def re_split(raw):
    return [chunk for chunk in raw.replace(";", ",").split(",")]


def load_skills(*dirs):
    """Load every *.md card from the given dirs (first wins per name)."""
    skills = {}
    for directory in dirs:
        if not directory or not os.path.isdir(directory):
            continue
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".md"):
                continue
            path = os.path.join(directory, fname)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    skill = parse_skill(fh.read(), source=path)
            except ValueError:
                continue                    # malformed cards never crash runs
            skills.setdefault(skill.name, skill)
    return list(skills.values())


def select_skills(skills, text):
    """Return triggered skills in stable order."""
    return [s for s in skills if s.matches(text)]


def render_block(skills):
    """Render matched skills as a system-prompt appendix."""
    if not skills:
        return ""
    chunks = ["# Relevant skills"]
    for s in skills:
        chunks.append(f"## {s.name}\n{s.body}")
    return "\n\n".join(chunks)
