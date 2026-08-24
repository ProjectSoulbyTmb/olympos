"""PTAH demo - an offline scripted mission used by `run --demo`.

Shows the full loop without any network: the scripted brain creates a
small report with the file editor, verifies the kernel gate, then
answers. Deterministic, fast, CI-safe.
"""

import json

from ptah import content


def demo_script():
    create = json_action("file_editor", {
        "op": "create", "path": "PTAH_DEMO.txt",
        "content": (
            f"ptah {content.VERSION} demo\n"
            "The craftsman god built this file without touching "
            "the network.\n")})
    tracker = json_action("task_tracker",
                          {"op": "add", "title": "demo mission"})
    answer = ("Demo complete: wrote PTAH_DEMO.txt and kept the plan in "
              "the task tracker. Configure PTAH_API_KEY to run a real "
              "brain.")
    return [json.dumps(tracker), json.dumps(create),
            json.dumps({"answer": answer})]


def json_action(tool, args):
    return {"action": {"tool": tool, "args": args}}
