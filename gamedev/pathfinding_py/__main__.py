import argparse

from pathfinding_py import Grid, bfs_path


def render(grid, path=None, start=None, goal=None):
    path_set = set(path or ())
    lines = []
    for y in range(grid.height):
        row = []
        for x in range(grid.width):
            c = (x, y)
            if c == start:
                row.append("S")
            elif c == goal:
                row.append("G")
            elif c in path_set:
                row.append("*")
            elif grid.blocked(c[0], c[1]):
                row.append("#")
            else:
                row.append(".")
        lines.append("".join(row))
    return "\n".join(lines)


def demo():
    g = Grid(12, 9)
    for x in range(2, 8):
        g.set_blocked(x, 4)
    start, goal = (1, 7), (10, 1)
    path = bfs_path(g, start, goal)
    print(render(g, path, start, goal))
    print(f"path length: {len(path)} steps" if path else "unreachable")
    g.set_blocked(5, 3)
    g.set_blocked(5, 5)
    path2 = bfs_path(g, start, goal)
    print("after map edit:")
    print(render(g, path2, start, goal))
    if path2 and path:
        print(f"detour cost delta: {len(path2) - len(path)}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pathfinding_py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    args = parser.parse_args(argv)
    if args.cmd == "demo":
        demo()


if __name__ == "__main__":
    main()
