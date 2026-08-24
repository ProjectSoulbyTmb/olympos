"""DAEDALUS schema gates (VULCAN RIG pattern): a build spec either
parses against its shape or is refused with a precise error before
any guest is rented."""

SPEC_KINDS = ("build",)

REQUIRED_SPEC_KEYS = {"blueprint": str}
OPTIONAL_SPEC_KEYS = {
    "kind": str,
    "name": str,
    "faults": list,
    "attempts": int,
    "labels": list,
}
KNOWN_FAULTS = frozenset()


def validate_spec(spec, blueprint_names=()):
    """-> list[str]; empty == acceptable. Hard errors name the field."""
    if not isinstance(spec, dict):
        return [f"error: spec root is {type(spec).__name__}, "
                "expected object"]
    issues = []
    for key, want in REQUIRED_SPEC_KEYS.items():
        if key not in spec:
            issues.append(f"error: missing '{key}'")
        elif not isinstance(spec[key], want):
            issues.append(f"error: '{key}' is {type(spec[key]).__name__}"
                          f", expected {want.__name__}")
    if isinstance(spec.get("blueprint"), str) and blueprint_names \
            and spec["blueprint"] not in blueprint_names:
        issues.append(f"error: unknown blueprint "
                      f"'{spec['blueprint']}' (known: "
                      f"{', '.join(sorted(blueprint_names))})")
    for key, want in OPTIONAL_SPEC_KEYS.items():
        if key in spec and not isinstance(spec[key], want):
            issues.append(f"error: '{key}' is "
                          f"{type(spec[key]).__name__}, "
                          f"expected {want.__name__}")
    faults = spec.get("faults")
    if isinstance(faults, list):
        for f in faults:
            if not isinstance(f, str):
                issues.append("error: fault names must be strings")
    attempts = spec.get("attempts")
    if isinstance(attempts, int) and not 1 <= attempts <= 10:
        issues.append("error: 'attempts' must be within [1, 10]")
    return issues


def validate_rule(rule):
    """Build-policy rules mirror vulcan/rules.py grammar:
    {id, trigger:{type,...}, when:{kind,...}?, then:[{kind,...}],
     max_fires?, priority?}."""
    if not isinstance(rule, dict):
        return ["error: rule root must be an object"]
    issues = []
    if not isinstance(rule.get("id"), str):
        issues.append("error: rule.id must be a string")
    trig = rule.get("trigger")
    if not isinstance(trig, dict) or \
            trig.get("type") not in ("event", "tick"):
        issues.append("error: trigger.type must be event|tick")
    then = rule.get("then")
    if not isinstance(then, list) or not then:
        issues.append("error: then must be a non-empty list")
    else:
        for step in then:
            if not isinstance(step, dict) or \
                    step.get("kind") not in ACTION_KINDS:
                issues.append("error: action.kind must be one of: "
                              + ", ".join(sorted(ACTION_KINDS)))
                break
    mf = rule.get("max_fires")
    if mf is not None and (not isinstance(mf, int) or mf < 1):
        issues.append("error: max_fires must be a positive integer")
    pr = rule.get("priority")
    if pr is not None and not isinstance(pr, int):
        issues.append("error: priority must be an integer")
    return issues


ACTION_KINDS = frozenset({
    "retry_build",       # requeue the failed build (respects ceiling)
    "raise_timeout",     # add headroom to the lane's gate timeout
    "quarantine_blueprint",  # stop offering a failing design
    "alert",             # audit + ratatosk shout
})
