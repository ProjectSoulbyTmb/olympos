"""imaging - pure-stdlib frame math: PPM I/O, hashes, histograms,
scene-cut detection and motion scoring.

FFmpeg decodes video into raw PPM (P6) frames; everything after that
is dependency-free Python so analysis runs anywhere, offline.
"""
import os


# ---------------------------------------------------------------- PPM I/O

def read_ppm(source):
    """Parse a binary PPM (P6). Returns (width, height, pixels-bytes)."""
    if isinstance(source, (bytes, bytearray)):
        return _parse(bytes(source))
    with open(os.fspath(source), "rb") as fh:
        return _parse(fh.read())


def _parse(data):
    # header: P6\n<w> <h>\n<max>\n  (whitespace-tolerant)
    pos, fields = 0, []
    while len(fields) < 4:
        while pos < len(data) and data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            while pos < len(data) and data[pos] not in (10, 13):
                pos += 1
            continue
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        fields.append(data[start:pos])
    magic, w, h, maxval = (fields[0], int(fields[1]), int(fields[2]),
                           int(fields[3]))
    if magic != b"P6" or maxval > 255:
        raise ValueError("only binary P6 PPM with 8-bit channels")
    pos += 1  # single whitespace byte before raster
    need = w * h * 3
    raster = data[pos:pos + need]
    if len(raster) < need:
        raise ValueError("truncated PPM raster")
    return w, h, raster


def write_ppm(path, width, height, pixels):
    if len(pixels) != width * height * 3:
        raise ValueError("pixel buffer size mismatch")
    with open(path, "wb") as fh:
        fh.write(b"P6\n%d %d\n255\n" % (width, height))
        fh.write(pixels)


# ------------------------------------------------------- downscale / gray

GRAY_GRID = 9          # NxN perceptual grid used by both hashes
DHASH_BITS = GRAY_GRID * (GRAY_GRID - 1)


def to_gray_small(w, h, px, grid=GRAY_GRID):
    """Area-average an RGB raster into a small grayscale grid."""
    out = bytearray(grid * grid)
    for gy in range(grid):
        y0 = h * gy // grid
        y1 = max(h * (gy + 1) // grid, y0 + 1)
        sy = max(1, (y1 - y0) // 8)
        for gx in range(grid):
            x0 = w * gx // grid
            x1 = max(w * (gx + 1) // grid, x0 + 1)
            sx = max(1, (x1 - x0) // 8)
            r = g = b = n = 0
            for y in range(y0, y1, sy):
                row = y * w
                for x in range(x0, x1, sx):
                    i = (row + x) * 3
                    r += px[i]
                    g += px[i + 1]
                    b += px[i + 2]
                    n += 1
            out[gy * grid + gx] = \
                (r * 299 + g * 587 + b * 114) // 1000 // max(n, 1)
    return grid, grid, bytes(out)


# ---------------------------------------------------------------- hashing

def ahash(w, h, px):
    gw, gh, gray = to_gray_small(w, h, px)
    avg = sum(gray) // len(gray)
    bits = "".join("1" if v >= avg else "0" for v in gray)
    return "%016x" % int(bits, 2)


def dhash(w, h, px, grid=GRAY_GRID):
    _gw, _gh, gray = to_gray_small(w, h, px, grid)
    bits = []
    for y in range(grid):
        row = y * grid
        for x in range(grid - 1):
            bits.append("1" if gray[row + x] > gray[row + x + 1] else "0")
    return "%016x" % int("".join(bits) or "0", 2)


def hamming(hex_a, hex_b):
    return bin(int(hex_a, 16) ^ int(hex_b, 16)).count("1")


# ------------------------------------------------------------- histogram

def histogram(w, h, px, bins=8):
    """Per-channel normalized histograms flattened; sums to ~1."""
    hist = [0] * (bins * 3)
    n = w * h
    for i in range(0, len(px), 3):
        hist[px[i] * bins // 256] += 1
        hist[bins + px[i + 1] * bins // 256] += 1
        hist[2 * bins + px[i + 2] * bins // 256] += 1
    return [round(v / n, 6) for v in hist]


def hist_distance(ha, hb):
    """Histogram intersection distance: ~0 identical .. 1 disjoint.

    Each channel's histogram sums to ~1, so the full intersection is
    normalized by the channel count."""
    if not ha or len(ha) != len(hb):
        return 1.0
    total = sum(min(a, b) for a, b in zip(ha, hb))
    channels = max(len(ha) / 3.0, 1.0)
    return round(max(0.0, min(1.0 - total / channels, 1.0)), 6)


# ------------------------------------------- frame sequence understanding

class FrameStats:
    """Lightweight per-frame fingerprint used for cuts and motion."""

    __slots__ = ("ahash", "dhash", "hist")

    def __init__(self, ahash, dhash, hist):
        self.ahash, self.dhash, self.hist = ahash, dhash, hist

    def diff(self, other):
        return (hamming(self.dhash, other.dhash) /
                float(DHASH_BITS),
                self.hist_hist_dist(other))

    def hist_hist_dist(self, other):
        return hist_distance(self.hist, other.hist)


def frame_stats_from_ppm(path):
    w, h, px = read_ppm(path)
    return FrameStats(ahash(w, h, px), dhash(w, h, px),
                      histogram(w, h, px))


def detect_scenes(stats, timestamps, hist_thresh=0.45, dhash_thresh=0.34):
    """Cut boundaries where consecutive frames diverge sharply.

    Returns list of (start, end) scene spans covering the timeline.
    """
    scenes = []
    cut = 0
    for i in range(1, len(stats)):
        dh, hh = stats[i].diff(stats[i - 1])
        if dh >= dhash_thresh and hh >= hist_thresh:
            scenes.append((timestamps[cut], timestamps[i]))
            cut = i
    if timestamps:
        scenes.append((timestamps[cut], timestamps[-1]))
    return [(round(a, 3), round(b, 3)) for a, b in scenes]


def motion_score(stats):
    """Mean perceptual delta between consecutive frames, 0..1."""
    if len(stats) < 2:
        return 0.0
    deltas = [stats[i].diff(stats[i - 1])[0] for i in range(1, len(stats))]
    return round(sum(deltas) / len(deltas), 6)
