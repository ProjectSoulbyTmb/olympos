import logging
import os
from logging.handlers import RotatingFileHandler

from . import config

_loggers = {}


def setup():
    os.makedirs(config.LOG_DIR, exist_ok=True)
    return get_logger("orchestrator")


def get_logger(name):
    if name in _loggers:
        return _loggers[name]
    lg = logging.getLogger(f"olympus.{name}")
    lg.setLevel(logging.INFO)
    h = RotatingFileHandler(
        os.path.join(config.LOG_DIR, f"{name}.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    lg.addHandler(h)
    lg.propagate = False
    _loggers[name] = lg
    return lg


def log_path(name):
    return os.path.join(config.LOG_DIR, f"{name}.log")


def log_mtime(name):
    try:
        return os.path.getmtime(log_path(name))
    except OSError:
        return None
