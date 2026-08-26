import os
import shutil

VERSION = "1.0.0"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
STATUS_FILE = os.path.join(BASE_DIR, "status.json")
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 47400

PY = os.environ.get(
    "OLYMPUS_PYTHON",
    r"C:\Users\Earth949\AppData\Local\Programs\Python\Python312\python.exe",
)
NODE = shutil.which("node") or "node"
CMD = os.environ.get("ComSpec", r"C:\Windows\system32\cmd.exe")

SINGLETON_JOBS = [
    {
        "name": "zeus-guardian",
        "args": [PY, "-m", "zeus.server"],
        "cwd": r"D:\olympos",
        "freshness": 900,
    },
    {
        "name": "hypnos-dreamworker",
        "args": [PY, "-m", "hypnos.daemon"],
        "cwd": r"D:\olympos",
        "freshness": 900,
    },
    {
        "name": "relay-bridge",
        "args": [PY, "-m", "relay", "watch", "--every", "60"],
        "cwd": r"D:\olympos",
        "freshness": 300,
    },
    {
        "name": "artemis-huntress",
        "args": [PY, "-m", "artemis", "--watch", "300"],
        "cwd": r"D:\olympos",
        "freshness": 900,
    },
    {
        "name": "poseidon-tide",
        "args": [PY, "-m", "poseidon", "--interval", "300", "watch"],
        "cwd": r"D:\olympos",
        "freshness": 900,
    },
    {
        "name": "kronos-governor",
        "args": [PY, "-m", "kronos"],
        "cwd": r"D:\olympos",
        "freshness": 900,
    },
    {
        "name": "hebe-scribe",
        "args": [PY, "-m", "hebe", "--interval", "300", "watch"],
        "cwd": r"D:\olympos",
        "freshness": 900,
    },
    {
        "name": "voltage-sentinel",
        "args": [PY, "sentinel.py"],
        "cwd": r"D:\VOLTAGE",
        "freshness": 1800,
    },
    {
        "name": "actions-runner",
        "args": [CMD, "/c", r"D:\actions-runner-soul\run.cmd"],
        "cwd": r"D:\actions-runner-soul",
        "cooldown": 60,
        "freshness": 3600,
    },
    {
        "name": "gaia-watch",
        "args": [NODE, "gaia.mjs", "pulse", "--watch", "--every", "15m"],
        "cwd": r"D:\olympos\gaia",
        "freshness": 1800,
    },
]

ONESHOT_JOBS = [
    {
        "name": "vulcan-auto",
        "args": [
            r"C:\Program Files\nodejs\node.exe",
            "scripts\\vulcan-auto.mjs", "--fix", "--build", "--expand",
        ],
        "cwd": r"D:\olympos\project---soul",
        "interval": 1800,
        "timeout": 1500,
    },
    {
        "name": "voltage-zeus",
        "args": [PY, r"zeus\cli.py"],
        "cwd": r"D:\VOLTAGE",
        "interval": 1800,
        "timeout": 600,
    },
    {
        "name": "persephone-guardian",
        "args": [PY, "-u", r"D:\olympos\persephone\persephone.py", "--once"],
        "cwd": r"D:\olympos\persephone",
        "interval": 300,
        "timeout": 240,
    },
    {
        "name": "ares-sweep",
        "args": [PY, "-m", "ares", "sweep", "--profile", "night"],
        "cwd": r"D:\olympos",
        "daily": "03:00",
        "timeout": 7200,
    },
]


def all_specs():
    return {j["name"]: j for j in SINGLETON_JOBS + ONESHOT_JOBS}
