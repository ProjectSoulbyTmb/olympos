"""ZEUS oracle - the anomaly eye.

The oracle samples hot directories each patrol tick and builds a
lightweight mutation signature (per-entry mtime/size/existence). A
sudden burst of changes - especially arrivals of mostly new files -
is the classic ransomware/staging signature, so bursts escalate to
critical findings the kernel can act on. Sampling is capped so even
fat trees cannot stall a patrol.
"""

import os

import content


class HotDir:
    """One watched directory with a rolling window of change counts."""

    def __init__(self, path, max_entries):
        self.path = path
        self.max_entries = max_entries
        self.last_sig = None
        self.window = []           # [(changed, added), ...] newest last

    def sample(self):
        """Return (changed, added) vs previous sample."""
        sig = {}
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.path):
            dirnames[:] = [d for d in sorted(dirnames)
                           if d.lower() not in content.EXCLUDE_DIRS]
            for fn in sorted(filenames):
                if count >= self.max_entries:
                    return None     # tree too big - skip this round
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                    sig[p] = (st.st_mtime_ns, st.st_size)
                except OSError:
                    sig[p] = (-1, -1)   # vanished mid-walk: still an entry
                count += 1
        prev = self.last_sig
        self.last_sig = sig
        if prev is None:
            return None              # first sample only primes the pump
        changed = added = 0
        for key, val in sig.items():
            old = prev.get(key)
            if old is None:
                added += 1
                changed += 1
            elif old != val:
                changed += 1
        return changed, added


class Oracle:
    def __init__(self, churn_dirs=None):
        rel_dirs = list(churn_dirs if churn_dirs is not None
                        else content.CHURN_DIRS)
        self.hots = [HotDir(os.path.join(content.WORKSPACE, d),
                            content.CHURN_MAX_ENTRIES)
                     for d in rel_dirs]

    def patrol(self):
        """Sample all hot dirs; returns anomaly findings."""
        out = []
        for hot in self.hots:
            res = self._sample_safe(hot)
            if res is None:
                continue
            hot.window.append(res)
            if len(hot.window) > content.CHURN_WINDOW_TICKS:
                hot.window.pop(0)
            total_changed = sum(c for c, _ in hot.window)
            total_added = sum(a for _, a in hot.window)
            if total_changed < content.CHURN_BURST_THRESHOLD \
                    or len(hot.window) < 1:
                continue
            share_new = (total_added / total_changed) \
                if total_changed else 0.0
            synthetic = share_new >= content.CHURN_NEW_FILE_SHARE
            out.append({
                "type": "churn_burst", "severity": "critical",
                "dir": hot.path,
                "changed": total_changed,
                "added": total_added,
                "synthetic": synthetic,
                "text": f"mutation burst in {hot.path}: "
                        f"{total_changed} entries in "
                        f"{len(hot.window)} ticks "
                        f"({total_added} new)",
            })
            hot.window.clear()       # one burst per incident
        return out

    @staticmethod
    def _sample_safe(hot):
        try:
            return hot.sample()
        except OSError:
            hot.window.clear()
            return None
