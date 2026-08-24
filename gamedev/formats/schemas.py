import json


MAP_FORMAT = "gd.map/1"
REPLAY_FORMAT = "gd.replay/1"
PROTOCOL_VERSION = "gd.net/1"


def make_map(width, height, tiles, layer_name="ground", tile_size=16, spawn=(1, 1), meta=None):
    return {
        "format": MAP_FORMAT,
        "width": width,
        "height": height,
        "tile_size": tile_size,
        "layers": [{"name": layer_name, "tiles": list(tiles)}],
        "spawn": [int(spawn[0]), int(spawn[1])],
        "meta": dict(meta or {}),
    }


def validate_map(m):
    if not isinstance(m, dict):
        return ["map must be an object"]
    errors = []
    if m.get("format") != MAP_FORMAT:
        errors.append(f"format must be {MAP_FORMAT!r}")
    width = m.get("width")
    height = m.get("height")
    if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
        errors.append("width must be a positive int")
    if not isinstance(height, int) or isinstance(height, bool) or height <= 0:
        errors.append("height must be a positive int")
    if errors:
        return errors
    layers = m.get("layers")
    if not isinstance(layers, list) or not layers:
        return errors + ["layers must be a non-empty list"]
    seen_names = set()
    for i, layer in enumerate(layers):
        if not isinstance(layer, dict):
            errors.append(f"layer[{i}] must be an object")
            continue
        name = layer.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"layer[{i}].name must be a non-empty string")
        elif name in seen_names:
            errors.append(f"duplicate layer name {name!r}")
        else:
            seen_names.add(name)
        tiles = layer.get("tiles")
        if not isinstance(tiles, list):
            errors.append(f"layer[{i}].tiles must be a list")
        elif len(tiles) != width * height:
            errors.append(
                f"layer[{i}].tiles length {len(tiles)} != width*height {width * height}"
            )
        else:
            bad = [t for t in tiles if not isinstance(t, int) or isinstance(t, bool) or t < 0]
            if bad:
                errors.append(f"layer[{i}].tiles contains {len(bad)} invalid tile ids")
    spawn = m.get("spawn")
    if (
        not isinstance(spawn, list)
        or len(spawn) != 2
        or any(not isinstance(v, int) or isinstance(v, bool) for v in spawn)
    ):
        errors.append("spawn must be [x, y] ints")
    elif not (0 <= spawn[0] < width and 0 <= spawn[1] < height):
        errors.append("spawn out of bounds")
    meta = m.get("meta")
    if meta is not None and not isinstance(meta, dict):
        errors.append("meta must be an object")
    return errors


def is_walkable_map(m, wall_tiles=frozenset({1})):
    width, height = m["width"], m["height"]
    tiles = m["layers"][0]["tiles"]

    def at(x, y):
        return tiles[y * width + x]

    blocked = [[at(x, y) in wall_tiles for x in range(width)] for y in range(height)]
    return blocked


def validate_replay(r):
    if not isinstance(r, dict):
        return ["replay must be an object"]
    errors = []
    if r.get("format") != REPLAY_FORMAT:
        errors.append(f"format must be {REPLAY_FORMAT!r}")
    seed = r.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        errors.append("seed must be a non-negative int")
    game = r.get("game")
    if not isinstance(game, str) or not game:
        errors.append("game must be a non-empty string")
    ticks = r.get("ticks")
    if not isinstance(ticks, list):
        return errors + ["ticks must be a list"]
    prev_t = -1
    for i, tick in enumerate(ticks):
        if not isinstance(tick, dict):
            errors.append(f"tick[{i}] must be an object")
            continue
        t = tick.get("t")
        if not isinstance(t, int) or isinstance(t, bool) or t != prev_t + 1:
            errors.append(f"tick[{i}].t must be exactly previous+1 (got {t}, prev {prev_t})")
        prev_t = t if isinstance(t, int) and not isinstance(t, bool) else prev_t
        inputs = tick.get("inputs")
        if not isinstance(inputs, list) or any(not isinstance(x, str) for x in inputs):
            errors.append(f"tick[{i}].inputs must be a list of strings")
    return errors


def save_map(m, path):
    errors = validate_map(m)
    if errors:
        raise ValueError(f"refusing to save invalid map: {errors}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f)


def load_map(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_replay(r, path):
    errors = validate_replay(r)
    if errors:
        raise ValueError(f"refusing to save invalid replay: {errors}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f)


def load_replay(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
