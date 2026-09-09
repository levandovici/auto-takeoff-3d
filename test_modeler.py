import unittest
from unittest.mock import Mock

from modeler import RoofModelerApp


class DeleteEdgeTests(unittest.TestCase):
    def test_deleting_divider_simplifies_both_nearly_straight_endpoints(self):
        app = RoofModelerApp.__new__(RoofModelerApp)
        app.dots = [
            (10.50, 18.60),
            (23.95, 18.60),
            (23.95, 8.90),
            (10.35, 9.20),
            (14.20, 9.12),
            (19.45, 18.60),
        ]
        props = {"edge_type": "none"}
        app.edges = [
            dict(props, a=0, b=5),
            dict(props, a=5, b=1),
            dict(props, a=1, b=2),
            dict(props, a=2, b=4),
            dict(props, a=4, b=3),
            dict(props, a=3, b=0),
            dict(props, a=4, b=5),
        ]
        app.path = []
        app.areas = []
        app.ventilation_ducts = []
        app.pencil_start = None
        app.hover_dot = None
        app._last_synced_dot = None
        app.selected_dot = None
        app.selected_edge = 6
        app._merge_areas_across_edge = Mock()
        app._push_history = Mock()
        app._sync_params = Mock()
        app._draw = Mock()

        app._delete_edge(6)

        self.assertEqual(len(app.dots), 4)
        self.assertNotIn((14.20, 9.12), app.dots)
        self.assertNotIn((19.45, 18.60), app.dots)
        self.assertEqual(len(app.edges), 4)

    def test_deleting_junction_dot_unifies_continuation_and_removes_branch(self):
        app = RoofModelerApp.__new__(RoofModelerApp)
        app.dots = [
            (12.55, 15.00),
            (24.15, 14.20),
            (23.85, 6.50),
            (12.50, 7.00),
            (12.52, 10.15),
            (24.08, 12.41),
        ]
        props = {"edge_type": "none"}
        app.edges = [
            dict(props, a=0, b=1),
            dict(props, a=1, b=5),
            dict(props, a=5, b=2),
            dict(props, a=2, b=3),
            dict(props, a=3, b=4),
            dict(props, a=4, b=0),
            dict(props, a=4, b=5),
        ]
        app.path = []
        app.areas = []
        app.ventilation_ducts = []
        app.pencil_start = None
        app.hover_dot = None
        app._last_synced_dot = None
        app.selected_dot = 4
        app.selected_edge = None
        app._push_history = Mock()
        app._sync_params = Mock()
        app._draw = Mock()

        app._erase_dot(4)

        self.assertNotIn((12.52, 10.15), app.dots)
        self.assertEqual(len(app.edges), 5)
        self.assertTrue(any({edge["a"], edge["b"]} == {0, 3} for edge in app.edges))
        self.assertFalse(any({edge["a"], edge["b"]} == {3, 4} for edge in app.edges))


if __name__ == "__main__":
    unittest.main()
