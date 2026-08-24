"""Structural gate for the Godot output template (L0 in the ladder).

Validates the shipped template AND any generated copy pointed at via
--path. Does not require a Godot binary.

Run:  python templates/verify_template.py [--path <dir>]
Exit: 0 valid, 1 violations.
"""

import argparse
import configparser
import io
import os
import sys

REQUIRED_FILES = ("project.godot", "main.tscn", "main.gd", "README.md")


def check(path):
    problems = []
    for rel in REQUIRED_FILES:
        if not os.path.exists(os.path.join(path, rel)):
            problems.append(f"missing required file: {rel}")

    proj = os.path.join(path, "project.godot")
    if os.path.exists(proj):
        text = open(proj, encoding="utf-8").read()
        parser = configparser.ConfigParser(
            interpolation=None, strict=False)
        try:
            # godot files may carry keys before any [section]; give
            # them a home so INI parsing works.
            parser.read_string("[_preamble]\n" +
                               text.replace('PackedStringArray("4.3")',
                                            '"4.3"'))
            if not parser.has_section("application"):
                problems.append("project.godot missing [application]")
            else:
                main_scene = parser.get("application", "run/main_scene",
                                        fallback="").strip().strip('"')
                if not main_scene.startswith("res://"):
                    problems.append("run/main_scene must be res:// path")
        except configparser.Error as exc:
            problems.append(f"project.godot unparseable: {exc}")

    gd = os.path.join(path, "main.gd")
    if os.path.exists(gd):
        body = open(gd, encoding="utf-8").read()
        for needle, why in (
                ("_tick(", "fixed-tick entry point absent"),
                ("TICK_RATE", "tick-rate constant absent"),
                ("rng.seed", "seeded RNG discipline absent")):
            if needle not in body:
                problems.append(f"main.gd: {why}")
        if "_process(delta: float) -> void:" in body and \
                "accumulator" not in body:
            problems.append("main.gd: _process mutates without "
                            "accumulator pattern")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=os.path.dirname(
        os.path.abspath(__file__)) + "/godot-game")
    args = ap.parse_args()
    problems = check(args.path)
    print("verify_template")
    for p in problems:
        print(f"  FAIL  {p}")
    verdict = "VALID" if not problems else f"{len(problems)} violation(s)"
    print(f"template {args.path}: {verdict}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
