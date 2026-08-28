"""ptah.vscode_workspace - safe, generated VS Code workspace integration.

Generates ``.vscode/tasks.json`` and ``.vscode/settings.json`` describing
every PTAH-supported local LLM backend alias (ollama, vllm, lmstudio,
llama.cpp/llamacpp, litellm, openai-compatible) plus tasks that invoke the
existing ``ptah probe``, ``ptah benchmark``, and ``ptah deploy-check``
commands. This module never talks to a backend or server itself.

Design goals mirror the rest of PTAH:

- stdlib only, no third-party dependencies.
- no network activity: generation and validation only read the process
  environment and read/write local JSON files through
  ``ptah.workspace.LocalWorkspace``, which confines every write to the
  target directory and refuses ``..`` climbs, absolute paths, and
  drive-letter/UNC escapes.
- deterministic, inspectable output; existing files are left untouched
  unless the caller explicitly opts into overwriting them.
- this integration is strictly for locally hosted, OpenAI-compatible LLM
  backends. It does not alter, probe, or make any claim about GitHub
  Copilot, and it does not claim unlimited compute or universal zero cost:
  local backends still require capable hardware, still have per-model
  license terms, and still consume time/electricity even though they avoid
  metered per-token API charges for the requests they serve.
"""

import json
import os
from urllib.parse import urlparse

from ptah.llm import LOCAL_ENV_TAGS, LOCAL_PROVIDER_DEFAULTS, normalize_provider
from ptah.workspace import LocalWorkspace

# Canonical alias order mirrors ptah.llm.LOCAL_PROVIDER_DEFAULTS.
SUPPORTED_BACKENDS = (
    "ollama", "vllm", "lmstudio", "llamacpp", "litellm", "openai-compatible",
)

BACKEND_LABELS = {
    "ollama": "Ollama",
    "vllm": "vLLM",
    "lmstudio": "LM Studio",
    "llamacpp": "llama.cpp",
    "litellm": "LiteLLM",
    "openai-compatible": "OpenAI-compatible",
}

TASKS_SCHEMA_VERSION = "2.0.0"
TASKS_FILE = ".vscode/tasks.json"
SETTINGS_FILE = ".vscode/settings.json"

REQUIRED_TASK_LABELS = (
    "PTAH: Benchmark (selected backends)",
    "PTAH: Deploy Check",
)


def _normalize_backends(backends=None):
    """Validate and de-duplicate requested aliases; default to all of them."""
    if not backends:
        return list(SUPPORTED_BACKENDS)
    selected = []
    for item in backends:
        alias = normalize_provider(item)
        if alias not in LOCAL_PROVIDER_DEFAULTS:
            raise ValueError(f"unsupported local backend: {item!r}")
        if alias not in selected:
            selected.append(alias)
    return selected


def _is_loopback_url(url):
    """Conservative loopback check used only to flag drifted defaults."""
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return False
    return host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def backend_descriptor(alias):
    """Resolve one local backend's endpoint/model/env names.

    Reads only ``os.environ`` (no I/O, no network) so a caller can preview
    what a generated workspace would contain before anything is written.
    """
    alias = normalize_provider(alias)
    if alias not in LOCAL_PROVIDER_DEFAULTS:
        raise ValueError(f"unsupported local backend: {alias!r}")
    default_url, default_model = LOCAL_PROVIDER_DEFAULTS[alias]
    tag = LOCAL_ENV_TAGS[alias]
    env = os.environ.get
    env_url = f"PTAH_{tag}_URL"
    env_model = f"PTAH_{tag}_MODEL"
    env_api_key = f"PTAH_{tag}_API_KEY"
    base_url = (env(env_url) or env(f"PTAH_{tag}_BASE_URL")
                or env(f"PTAH_{tag}_ENDPOINT") or default_url)
    model = env(env_model) or default_model
    return {
        "alias": alias,
        "label": BACKEND_LABELS[alias],
        "base_url": base_url,
        "model": model,
        "env_url": env_url,
        "env_model": env_model,
        "env_api_key": env_api_key,
        "endpoint_is_loopback": _is_loopback_url(base_url),
    }


def build_settings(backends=None):
    """Return the JSON-serializable ``.vscode/settings.json`` payload."""
    selected = _normalize_backends(backends)
    entries = {}
    for alias in selected:
        d = backend_descriptor(alias)
        entries[alias] = {
            "label": d["label"],
            "baseUrl": d["base_url"],
            "model": d["model"],
            "envUrl": d["env_url"],
            "envModel": d["env_model"],
            "envApiKey": d["env_api_key"],
        }
    return {
        "ptah.localLLM.backends": entries,
        "ptah.localLLM.selected": selected,
        "ptah.localLLM.defaultBackend": selected[0] if selected else "",
    }


def _probe_task(descriptor):
    return {
        "label": f"PTAH: Probe ({descriptor['label']})",
        "type": "shell",
        "command": "python",
        "args": ["-m", "ptah", "probe",
                 "--base-url", descriptor["base_url"],
                 "--model", descriptor["model"], "--json"],
        "group": "test",
        "problemMatcher": [],
        "presentation": {"reveal": "always", "panel": "shared"},
        "detail": (f"Local-only probe of the {descriptor['label']} "
                   "OpenAI-compatible endpoint; no external network access."),
    }


