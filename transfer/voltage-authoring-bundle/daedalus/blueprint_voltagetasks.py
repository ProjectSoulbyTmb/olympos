"""DAEDALUS blueprint: voltage-tasks - the mind-tier task installers.

Batch V8 mind tier. The scheduled-task installer for the learning
subfleet inside VOLTAGE, carrying the B6 hygiene law IN TEXT so it
is lintable before it ever runs:

  Naming law - every task name matches ^voltage-[a-z0-9-]+$; the
  Olympos convention of bare organ names never appears.
  Root law - all script paths derive from -VoltageRoot (default
  D:\\VOLTAGE); no absolute foreign roots.
  Boundary law - the installer text must not reference OneDrive, the
  frozen OneDrive checkout path, or the Olympos fleet at all; a leak
  is a gate red BEFORE installation, not an incident after.
  Staggered cadence - three weekly triggers (metis, argus, logia) at
  distinct hours, mirroring the fleet-learning sweep pattern.

The .ps1 ships as a woven artifact; its gate is a structural linter
so the proof needs no Task Scheduler and no elevation."""

import sys

INSTALLER = '''# Registers the VOLTAGE learning subfleet tasks.
# All work happens under -VoltageRoot; nothing references any other
# fleet or checkout. Idempotent via -Force re-registration.

param([string]$VoltageRoot = "D:\\VOLTAGE")

$ErrorActionPreference = "Stop"

$organDir = Join-Path $VoltageRoot "organ"
if (-not (Test-Path $organDir)) {
    throw "VOLTAGE organ directory missing: $organDir"
}

$tasks = @(
    @{ name = "voltage-metis";  file = "cycle_metis.ps1";
       day = "Sunday";    at = "03:15" },
    @{ name = "voltage-argus";  file = "cycle_argus.ps1";
       day = "Sunday";    at = "04:45" },
    @{ name = "voltage-logia";  file = "cycle_logia.ps1";
       day = "Sunday";    at = "06:05" }
)

foreach ($t in $tasks) {
    $scriptPath = Join-Path $organDir $t.file
    if (-not (Test-Path $scriptPath)) {
        throw "missing subfleet script: $scriptPath"
    }
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    $trigger = New-ScheduledTaskTrigger -Weekly `
        -DaysOfWeek $t.day -At $t.at
    Register-ScheduledTask -TaskName $t.name `
        -Action $action -Trigger $trigger -Force | Out-Null
    Write-Host "registered $($t.name) -> $($t.day) $($t.at)"
}

Write-Host "voltage learning subfleet armed under $VoltageRoot"
exit 0
'''

LINTER = '''"""Structural lint for the voltage task installer (no elevation)."""

import re
import sys

FORBIDDEN = ("onedrive", "default project", "olympos")
NAME_DEF_RE = re.compile(r'name\\s*=\\s*"(voltage-[a-z0-9-]+)"')


def lint(text):
    problems = []
    low = text.lower()
    for word in FORBIDDEN:
        if word in low:
            problems.append("boundary leak: %r present" % word)
    names = NAME_DEF_RE.findall(text)
    if len(names) != 3:
        problems.append("expected 3 subfleet tasks, found %d"
                        % len(names))
    times = set(re.findall(r'at\\s*=\\s*"(\\d\\d:\\d\\d)"', text))
    if len(times) != 3:
        problems.append("expected 3 staggered times, got %r"
                        % sorted(times))
    if "-DaysOfWeek" not in text or "-At " not in text:
        problems.append("weekly triggers missing")
    if "-DaysOfWeek $t.day" not in text:
        problems.append("trigger day not driven by task def")
    if "-VoltageRoot" not in text:
        problems.append("root param missing: -VoltageRoot")
    if "-TaskName $t.name" not in text:
        problems.append("registration loop not wired to task defs")
    return problems


def main():
    with open("register_voltage_learning_tasks.ps1",
              encoding="utf-8") as fh:
        text = fh.read()
    problems = lint(text)
    assert problems == [], problems

    # negative control: the linter itself must bite on a leak
    leaked = text.replace(
        '$organDir = Join-Path $VoltageRoot "organ"',
        '$organDir = Join-Path $VoltageRoot "organ"\\n'
        '# fallback: $env:USERPROFILE\\\\Documents\\\\Default Project')
    assert any("default project" in p for p in lint(leaked)), \\
        "linter missed a OneDrive-checkout leak"

    print("voltage-tasks gate green")
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def files():
    return {
        "register_voltage_learning_tasks.ps1": INSTALLER,
        "verify_voltagetasks.py": LINTER,
    }


FILES = files()
FILES_DEF = FILES

FAULTS = {
    # boundary leak injected into the installer -> forbidden-word rule
    # fires red (independent breaker)
    "olympus_leak": (
        "register_voltage_learning_tasks.ps1",
        '$tasks = @(',
        '# legacy fallback: ..\\\\..\\\\Documents\\\\Default Project'
        '\\n$tasks = @('),
}

BLUEPRINT = {
    "description": "VOLTAGE learning-subfleet task installers: "
                   "voltage-* naming, root confinement, boundary "
                   "hygiene lint",
    "files": FILES,
    "gate": [sys.executable, "verify_voltagetasks.py"],
    "faults": dict(FAULTS),
}
