from formats.schemas import is_walkable_map

from .grid import Grid


def grid_from_map(m, layer=0):
    blocked_rows = is_walkable_map(m)
    width, height = m["width"], m["height"]
    blocked = {
        (x, y)
        for y in range(height)
        for x in range(width)
        if blocked_rows[y][x]
    }
    return Grid(width, height, blocked)
