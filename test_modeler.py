import unittest
from unittest.mock import Mock

from calculator import RoofCalculator, RoofConfig, RoofInput
from modeler import RoofModelerApp
from roof_3d import build_cementoplast
from roof_plan import RoofPlan


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


class EraserDragTests(unittest.TestCase):
    def setUp(self):
        self.app = RoofModelerApp.__new__(RoofModelerApp)
        self.app.tool_var = Mock()
        self.app.tool_var.get.return_value = "eraser"
        self.app.eraser_dragging = False
        self.app._on_eraser_click = Mock()
        self.app._draw = Mock()

    def test_eraser_press_starts_drag_and_erases(self):
        event = Mock(x=30, y=40)

        self.app._on_click(event)

        self.assertTrue(self.app.eraser_dragging)
        self.assertEqual((self.app.mouse_x, self.app.mouse_y), (30, 40))
        self.app._on_eraser_click.assert_called_once_with(30, 40)

    def test_eraser_drag_erases_at_each_pointer_position_until_release(self):
        self.app.eraser_dragging = True

        self.app._on_left_drag(Mock(x=50, y=60))
        self.app._on_left_release(Mock(x=70, y=80))
        self.app._on_left_drag(Mock(x=90, y=100))

        self.app._on_eraser_click.assert_called_once_with(50, 60, preserve_endpoint_dots=True)
        self.assertFalse(self.app.eraser_dragging)
        self.assertEqual((self.app.mouse_x, self.app.mouse_y), (90, 100))

    def test_drag_erasing_line_preserves_endpoint_dots(self):
        app = RoofModelerApp.__new__(RoofModelerApp)
        app.dots = [(0.0, 0.0), (5.0, 0.0)]
        app.edges = [{"a": 0, "b": 1, "edge_type": "line"}]
        app.ventilation_ducts = []
        app.selected_dot = None
        app.selected_edge = None
        app._merge_areas_across_edge = Mock()
        app._push_history = Mock()
        app._sync_params = Mock()
        app._draw = Mock()

        app._delete_edge(0, preserve_endpoint_dots=True)

        self.assertEqual(app.dots, [(0.0, 0.0), (5.0, 0.0)])
        self.assertEqual(app.edges, [])


class CementoplastDirectionTests(unittest.TestCase):
    def setUp(self):
        self.plan = RoofPlan([(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)])

    def _border_height(self, mesh, axis, coordinate):
        vertices = mesh.vertices[abs(mesh.vertices[:, axis] - coordinate) < 1e-9]
        return max(vertices[:, 2])

    def test_directional_slopes_fall_toward_selected_border(self):
        expected = {
            "left": (0, 0.0, 10.0, 0.0, 0.2),
            "right": (0, 10.0, 0.0, 0.0, 0.2),
            "forward": (1, 4.0, 0.0, 0.0, 0.08),
            "backward": (1, 0.0, 4.0, 0.0, 0.08),
        }
        for direction, (axis, low_border, high_border, low_z, high_z) in expected.items():
            with self.subTest(direction=direction):
                mesh = build_cementoplast(
                    self.plan,
                    RoofConfig(base_slope_direction=direction, base_slope_pct=2.0),
                )
                self.assertTrue(mesh.is_watertight)
                self.assertAlmostEqual(self._border_height(mesh, axis, low_border), low_z)
                self.assertAlmostEqual(self._border_height(mesh, axis, high_border), high_z)

    def test_directional_slope_volume_uses_full_span(self):
        data = RoofInput(10.0, 4.0, 1.0, 0.2)
        left = RoofCalculator.calculate(data, RoofConfig(base_slope_direction="left", base_slope_pct=2.0))
        forward = RoofCalculator.calculate(data, RoofConfig(base_slope_direction="forward", base_slope_pct=2.0))
        self.assertEqual(left.v_cementoplast_m3, 4.0)
        self.assertEqual(forward.v_cementoplast_m3, 1.6)


if __name__ == "__main__":
    unittest.main()
