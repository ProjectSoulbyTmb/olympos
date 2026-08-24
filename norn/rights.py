"""NORN HEIMDALL-Rights: capability profiles (Mach send-right model).

A session holds rights, not the SDK. Rights are checked at dispatch,
server-side; clients only ever see what they may call. Default profile
"player" reproduces legacy behavior exactly, so old clients are
unaffected.
"""

PROFILES = {
    # Yggdrasil realm. "player" == everything except administration,
    # which is exactly what pre-NORN connections could do.
    "player": frozenset({"state", "chat", "docs", "live", "status",
                         "trade", "action"}),
    # Read-only observers: dashboards, Heimdall panels.
    "watcher": frozenset({"state", "live", "status"}),
    # LLM/strategy sessions: introspection only until escalated.
    "agent": frozenset({"state", "docs", "live", "status"}),
    # Escalated agent: may act on the world.
    "agent_rw": frozenset({"state", "docs", "live", "status", "action"}),
    # Administration: grant/escalation management.
    "admin": frozenset({"state", "chat", "docs", "live", "status",
                        "trade", "action", "grant"}),
}

DEFAULT_PROFILE = "player"
GRANT_RIGHT = "grant"

# Vulcan realm profiles: operator == today's full surface, watcher ==
# read-only dashboard. host.py gates mutating verbs against these.
VULCAN_INFO = frozenset({
    "ping", "state", "zones", "zone", "devices", "device", "rules",
    "alerts", "events", "stats", "diagnose", "warden"})
VULCAN_PROFILES = {
    "operator": None,   # None == every verb in VulcanSDK._VALID
    "watcher": VULCAN_INFO,
}
VULCAN_DEFAULT_PROFILE = "operator"

# Zeus realm: protection verbs are high-stakes (bolts, policy), so the
# read-only surface stays wide but mutation stays operator-only.
ZEUS_INFO = frozenset({
    "ping", "status", "diagnose", "events", "repairs", "procs",
    "quarantine_list", "policy_get", "baseline_verify"})
ZEUS_MUTATING = frozenset({
    "patrol", "baseline_build", "watch_pid", "unwatch_pid",
    "bolt_kill", "quarantine_restore", "policy_set"})
ZEUS_PROFILES = {
    "operator": None,   # None == every verb in ZeusSDK._VALID
    "watcher": ZEUS_INFO,
}
ZEUS_DEFAULT_PROFILE = "operator"


def profile_names():
    return sorted(PROFILES)


def grant(profile):
    """-> frozenset of rights for a profile name."""
    if profile not in PROFILES:
        raise ValueError(
            f"unknown profile '{profile}' (valid: {profile_names()})")
    return PROFILES[profile]


def allows(rights, right):
    return right in rights


def can_narrow(current_allowed, new_allowed):
    """assume may only ever narrow access. None means 'all verbs'.
    (Escalation goes through the audited grant verb instead.)"""
    if new_allowed is None:
        return False
    if current_allowed is None:
        return True
    return new_allowed <= current_allowed
