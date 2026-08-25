import heapq
from collections import deque

from .grid import Grid, manhattan


class UnreachableError(Exception):
    pass


def bfs_path(grid, start, goal):
    if not grid.walkable(*start) or not grid.walkable(*goal):
        return None
    came_from = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if current == goal:
            path = []
            node = current
            while node is not None:
                path.append(node)
                node = came_from[node]
            return list(reversed(path))
        for nxt in grid.neighbors(*current):
            if nxt not in came_from:
                came_from[nxt] = current
                queue.append(nxt)
    return None


def astar_path(grid, start, goal, heuristic=manhattan):
    if not grid.walkable(*start) or not grid.walkable(*goal):
        return None
    open_heap = [(heuristic(start, goal), 0, start)]
    came_from = {start: None}
    cost_so_far = {start: 0}
    while open_heap:
        _, g, current = heapq.heappop(open_heap)
        if current == goal:
            path = []
            node = current
            while node is not None:
                path.append(node)
                node = came_from[node]
            return list(reversed(path))
        for nxt in grid.neighbors(*current):
            new_cost = g + 1
            if nxt not in cost_so_far or new_cost < cost_so_far[nxt]:
                cost_so_far[nxt] = new_cost
                came_from[nxt] = current
                priority = new_cost + heuristic(nxt, goal)
                heapq.heappush(open_heap, (priority, new_cost, nxt))
    return None


def reachable(grid, start, max_dist=None):
    if not grid.walkable(*start):
        return set()
    dist = {start: 0}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        d = dist[current]
        if max_dist is not None and d >= max_dist:
            continue
        for nxt in grid.neighbors(*current):
            if nxt not in dist:
                dist[nxt] = d + 1
                queue.append(nxt)
    return set(dist)


def ensure_reachable(grid, start, goal):
    path = bfs_path(grid, start, goal)
    if path is None:
        raise UnreachableError(f"no path from {start} to {goal}")
    return path


def flow_field(grid, goal):
    if not grid.walkable(*goal):
        return {}
    dist = {goal: 0}
    queue = deque([goal])
    while queue:
        current = queue.popleft()
        for nxt in grid.neighbors(*current):
            if nxt not in dist:
                dist[nxt] = dist[current] + 1
                queue.append(nxt)
    field = {}
    for cell, d in dist.items():
        best = None
        best_dist = d
        for nxt in grid.neighbors(*cell):
            if dist[nxt] < best_dist:
                best_dist = dist[nxt]
                best = nxt
        field[cell] = best
    return field


def step_toward(field, pos):
    return field.get(pos)


__all__ = [
    "UnreachableError",
    "bfs_path",
    "astar_path",
    "reachable",
    "ensure_reachable",
    "flow_field",
    "step_toward",
]
