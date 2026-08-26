"""HADES auth - the operator's daily password gate.

Seal and verify prove ASSETS are intact; auth proves the OPERATOR is
present. One password unlocks a session (default 12h - one per working
day); while a session is alive every gated verb flows without further
prompts. When it lapses, everything gated waits for the operator.

Storage rules (never violated):
  - the password itself is NEVER written anywhere: disk, logs, git
  - auth.json keeps ONLY salt + iteration count + PBKDF2-HMAC-SHA256
    digest of the password
  - comparison is constant-time (hmac.compare_digest)
  - session.json holds a random token + expiry; deleting it = locked
  - failed attempts count up and back off exponentially (capped at 15
    minutes) BEFORE hashing work is spent on an attacker

Fail-closed: missing or corrupt auth state locks every gated verb;
nothing ever falls open.
"""

import hashlib
import hmac
import json
import os
import secrets
import sys
import time


DEFAULT_TTL_S = 12 * 3600
PBKDF_ITERATIONS = 200_000
SALT_BYTES = 16
TOKEN_BYTES = 32
MIN_PASSWORD_LEN = 8

BACKOFF_FREE_FAILS = 3     # first N failures cost nothing but evidence
BACKOFF_BASE_S = 2
BACKOFF_CAP_S = 900


class AuthError(RuntimeError):
    """Refused: bad password, backoff active, or unusable auth state."""


def announce(event):
    """Mirror one auth event onto the Ratatosk bus (hades-alerts).
    Best-effort, never raises - the audit trail stays the truth."""
    try:
        from ratatosk import publish
        publish("hades-alerts", event, frm="hades-auth",
                kind=str(event.get("kind", "event")))
    except Exception:
        pass


def _now():
    return int(time.time())


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


