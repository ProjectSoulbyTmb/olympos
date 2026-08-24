"""PTAH security - risk classification, confirmation policy, grants.

Every tool action passes through the RiskAnalyzer before execution:

  SAFE        routine local work (read a file, echo, list a directory)
  ELEVATED    allowed but consequential (network fetch, package install)
  DESTRUCTIVE destructive or irreversible (recursive delete, force push)
  DENIED      never executable; confirmation cannot override

The ConfirmationPolicy decides what happens above SAFE:
  auto           run everything not DENIED
  confirm-risky  DESTRUCTIVE waits for explicit user confirmation
  confirm-all    DESTRUCTIVE and ELEVATED wait for confirmation

Risk classes map onto the house grant ladder: L0 read-only, L1 standing
grant, L2 elevated (see DESIGN.md "fail safe").
"""

import re

SAFE = "SAFE"
ELEVATED = "ELEVATED"
DESTRUCTIVE = "DESTRUCTIVE"
DENIED = "DENIED"

GRANT_CLASS = {                  # Yggdrasil grant ladder mapping
    SAFE: "L0",
    ELEVATED: "L1",
    DESTRUCTIVE: "L2",
    DENIED: "DENY",
}

POLICY_AUTO = "auto"
POLICY_CONFIRM_RISKY = "confirm-risky"
POLICY_CONFIRM_ALL = "confirm-all"
POLICIES = (POLICY_AUTO, POLICY_CONFIRM_RISKY, POLICY_CONFIRM_ALL)


class Verdict:
    """Outcome of classifying one action."""

    __slots__ = ("risk", "reason", "needs_confirmation", "allowed")

    def __init__(self, risk, reason="", needs_confirmation=False,
                 allowed=True):
        self.risk = risk
        self.reason = reason
        self.needs_confirmation = needs_confirmation
        self.allowed = allowed

    @property
    def grant(self):
        return GRANT_CLASS[self.risk]

    def to_dict(self):
        return {"risk": self.risk, "reason": self.reason,
                "needs_confirmation": self.needs_confirmation,
                "allowed": self.allowed, "grant": self.grant}

    def __repr__(self):
        return (f"Verdict({self.risk}, confirm={self.needs_confirmation}, "
                f"allowed={self.allowed}, reason={self.reason!r})")


def _compile(rules):
    return [(re.compile(pattern, re.IGNORECASE), why)
            for pattern, why in rules]


class RiskAnalyzer:
    """Regex rule table over the rendered action (tool + args)."""

    def __init__(self, deny=None, destructive=None, elevated=None):
        # content.py defaults; tests may inject focused tables.
        from ptah import content
        self.deny = _compile(deny if deny is not None else content.DENY_RULES)
        self.destructive = _compile(
            destructive if destructive is not None
            else content.DESTRUCTIVE_RULES)
        self.elevated = _compile(
            elevated if elevated is not None else content.ELEVATED_RULES)

    def render(self, tool_name, args):
        parts = [str(tool_name)]
        for key in sorted(args):
            parts.append(f"{key}={args[key]}")
        return "\n".join(parts)

    def classify(self, tool_name, args):
        text = self.render(tool_name, args)
        for rx, why in self.deny:
            if rx.search(text):
                return Verdict(DENIED, why, allowed=False)
        for rx, why in self.destructive:
            if rx.search(text):
                return Verdict(DESTRUCTIVE, why)   # confirmation decided by policy
        for rx, why in self.elevated:
            if rx.search(text):
                return Verdict(ELEVATED, why)
        return Verdict(SAFE, "")


class ConfirmationPolicy:
    """Decides which verdicts need a human yes before execution."""

    def __init__(self, name=POLICY_CONFIRM_RISKY):
        if name not in POLICIES:
            raise ValueError(f"unknown policy: {name!r}")
        self.name = name

    def apply(self, verdict):
        if not verdict.allowed:
            return False                       # denied stays denied
        if verdict.risk == SAFE:
            return False
        if verdict.risk == DESTRUCTIVE:
            return True                        # always gated under every policy
        if verdict.risk == ELEVATED:
            return self.name == POLICY_CONFIRM_ALL
        return False
