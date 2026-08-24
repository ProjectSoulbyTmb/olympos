"""PTAH workspace - the scoped execution environment.

A Workspace is the only filesystem surface an agent may touch. Every
path a tool receives resolves through this module, which refuses
absolute paths, drive letters, UNC shares and `..` climbs that would
leave the root. Fail-safe by construction.
"""

import os


class PathEscape(ValueError):
    """Raised when a requested path leaves the workspace root."""


class SizeLimit(OSError):
    """Raised when a file operation exceeds content.FILE_SIZE_CAP."""


def _is_within(root, candidate):
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


class LocalWorkspace:
    """Filesystem sandbox rooted at an absolute directory."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        if not os.path.isdir(self.root):
            os.makedirs(self.root, exist_ok=True)

    # ---------------------------------------------------------- resolving
    def resolve(self, rel):
        """Resolve a workspace-relative path; raise PathEscape on tricks."""
        if not isinstance(rel, str) or not rel.strip():
            raise PathEscape("empty path")
        norm = rel.replace("\\", "/").strip()
        if norm.startswith(("/", "~")):
            raise PathEscape(f"absolute paths rejected: {rel!r}")
        if len(norm) > 1 and norm[1] == ":":
            raise PathEscape(f"drive-letter paths rejected: {rel!r}")
        if any(part == ".." for part in norm.split("/")):
            raise PathEscape(f"path climbing rejected: {rel!r}")
        candidate = os.path.abspath(os.path.join(self.root, *norm.split("/")))
        root_lower = self.root.lower()
        cand_lower = candidate.lower()
        if not (cand_lower == root_lower
                or cand_lower.startswith(root_lower + os.sep)):
            raise PathEscape(f"path escapes workspace: {rel!r}")
        return candidate

    def relpath(self, absolute):
        return os.path.relpath(absolute, self.root).replace(os.sep, "/")

    # ------------------------------------------------------------ io ops
    def exists(self, rel):
        return os.path.exists(self.resolve(rel))

    def read_file(self, rel, max_bytes=None):
        from ptah import content
        cap = max_bytes or content.FILE_SIZE_CAP
        path = self.resolve(rel)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"not a file: {rel}")
        size = os.path.getsize(path)
        if size > cap:
            raise SizeLimit(f"{rel} is {size} bytes (cap {cap})")
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def write_file(self, rel, text, overwrite=True):
        from ptah import content
        blob = text.encode("utf-8")
        if len(blob) > content.FILE_SIZE_CAP:
            raise SizeLimit(
                f"write of {len(blob)} bytes exceeds cap "
                f"{content.FILE_SIZE_CAP}")
        path = self.resolve(rel)
        if os.path.exists(path) and not overwrite:
            raise FileExistsError(f"refusing to overwrite: {rel}")
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return {"path": rel, "bytes": len(blob)}

    def list_dir(self, rel=""):
        base = self.resolve(rel) if rel else self.root
        if not os.path.isdir(base):
            raise NotADirectoryError(f"not a directory: {rel!r}")
        out = []
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            kind = "dir" if os.path.isdir(full) else "file"
            size = os.path.getsize(full) if kind == "file" else None
            out.append({"name": self.relpath(full), "kind": kind,
                        "size": size})
        return out

    def walk_files(self, skip_dirs=("__pycache__", ".git", "node_modules")):
        """Yield workspace-relative file paths, stable order."""
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in skip_dirs)
            for name in sorted(filenames):
                yield self.relpath(os.path.join(dirpath, name))
