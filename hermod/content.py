"""HERMOD tuning table - the feed pipeline obeys nothing but this."""

import os

VERSION = 1

ORGAN = "hermod"
TOPIC = "feeds"

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(HERE)
DATA_DIR = os.path.join(HERE, "data")
INBOX_DIR = os.path.join(DATA_DIR, "incoming")     # operator drops here
STORE_DIR = os.path.join(DATA_DIR, "store")        # normalized feeds
DONE_DIR = os.path.join(DATA_DIR, "processed")
FAILED_DIR = os.path.join(DATA_DIR, "failed")

KEEP_PROCESSED = 100          # archived originals per side
MAX_ENTRIES_PER_BUNDLE = 5000
STORE_KEEP_ENTRIES = 20_000   # per-source bound; oldest pruned on append

AUDIT_PATH = os.path.join(DATA_DIR, "audit.jsonl")
AUDIT_MAX_BYTES = 1_000_000
