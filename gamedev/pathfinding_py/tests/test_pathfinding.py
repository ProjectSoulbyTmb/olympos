import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from formats.schemas import make_map  # noqa: E402

from pathfinding_py import (  # noqa: E402
    Grid,
    UnreachableError,
    astar_path,
    bfs_path,
    ensure_reachable,
    flow_field,
    grid_from_map,
    reachable,
    step_toward,
)


def open_grid(w=10, h=8):
    return Grid(w, h)


def wall_grid():
    g = Grid(5, 5)
    for y in range(1, 4):
        g.set_blocked(2, y)
    return g


class TestGrid(unittest.TestCase):
    def test_bounds_and_blocked(self):
        g = open_grid()
        self.assertTrue(g.walkable(0, 0))
        self.assertFalse(g.in_bounds(-1, 0))
        self.assertFalse(g.in_bounds(10, 0))
        self.assertFalse(g.walkable(9, 8))
        g.set_blocked(3, 3)
        self.assertTrue(g.blocked(3, 3))
        g.set_blocked(3, 3, False)
        self.assertFalse(g.blocked(3, 3))


class TestPaths(unittest.TestCase):
    def test_bfs_straight_line_length(self):
        g = open_grid()
        p = bfs_path(g, (0, 0), (3, 0))
        self.assertEqual(p, [(0, 0), (1, 0), (2, 0), (3, 0)])

    def test_bfs_detours_around_wall(self):
        g = wall_grid()
        p = bfs_path(g, (0, 2), (4, 2))
        self.assertIsNotNone(p)
        self.assertEqual(p[0], (0, 2))
        self.assertEqual(p[-1], (4, 2))
        self.assertEqual(len(p), 7)

    def test_astar_matches_bfs_cost_on_uniform_grid(self):
        g = wall_grid()
        a = astar_path(g, (0, 2), (4, 2))
        b = bfs_path(g, (0, 2), (4, 2))
        self.assertEqual(len(a), len(b))

    def test_unreachable_returns_none(self):
        g = Grid(3, 1)
        g.set_blocked(1, 0)
        self.assertIsNone(bfs_path(g, (0, 0), (2, 0)))
        self.assertIsNone(astar_path(g, (0, 0), (2, 0)))

    def test_blocked_start_or_goal(self):
        g = open_grid()
        g.set_blocked(0, 0)
        self.assertIsNone(bfs_path(g, (0, 0), (1, 0)))


class TestReachability(unittest.TestCase):
    def test_reachable_set_and_limit(self):
        g = open_grid(10, 10)
        all_cells = reachable(g, (0, 0))
        self.assertEqual(len(all_cells), 100)
        limited = reachable(g, (0, 0), max_dist=2)
        self.assertEqual(
            limited, {(0, 0), (1, 0), (2, 0), (0, 1), (0, 2), (1, 1)}
        )

    def test_ensure_reachable_raises(self):
        g = Grid(3, 1)
        g.set_blocked(1, 0)
        with self.assertRaises(UnreachableError):
            ensure_reachable(g, (0, 0), (2, 0))


class TestFlowField(unittest.TestCase):
    def test_flow_steps_lead_to_goal(self):
        g = wall_grid()
        field = flow_field(g, (4, 2))
        self.assertIn((0, 2), field)
        pos = (0, 2)
        steps = 0
        while pos != (4, 2):
            pos = step_toward(field, pos)
            steps += 1
            self.assertLess(steps, 50)
        expected = len(bfs_path(g, (0, 2), (4, 2))) - 1
        self.assertEqual(steps, expected)

    def test_step_at_goal_is_none(self):
        g = open_grid()
        field = flow_field(g, (2, 2))
        self.assertIsNone(step_toward(field, (2, 2)))

    def test_flow_skips_blocked_goal(self):
        g = open_grid()
        g.set_blocked(1, 1)
        self.assertEqual(flow_field(g, (1, 1)), {})


class TestMapAdapter(unittest.TestCase):
    def border_map(self):
        w, h = 6, 6
        tiles = [
            1 if (x in (0, w - 1) or y in (0, h - 1)) else 0
            for y in range(h)
            for x in range(w)
        ]
        return make_map(w, h, tiles, spawn=(1, 1))

    def test_adapter_blocks_borders(self):
        g = grid_from_map(self.border_map())
        self.assertFalse(g.walkable(0, 0))
        self.assertTrue(g.walkable(1, 1))
        p = bfs_path(g, (1, 1), (4, 4))
        self.assertIsNotNone(p)
        self.assertEqual(len(p), 7)

    def test_adapter_with_extra_pillar_forces_longer_path(self):
        m = self.border_map()
        for y in range(2, 5):
            m["layers"][0]["tiles"][y * 6 + 3] = 1
        g = grid_from_map(m)
        detour = bfs_path(g, (1, 1), (4, 4))
        self.assertIsNotNone(detour)
        self.assertGreater(len(detour), 7)
        self.assertTrue(all(x != 3 for x, _ in detour))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    )
    sys.exit(0 if result.wasSuccessful() else 1)
