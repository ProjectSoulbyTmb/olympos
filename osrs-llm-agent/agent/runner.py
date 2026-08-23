import io
import re
import traceback
from contextlib import redirect_stdout

from game.world import BudgetExceeded, GameError

BLOCKED_NAMES = ("open", "exec", "eval", "compile", "__import__", "input",
                 "breakpoint", "globals", "locals", "vars", "getattr",
                 "setattr", "delattr")

METHOD_ACCESSORS = ("ticks_left", "skills", "inventory", "coins", "log",
                    "quest_status", "shop_prices", "shop_stock")


def auto_repair(code):
    for name in METHOD_ACCESSORS:
        code = re.sub(rf"\.({name})\b(?!\()", f".{name}()", code)
    return code


def run_snippet(code, game, forgiving=False):
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
                return False, buffer.getvalue(), "snippet must define: def run(game):"
            fn(game)
        return True, buffer.getvalue(), ""
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
