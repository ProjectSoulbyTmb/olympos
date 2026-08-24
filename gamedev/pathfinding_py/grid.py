class Grid:
    def __init__(self, width, height, blocked=None):
        self.width = width
        self.height = height
        self.blocked_cells = set(blocked or ())

    def in_bounds(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def blocked(self, x, y):
        return (x, y) in self.blocked_cells

    def walkable(self, x, y):
        return self.in_bounds(x, y) and not self.blocked(x, y)

    def set_blocked(self, x, y, value=True):
        if value:
            self.blocked_cells.add((x, y))
        else:
            self.blocked_cells.discard((x, y))

    def neighbors(self, x, y):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if self.walkable(nx, ny):
                yield nx, ny

    def cells(self):
        for y in range(self.height):
            for x in range(self.width):
                yield x, y


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
