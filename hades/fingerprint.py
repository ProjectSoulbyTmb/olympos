"""HADES fingerprint engine - structural AST hashes that survive rebranding.

Two hashes per code unit:

strict - shape + literal constants. Catches copy-paste theft where only
         identifiers were renamed.
loose  - shape only. Catches heavier disguises where strings/numbers were
         swapped out too (the classic rebrand).

Identifiers (variable/function/attribute/import names) are blanked in
both, so renaming a stolen function does not hide it. Fingerprints are
taken per top-level def/class plus the whole module, so a thief copying
a single function is still caught.
"""


import ast
import hashlib

IDENT_FIELDS = frozenset({"id", "name", "arg", "attr", "module", "asname", "names"})
SKIP_FIELDS = frozenset(
    {"lineno", "col_offset", "end_lineno", "end_col_offset", "type_comment"}
)

MIN_STRICT_NODES = 6
MIN_LOOSE_NODES = 12
MAX_LOOSE_REFS = 4


def _shape(node, consts):
    kind = type(node).__name__
    fields = []
    for key, val in ast.iter_fields(node):
        if key in SKIP_FIELDS:
            continue
        if key in IDENT_FIELDS:
            fields.append((key, ""))
            continue
        if isinstance(node, ast.Constant) and key == "value":
            fields.append((key, repr(val) if consts else ""))
            continue
        fields.append((key, _value(val, consts)))
    return (kind, tuple(fields))


def _value(val, consts):
    if val is None:
        return None
    if isinstance(val, ast.AST):
        return _shape(val, consts)
    if isinstance(val, (list, tuple)):
        return tuple(_value(x, consts) for x in val)
    if isinstance(val, str):
        return val
    return repr(val)


def _digest(shape):
    return hashlib.sha256(repr(shape).encode("utf-8")).hexdigest()[:32]


def _count(node):
    return sum(1 for _ in ast.walk(node))


def unit_fingerprints(source):
    """Return [(symbol, strict_fp, loose_fp, node_count)].

    Symbols keep their original names for human-readable evidence;
    the fingerprints themselves are name-blind.
    """
    tree = ast.parse(source)
    units = [
        (
            "<module>",
            _digest(_shape(tree, True)),
            _digest(_shape(tree, False)),
            _count(tree),
        )
    ]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            units.append(
                (
                    node.name,
                    _digest(_shape(node, True)),
                    _digest(_shape(node, False)),
                    _count(node),
                )
            )
    return units
