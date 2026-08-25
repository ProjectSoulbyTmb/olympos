"""kinema - Riley's private offline video studio.

Local-first mp4 production, enhanced analysis, frame sampling and a
folder-fed learning catalog. Optional local AI tier (ComfyUI bridge).
Stdlib only at the core; FFmpeg is the single external binary.

Acceptable use is documented in README.md: no real-person likeness
cloning, no non-consensual imagery of any kind.
"""
import os

VERSION = "1.0"

VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".wmv",
              ".mpg", ".mpeg", ".ts"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".ppm"}

DATA_DIR = os.path.join("data", "kinema")
