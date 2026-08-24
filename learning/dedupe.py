"""Token similarity for lesson de-duplication (stdlib only)."""

import re

_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {"the", "and", "for", "with", "after", "before", "a", "an",
         "of", "to", "in", "on", "is", "are", "be", "been"}


def _stem(w):
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: len(w) - len(suf)]
    return w


def tokens(text):
    """Lowercase stemmed word set, stopwords dropped."""
    return {_stem(w) for w in _WORD.findall(str(text).lower())
            if w not in _STOP}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def best_match(entry, lessons, threshold=0.55):
    """Return (lesson, score) of the most similar existing lesson,
    or None when nothing clears ``threshold``. Similarity blends
    title overlap with tag overlap (tags weighted double)."""
    cand_title = tokens(entry.get("title", ""))
    cand_tags = {t.lower() for t in entry.get("tags", [])}
    best, best_score = None, 0.0
    for lsn in lessons:
        score = jaccard(cand_title, tokens(lsn.get("title", "")))
        existing_tags = {t.lower() for t in lsn.get("tags", [])}
        if cand_tags or existing_tags:
            tag_score = jaccard(cand_tags, existing_tags)
            score = max(score, tag_score * 0.9)
        if score > best_score:
            best, best_score = lsn, score
    if best is None or best_score < threshold:
        return None
    return best, round(best_score, 3)