class AuthStore:
    """Credential + session state under the hades state directory."""

    def __init__(self, state_dir, ttl_s=DEFAULT_TTL_S):
        self.state_dir = state_dir
        self.auth_path = os.path.join(state_dir, "auth.json")
        self.session_path = os.path.join(state_dir, "session.json")
        self.ttl_s = int(ttl_s)

    # ---------- credential document ----------

    def status(self):
        """'missing' (never enrolled), 'corrupt' (present but unusable),
        or 'ok'. Corrupt is fail-closed, never auto-repaired."""
        if not os.path.exists(self.auth_path):
            return "missing"
        try:
            with open(self.auth_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if (str(doc.get("salt_hex", "")).lower()
                    and int(doc["iterations"]) > 0
                    and str(doc.get("hash_hex", ""))):
                return "ok"
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return "corrupt"

    def is_configured(self):
        return self.status() == "ok"

    def _load(self):
        with open(self.auth_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _digest(password, salt, iterations):
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt,
            int(iterations)).hex()

    def _write_auth(self, doc):
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self.auth_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
        os.replace(tmp, self.auth_path)

    def _check_current(self, old):
        """Verify the current password before any change; failures feed
        the same backoff counter as unlock attempts."""
        doc = self._load()
        want = self._digest(old or "", bytes.fromhex(doc["salt_hex"]),
                            doc["iterations"])
        if hmac.compare_digest(want, str(doc["hash_hex"])):
            return True
        self.register_failure()
        raise AuthError("current password is wrong")

    def set_password(self, new_password, old=None):
        """Enroll or rotate. Requires the current password when already
        configured. Kills any live session either way."""
        if len(new_password or "") < MIN_PASSWORD_LEN:
            raise AuthError("password must be at least %d characters"
                            % MIN_PASSWORD_LEN)
        rotated = self.is_configured()
        if rotated:
            self._check_current(old)
        salt = secrets.token_bytes(SALT_BYTES)
        doc = {
            "version": 1,
            "salt_hex": salt.hex(),
            "iterations": PBKDF_ITERATIONS,
            "hash_hex": self._digest(new_password, salt, PBKDF_ITERATIONS),
            "created_at": _iso(_now()),
            "fails": 0,
            "last_fail": 0,
        }
        self._write_auth(doc)
        self.lock()
        return rotated

    # ---------- failures / backoff ----------

    def _save_counters(self, doc):
        self._write_auth(doc)

    def register_failure(self):
        doc = self._load()
        doc["fails"] = int(doc.get("fails", 0)) + 1
        doc["last_fail"] = _now()
        self._save_counters(doc)
        return doc["fails"]

    def reset_failures(self):
        try:
            doc = self._load()
        except (OSError, ValueError):
            return
        if doc.get("fails"):
            doc["fails"] = 0
            doc["last_fail"] = 0
            self._save_counters(doc)

    def fails(self):
        if not self.is_configured():
            return 0
        return int(self._load().get("fails", 0))

    def backoff_remaining(self, now=None):
        """Seconds an attacker (or a mistyped finger) must still wait.
        Rule: after BACKOFF_FREE_FAILS consecutive failures, each extra
        failure doubles the wait: 2^(f-N) seconds, capped."""
        now = _now() if now is None else int(now)
        f = self.fails()
        if f <= BACKOFF_FREE_FAILS:
            return 0
        delay = min(BACKOFF_CAP_S,
                    BACKOFF_BASE_S * (2 ** (f - BACKOFF_FREE_FAILS - 1)))
        elapsed = now - int(self._load().get("last_fail", 0))
        return max(0, delay - elapsed)

    # ---------- session ----------

    def _write_session(self, doc):
        os.makedirs(self.state_dir, exist_ok=True)
        fd = os.open(self.session_path,
                     os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, sort_keys=True)

    def session_valid(self, now=None):
        now = _now() if now is None else int(now)
        if not os.path.exists(self.session_path):
            return False
        try:
            with open(self.session_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if now < int(doc["expires_epoch"]) and doc.get("token_hex"):
                return True
        except (OSError, ValueError, TypeError, KeyError):
            pass
        try:
            os.remove(self.session_path)      # expired/garbage: sweep it
        except OSError:
            pass
        return False

    def session(self):
        if not self.session_valid():
            return None
        with open(self.session_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def attempt_unlock(self, password, now=None):
        """One login try. Returns the session document on success, None
        on a wrong password (and counts it), raises AuthError while a
        backoff is running or the credential state is unusable."""
        now = _now() if now is None else int(now)
        state = self.status()
        if state == "corrupt":
            raise AuthError(
                "auth state is corrupt - restore or delete "
                "hades/state/auth.json, then run: python hades/cli.py passwd")
        if state == "missing":
            raise AuthError(
                "no password enrolled - run: python hades/cli.py passwd")
        wait = self.backoff_remaining(now)
        if wait > 0:
            raise AuthError("too many failures - wait %d s" % wait)
        doc = self._load()
        want = self._digest(password or "", bytes.fromhex(doc["salt_hex"]),
                            doc["iterations"])
        if not hmac.compare_digest(want, str(doc["hash_hex"])):
            self.register_failure()
            announce({"kind": "auth_fail",
                      "fails": int(doc.get("fails", 0)) + 1})
            return None
        self.reset_failures()
        session = {
            "token_hex": secrets.token_bytes(TOKEN_BYTES).hex(),
            "unlocked_at": _iso(now),
            "expires_epoch": now + self.ttl_s,
            "expires_at": _iso(now + self.ttl_s),
        }
        self._write_session(session)
        return session

    def lock(self):
        try:
            os.remove(self.session_path)
        except OSError:
            pass

    # ---------- reporting ----------

    def public_state(self):
        """Safe-to-print summary (no secrets, no hashes)."""
        sess = self.session() if self.is_configured() else None
        return {
            "auth": {
                "state": self.status(),
                "unlocked": bool(sess),
                "expires_at": (sess or {}).get("expires_at"),
                "fails": self.fails(),
            }
        }