def _benchmark_task(descriptors):
    args = ["-m", "ptah", "benchmark"]
    for d in descriptors:
        args += ["--backend", f"{d['alias']}={d['model']}@{d['base_url']}"]
    args += ["--runs", "1", "--json"]
    return {
        "label": "PTAH: Benchmark (selected backends)",
        "type": "shell",
        "command": "python",
        "args": args,
        "group": "test",
        "problemMatcher": [],
        "presentation": {"reveal": "always", "panel": "shared"},
        "detail": ("Repeatable local compatibility check across the "
                   "selected backend aliases; loopback endpoints only."),
    }


def _deploy_check_task():
    return {
        "label": "PTAH: Deploy Check",
        "type": "shell",
        "command": "python",
        "args": ["-m", "ptah", "deploy-check", "--host", "127.0.0.1", "--json"],
        "group": "test",
        "problemMatcher": [],
        "presentation": {"reveal": "always", "panel": "shared"},
        "detail": ("Validates server exposure/auth/TLS configuration; "
                   "performs no network probing."),
    }


def build_tasks(backends=None):
    """Return the JSON-serializable ``.vscode/tasks.json`` payload."""
    selected = _normalize_backends(backends)
    descriptors = [backend_descriptor(alias) for alias in selected]
    tasks = [_probe_task(d) for d in descriptors]
    tasks.append(_benchmark_task(descriptors))
    tasks.append(_deploy_check_task())
    return {"version": TASKS_SCHEMA_VERSION, "tasks": tasks}


def generate_workspace(root, backends=None, force=False,
                       write_settings=True, write_tasks=True):
    """Write ``.vscode/tasks.json`` and ``.vscode/settings.json`` under ``root``.

    Writes go through ``ptah.workspace.LocalWorkspace`` so they are confined
    to ``root`` and cannot escape it. No network access occurs. An existing
    file is left untouched (recorded under ``skipped``) unless ``force`` is
    set, so re-running generation is safe by default.
    """
    selected = _normalize_backends(backends)
    ws = LocalWorkspace(root)
    written = []
    skipped = []
    if write_tasks:
        payload = json.dumps(build_tasks(selected), indent=2) + "\n"
        if not force and ws.exists(TASKS_FILE):
            skipped.append(TASKS_FILE)
        else:
            ws.write_file(TASKS_FILE, payload)
            written.append(TASKS_FILE)
    if write_settings:
        payload = json.dumps(build_settings(selected), indent=2) + "\n"
        if not force and ws.exists(SETTINGS_FILE):
            skipped.append(SETTINGS_FILE)
        else:
            ws.write_file(SETTINGS_FILE, payload)
            written.append(SETTINGS_FILE)
    return {"root": ws.root, "backends": selected,
            "written": written, "skipped": skipped}


def validate_workspace(root):
    """Re-parse generated files and check their shape.

    Never executes a task and never contacts a network endpoint; this is a
    static, offline structural check only.
    """
    ws = LocalWorkspace(root)
    errors = []
    warnings = []

    if ws.exists(TASKS_FILE):
        try:
            data = json.loads(ws.read_file(TASKS_FILE))
        except (ValueError, OSError) as exc:
            errors.append(f"{TASKS_FILE}: invalid JSON ({exc})")
            data = None
        if data is not None:
            if data.get("version") != TASKS_SCHEMA_VERSION:
                errors.append(f"{TASKS_FILE}: unexpected version "
                             f"{data.get('version')!r}")
            tasks = data.get("tasks")
            if not isinstance(tasks, list) or not tasks:
                errors.append(f"{TASKS_FILE}: no tasks defined")
            else:
                labels = {t.get("label") for t in tasks if isinstance(t, dict)}
                for required in REQUIRED_TASK_LABELS:
                    if required not in labels:
                        errors.append(f"{TASKS_FILE}: missing task {required!r}")
                if not any(str(label).startswith("PTAH: Probe")
                          for label in labels):
                    errors.append(f"{TASKS_FILE}: no probe task defined")
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    for value in (task.get("args") or []):
                        if (isinstance(value, str) and value.startswith("http")
                                and not _is_loopback_url(value)):
                            warnings.append(
                                f"{TASKS_FILE}: task {task.get('label')!r} "
                                "references a non-loopback endpoint")
    else:
        errors.append(f"{TASKS_FILE}: not found")

    if ws.exists(SETTINGS_FILE):
        try:
            data = json.loads(ws.read_file(SETTINGS_FILE))
        except (ValueError, OSError) as exc:
            errors.append(f"{SETTINGS_FILE}: invalid JSON ({exc})")
            data = None
        if data is not None:
            backends = data.get("ptah.localLLM.backends")
            if not isinstance(backends, dict) or not backends:
                errors.append(f"{SETTINGS_FILE}: no backends configured")
            else:
                for alias, entry in backends.items():
                    if alias not in LOCAL_PROVIDER_DEFAULTS:
                        errors.append(f"{SETTINGS_FILE}: unsupported "
                                      f"backend {alias!r}")
                    elif not isinstance(entry, dict) or not entry.get("baseUrl"):
                        errors.append(f"{SETTINGS_FILE}: backend {alias!r} "
                                      "is missing baseUrl")
    else:
        errors.append(f"{SETTINGS_FILE}: not found")

    return {"root": ws.root, "ok": not errors,
            "errors": errors, "warnings": warnings}
