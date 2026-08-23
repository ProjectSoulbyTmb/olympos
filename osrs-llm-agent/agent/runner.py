import ctypes
import io
import re
import threading
import time
import traceback
from contextlib import redirect_stdout

from game.world import BudgetExceeded, GameError

HARD_TIMEOUT_SECONDS = 60
NO_PROGRESS_SECONDS = 20

BLOCKED_NAMES = ("open", "exec", "eval", "compile", "__import__", "input",
                 "breakpoint", "globals", "locals", "vars", "getattr",
                 "setattr", "delattr")

METHOD_ACCESSORS = ("ticks_left", "skills", "inventory", "coins", "log",
                    "quest_status", "shop_prices", "shop_stock")


class StrategyTimeout(GameError):
    pass


def _inject_async_exception(thread_id, exc):
    ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(thread_id), ctypes.py_object(exc))

METHOD_ACCESSORS = ("ticks_left", "skills", "inventory", "coins", "log",
                    "quest_status", "shop_prices", "shop_stock")


def auto_repair(code):
    for name in METHOD_ACCESSORS:
        code = re.sub(rf"\.({name})\b(?!\()", f".{name}()", code)
    return code


def run_snippet(code, game, forgiving=False,
                hard_timeout=HARD_TIMEOUT_SECONDS,
                no_progress=NO_PROGRESS_SECONDS):  # noqa: C901
    """Execute a strategy snippet defining run(game). Returns (ok, output,
    error_text). The snippet cannot import modules or touch the filesystem;
    it only sees the SDK object."""
    builtins_source = (__builtins__.__dict__
                       if hasattr(__builtins__, "__dict__") else __builtins__)
    safe_builtins = {k: v for k, v in builtins_source.items()
                     if k not in BLOCKED_NAMES}
    module_globals = {
        "__builtins__": safe_builtins,
        "game": game,
        "range": range,
        "len": len,
        "min": min,
        "max": max,
        "abs": abs,
        "sum": sum,
        "sorted": sorted,
        "print": print,
    }
    buffer = io.StringIO()
    code = auto_repair(code)
    try:
        compiled = compile(code, "<strategy>", "exec")
    except SyntaxError as e:
        return False, "", f"SyntaxError: {e}"
    try:
        with redirect_stdout(buffer):
            exec(compiled, module_globals)
            fn = module_globals.get("run")
            if not callable(fn):
                return False, buffer.getvalue(), \
                    "snippet must define: def run(game):"
            worker = threading.get_ident()
            deadline = {"t": time.time()}
            stop_reason = {"v": "wall-clock guard"}
            last_tick = {"v": getattr(game._w, "tick", 0) if hasattr(
                game, "_w") else 0}

            def progress():
                inner = getattr(game, "_w", None)
                if inner is not None:
                    return getattr(inner, "tick", 0)
                try:
                    return game.ticks_left()
                except Exception:
                    return 0

            def guard():
                while True:
                    time.sleep(1)
                    tick_now = progress()
                    if tick_now != last_tick["v"]:
                        last_tick["v"] = tick_now
                        deadline["t"] = time.time()
                    if time.time() - deadline["t"] > no_progress or \
                            time.time() - start > hard_timeout:
                        stop_reason["v"] = (
                            "safeguard: strategy stopped ("
                            f"{no_progress}s no progress / "
                            f"{hard_timeout}s hard cap)")
                        _inject_async_exception(worker, StrategyTimeout)
                        return

            start = time.time()
            last_tick["v"] = progress()
            watcher = threading.Thread(target=guard, daemon=True)
            watcher.start()
            try:
                fn(game)
            finally:
                deadline["t"] = float("inf")
        return True, buffer.getvalue(), ""
    except StrategyTimeout:
        return True, buffer.getvalue(), stop_reason["v"]
    except BudgetExceeded:
        return True, buffer.getvalue(), ""
    except (GameError, KeyError) as e:
        if forgiving:
            note = f"stopped early on: {e}"
            return True, buffer.getvalue() + note, ""
        err = traceback.format_exc(limit=2)
        return False, buffer.getvalue(), err
    except Exception:
        err = traceback.format_exc(limit=3)
        return False, buffer.getvalue(), err
