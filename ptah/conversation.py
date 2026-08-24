"""PTAH conversation - persistent event-sourced sessions.

A conversation is a directory under ptah/data/conversations/<id>/:

  events.jsonl   append-only typed event log (the source of truth)
  meta.json      id, status, workspace root, created timestamp

Statuses: idle -> running -> (waiting_confirmation) -> finished | error.
The log survives crashes; state is always replayable from events alone.
"""

import json
import os
import random
import threading
import time

from ptah import content, events


class Conversation:
    IDLE = "idle"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    FINISHED = "finished"
    ERROR = "error"

    def __init__(self, directory):
        self.dir = os.path.abspath(directory)
        self.events = []
        self.meta = {}
        self.lock = threading.RLock()
        self.pending_action = None       # (tool, args) awaiting confirmation

    # ------------------------------------------------------------ create
    @classmethod
    def new(cls, root=None, workspace_root=""):
        root = root or content.conversations_dir()
        cid = time.strftime("%Y%m%d-%H%M%S") + "-" + \
            "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789",
                                   k=6))
        conv_dir = os.path.join(root, cid)
        os.makedirs(conv_dir, exist_ok=True)
        conv = cls(conv_dir)
        conv.meta = {"id": cid,
                     "created": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                              time.gmtime()),
                     "status": cls.IDLE,
                     "workspace": workspace_root}
        conv._save_meta()
        return conv

    @classmethod
    def load(cls, directory):
        conv = cls(directory)
        path = os.path.join(conv.dir, "events.jsonl")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                conv.events = [events.deserialize(line)
                               for line in fh if line.strip()]
        meta_path = os.path.join(conv.dir, "meta.json")
        if os.path.isfile(meta_path):
            with open(meta_path, "r", encoding="utf-8") as fh:
                conv.meta = json.load(fh)
        else:
            conv.meta = {"id": os.path.basename(conv.dir),
                         "status": cls.IDLE, "created": "", "workspace": ""}
        last_confirm = next((e for e in reversed(conv.events)
                             if e.TYPE == "confirmation_required"), None)
        pending_finish = next((e for e in reversed(conv.events)
                               if isinstance(e, events.FinishedEvent)), None)
        if last_confirm is not None:
            idx = conv.events.index(last_confirm)
            if pending_finish is None or conv.events.index(pending_finish) < idx:
                conv.pending_action = (last_confirm.tool, last_confirm.args)
        return conv

    # ----------------------------------------------------------- writing
    def append(self, event):
        with self.lock:
            self.events.append(event)
            path = os.path.join(self.dir, "events.jsonl")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(events.serialize(event) + "\n")
            if isinstance(event, events.FinishedEvent):
                status = (self.FINISHED if event.reason == "answered"
                          else self.ERROR)
                self._set_status(status)
                self.pending_action = None
            elif isinstance(event, events.ConfirmationRequiredEvent):
                self._set_status(self.WAITING_CONFIRMATION)
                self.pending_action = (event.tool, event.args)

    def _set_status(self, status):
        self.meta["status"] = status
        self._save_meta()

    def set_status(self, status):
        with self.lock:
            self._set_status(status)

    def _save_meta(self):
        with open(os.path.join(self.dir, "meta.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(self.meta, fh, indent=2)

    # ---------------------------------------------------------- reading
    @property
    def id(self):
        return self.meta.get("id", os.path.basename(self.dir))

    @property
    def status(self):
        return self.meta.get("status", self.IDLE)

    def slice(self, after=0):
        """Events strictly after index `after` (incremental polling)."""
        with self.lock:
            return list(self.events[after:]), len(self.events)

    def last_finished(self):
        return next((e for e in reversed(self.events)
                     if isinstance(e, events.FinishedEvent)), None)


class Store:
    """Disk-backed listing of all conversations."""

    def __init__(self, root=None):
        self.root = root or content.conversations_dir()

    def create(self, workspace_root=""):
        return Conversation.new(root=self.root,
                                workspace_root=workspace_root)

    def list(self):
        out = []
        if not os.path.isdir(self.root):
            return out
        for name in sorted(os.listdir(self.root), reverse=True):
            meta_path = os.path.join(self.root, name, "meta.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as fh:
                        out.append(json.load(fh))
                except (OSError, ValueError):
                    continue
        return out

    def get(self, cid):
        path = os.path.join(self.root, cid)
        if not os.path.isdir(path):
            return None
        return Conversation.load(path)

    def prune(self, keep_days=14):
        """Delete conversations older than the retention window.

        Returns (removed_count). Only touches ptah-owned data dirs and
        refuses anything that does not look like a conversation dir.
        """
        cutoff = time.time() - keep_days * 86400
        removed = 0
        if not os.path.isdir(self.root):
            return removed
        for name in os.listdir(self.root):
            path = os.path.join(self.root, name)
            marker = os.path.join(path, "meta.json")
            if not (os.path.isdir(path) and os.path.isfile(marker)):
                continue                      # not ours - never touch
            if os.path.getmtime(marker) < cutoff:
                import shutil
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        return removed
