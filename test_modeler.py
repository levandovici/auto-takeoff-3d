import unittest
from unittest.mock import Mock, patch

import numpy as np

from calculator import RoofCalculator, RoofConfig, RoofInput
from modeler import MaterialConfigDialog, RoofModelerApp, UnitSettings
from roof_3d import build_cementoplast, build_cementoplast_counterinclination, generate_3d_components
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


class MultiSelectionMoveTests(unittest.TestCase):
    def setUp(self):
        self.app = RoofModelerApp.__new__(RoofModelerApp)
        self.app.dots = [(1.0, 1.0), (4.0, 1.0), (7.0, 1.0)]
        self.app.edges = [
            {"a": 0, "b": 1, "edge_type": "line"},
            {"a": 1, "b": 2, "edge_type": "line"},
        ]
        self.app.selected_dot = None
        self.app.selected_edge = None
        self.app.selected_dots = set()
        self.app.selected_edges = set()
        self.app.eraser_dragging = False
        self.app.pencil_start = None
        self.app._m_to_c = Mock(side_effect=lambda x, y: (x, y))
        self.app._c_to_m = Mock(side_effect=lambda x, y: (x, y))
        self.app._sync_params = Mock()
        self.app._draw = Mock()
        self.app._push_history = Mock()

    def test_rectangle_selects_only_fully_contained_objects(self):
        self.app._select_in_rectangle((0.0, 0.0), (5.0, 2.0))

        self.assertEqual(self.app.selected_dots, {0, 1})
        self.assertEqual(self.app.selected_edges, {0})

    def test_shift_click_adds_dot_to_selection(self):
        self.app._set_selection({0}, set())
        self.app._on_select_click(4.0, 1.0, state=0x1)

        self.assertEqual(self.app.selected_dots, {0, 1})
        self.assertEqual(self.app.selected_edges, set())

    def test_ctrl_click_removes_dot_from_selection(self):
        self.app._set_selection({0, 1}, set())
        self.app._on_select_click(4.0, 1.0, state=0x4)

        self.assertEqual(self.app.selected_dots, {0})
        self.assertEqual(self.app.selected_edges, set())

    def test_shift_box_adds_objects_to_selection(self):
        self.app._set_selection({0}, set())
        self.app._select_in_rectangle((0.0, 0.0), (5.0, 2.0), state=0x1)

        self.assertEqual(self.app.selected_dots, {0, 1})
        self.assertEqual(self.app.selected_edges, {0})

    def test_ctrl_box_removes_objects_from_selection(self):
        self.app._set_selection({0, 1}, {0})
        self.app._select_in_rectangle((0.0, 0.0), (5.0, 2.0), state=0x4)

        self.assertEqual(self.app.selected_dots, set())
        self.assertEqual(self.app.selected_edges, set())

    def test_move_tool_shift_click_adds_object(self):
        self.app._set_selection({0}, {0})
        self.app._find_nearest_dot = Mock(return_value=1)

        self.app._start_move(4.0, 1.0, state=0x1)

        self.assertEqual(self.app.selected_dots, {0, 1})

    def test_move_tool_ctrl_click_removes_object(self):
        self.app._set_selection({0, 1}, {0})
        self.app._find_nearest_dot = Mock(return_value=1)

        self.app._start_move(4.0, 1.0, state=0x4)

        self.assertEqual(self.app.selected_dots, {0})

    def test_move_drags_all_selected_objects_together(self):
        self.app._set_selection({0}, {0})
        self.app._find_nearest_dot = Mock(return_value=0)
        self.app._find_nearest_edge = Mock(return_value=None)
        self.app.tool_var = Mock()
        self.app.tool_var.get.return_value = "move"

        self.app._start_move(1.0, 1.0)
        self.app._on_left_drag(Mock(x=3.0, y=4.0))
        self.app._on_left_release(Mock(x=3.0, y=4.0, state=0))

        self.assertEqual(self.app.dots, [(3.0, 4.0), (6.0, 4.0), (7.0, 1.0)])
        self.app._push_history.assert_called_once()

    def test_move_tool_can_box_select_multiple_objects(self):
        self.app._find_nearest_dot = Mock(return_value=None)
        self.app._find_nearest_edge = Mock(return_value=None)
        self.app.tool_var = Mock()
        self.app.tool_var.get.return_value = "move"

        self.app._start_move(0.0, 0.0)
        self.app._on_left_drag(Mock(x=5.0, y=2.0))
        self.app._on_left_release(Mock(x=5.0, y=2.0, state=0))

        self.assertEqual(self.app.selected_dots, {0, 1})
        self.assertEqual(self.app.selected_edges, {0})

    def test_delete_removes_all_selected_dots_in_descending_order(self):
        self.app._set_selection({0, 2}, {0})
        self.app.tool_var = Mock()
        self.app.tool_var.get.return_value = "select"
        self.app._erase_dot = Mock()

        result = self.app._on_delete()

        self.assertEqual(result, "break")
        self.assertEqual([call.args[0] for call in self.app._erase_dot.call_args_list], [2, 0])

    def test_delete_removes_all_selected_edges_in_descending_order(self):
        self.app._set_selection(set(), {0, 1})
        self.app.tool_var = Mock()
        self.app.tool_var.get.return_value = "select"
        self.app._delete_edge = Mock()

        result = self.app._on_delete()

        self.assertEqual(result, "break")
        self.assertEqual([call.args[0] for call in self.app._delete_edge.call_args_list], [1, 0])

    def test_ctrl_a_selects_all_objects_for_select_and_move_tools(self):
        self.app.root = Mock()
        self.app.root.focus_get.return_value = self.app.root
        self.app.tool_var = Mock()
        self.app._sync_params = Mock()

        for tool in ("select", "move"):
            self.app.tool_var.get.return_value = tool
            result = self.app._select_all()

            self.assertEqual(result, "break")
            self.assertEqual(self.app.selected_dots, {0, 1, 2})
            self.assertEqual(self.app.selected_edges, {0, 1})

    def test_ctrl_a_keeps_entry_select_all_behavior(self):
        self.app.root = Mock()
        self.app.root.focus_get.return_value = Mock(winfo_class=Mock(return_value="TEntry"))
        self.app.tool_var = Mock()
        self.app.tool_var.get.return_value = "select"

        self.assertIsNone(self.app._select_all())

    def test_escape_drops_select_tool_selection(self):
        self.app._set_selection({0, 1}, {0})
        self.app.tool_var = Mock()
        self.app.tool_var.get.return_value = "select"
        self.app.selection_start = None
        self.app.selection_current = None
        self.app.move_last = None
        self.app.move_dot_indices = set()
        self.app.move_changed = False

        result = self.app._on_escape()

        self.assertEqual(result, "break")
        self.assertEqual(self.app.selected_dots, set())
        self.assertEqual(self.app.selected_edges, set())

    def test_escape_drops_move_selection(self):
        self.app._set_selection({0, 1}, {0})
        self.app.tool_var = Mock()
        self.app.tool_var.get.return_value = "move"
        self.app.move_last = None
        self.app.move_dot_indices = {0, 1}
        self.app.move_changed = False

        result = self.app._on_escape()

        self.assertEqual(result, "break")
        self.assertEqual(self.app.selected_dots, set())
        self.assertEqual(self.app.selected_edges, set())
        self.assertIsNone(self.app.selected_dot)
        self.assertIsNone(self.app.selected_edge)


class MaterialConfigValidationTests(unittest.TestCase):
    def setUp(self):
        self.dialog = RoofModelerApp.__new__(RoofModelerApp)
        self.dialog.bitum_layers_var = Mock(get=Mock(return_value=2))
        self.dialog.pvc_geotextil_var = Mock(get=Mock(return_value=1))
        self.dialog.thermal_slab_layers_var = Mock(get=Mock(return_value=2))
        self.dialog.base_pct_var = Mock(get=Mock(return_value=2.0))
        self.dialog.counter_pct_var = Mock(get=Mock(return_value=2.0))
        self.dialog.num_drains_var = Mock(get=Mock(return_value=2))

    @patch("modeler.messagebox.showwarning")
    def test_rejects_out_of_range_slope(self, showwarning):
        self.dialog.base_pct_var.get.return_value = 5.1

        self.assertFalse(MaterialConfigDialog._validate_inputs(self.dialog))
        showwarning.assert_called_once()

    @patch("modeler.messagebox.showwarning")
    def test_accepts_numeric_values_at_bounds(self, showwarning):
        self.dialog.base_pct_var.get.return_value = 1.0
        self.dialog.num_drains_var.get.return_value = 20

        self.assertTrue(MaterialConfigDialog._validate_inputs(self.dialog))
        showwarning.assert_not_called()


class InspectorScrollTests(unittest.TestCase):
    def setUp(self):
        self.app = RoofModelerApp.__new__(RoofModelerApp)
        self.app.right_canvas = Mock()
        self.app.right_inner = Mock(master=self.app.right_canvas)

    def test_wheel_over_inspector_child_scrolls_panel(self):
        child = Mock(master=self.app.right_inner)

        result = self.app._on_right_scroll(Mock(widget=child, num=None, delta=-120))

        self.assertEqual(result, "break")
        self.app.right_canvas.yview_scroll.assert_called_once_with(3, "units")

    def test_wheel_outside_inspector_does_not_scroll_panel(self):
        outside = Mock(master=None)

        result = self.app._on_right_scroll(Mock(widget=outside, num=None, delta=-120))

        self.assertIsNone(result)
        self.app.right_canvas.yview_scroll.assert_not_called()

    def test_scroll_region_starts_at_top_and_contains_full_inspector(self):
        self.app.right_canvas.winfo_width.return_value = 300
        self.app.right_canvas.winfo_height.return_value = 500
        self.app.right_canvas.bbox.return_value = (0, 0, 280, 900)

        self.app._on_right_configure()

        self.app.right_canvas.configure.assert_called_once_with(scrollregion=(0, 0, 300, 900))


class PencilLengthInputTests(unittest.TestCase):
    def setUp(self):
        self.app = RoofModelerApp.__new__(RoofModelerApp)
        self.app.tool_var = Mock()
        self.app.tool_var.get.return_value = "pencil"
        self.app.pencil_start = 0
        self.app.pencil_length_input = ""
        self.app.dots = [(1.0, 2.0)]
        self.app.hover_edge_point = None
        self.app.mouse_x = 11
        self.app.mouse_y = 2
        self.app._c_to_m = Mock(side_effect=lambda x, y: (x, y))
        self.app._m_to_c = Mock(side_effect=lambda x, y: (x, y))
        self.app._on_pencil_click = Mock()
        self.app._draw = Mock()

    def test_keyboard_and_numpad_build_length(self):
        self.app._on_pencil_length_key(Mock(keysym="1", char="1"))
        self.app._on_pencil_length_key(Mock(keysym="period", char="."))
        self.app._on_pencil_length_key(Mock(keysym="KP_5", char="5"))

        self.assertEqual(self.app.pencil_length_input, "1.5")

    def test_enter_draws_length_in_current_direction(self):
        self.app.pencil_length_input = "4.5"

        result = self.app._on_pencil_length_key(Mock(keysym="Return", char="\r"))

        self.assertEqual(result, "break")
        self.assertEqual(self.app.pencil_length_input, "")
        self.app._on_pencil_click.assert_called_once_with(5.5, 2.0)

    def test_escape_action_cancels_line_preview(self):
        self.app.pencil_length_input = "4.5"

        result = self.app._on_escape()

        self.assertEqual(result, "break")
        self.assertIsNone(self.app.pencil_start)
        self.assertEqual(self.app.pencil_length_input, "")

    def test_enter_without_input_finishes_line_at_mouse(self):
        self.app._on_pencil_click = Mock()

        result = self.app._on_pencil_length_key(Mock(keysym="Return", char="\r"))

        self.assertEqual(result, "break")
        self.app._on_pencil_click.assert_called_once_with(11, 2)


class EraserDragTests(unittest.TestCase):
    def setUp(self):
        self.app = RoofModelerApp.__new__(RoofModelerApp)
        self.app.tool_var = Mock()
        self.app.tool_var.get.return_value = "eraser"
        self.app.eraser_dragging = False
        self.app.eraser_last = None
        self.app._on_eraser_click = Mock()
        self.app._erase_along_drag = Mock()
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

        self.app._erase_along_drag.assert_called_once_with(50, 60)
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

    def test_fast_drag_erases_line_between_mouse_events(self):
        app = RoofModelerApp.__new__(RoofModelerApp)
        app.dots = [(5.0, 0.0), (5.0, 4.0)]
        app.edges = [{"a": 0, "b": 1, "edge_type": "line"}]
        app.ventilation_ducts = []
        app.eraser_last = (0.0, 2.0)
        app.hover_dot = None
        app.hover_edge = None
        app._c_to_m = Mock(side_effect=lambda x, y: (x, y))
        app._merge_areas_across_edge = Mock()
        app._push_history = Mock()
        app._sync_params = Mock()
        app._draw = Mock()

        app._erase_along_drag(10.0, 2.0)

        self.assertEqual(app.edges, [])
        self.assertEqual(app.dots, [(5.0, 0.0), (5.0, 4.0)])
        self.assertEqual(app.eraser_last, (10.0, 2.0))


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

    def test_base_layout_selects_center_valley_or_border_valleys(self):
        inside = build_cementoplast(
            self.plan,
            RoofConfig(base_slope_direction="width", base_slope_layout="inside"),
        )
        outside = build_cementoplast(
            self.plan,
            RoofConfig(base_slope_direction="width", base_slope_layout="outside"),
        )
        self.assertAlmostEqual(self._border_height(inside, 0, 5.0), 0.0)
        self.assertAlmostEqual(self._border_height(inside, 0, 0.0), 0.1)
        self.assertAlmostEqual(self._border_height(outside, 0, 5.0), 0.1)
        self.assertAlmostEqual(self._border_height(outside, 0, 0.0), 0.0)

    def test_directional_slope_volume_uses_full_span(self):
        data = RoofInput(10.0, 4.0, 1.0, 0.2)
        left = RoofCalculator.calculate(data, RoofConfig(base_slope_direction="left", base_slope_pct=2.0))
        forward = RoofCalculator.calculate(data, RoofConfig(base_slope_direction="forward", base_slope_pct=2.0))
        self.assertEqual(left.v_cementoplast_layer_1_m3, 4.0)
        self.assertEqual(forward.v_cementoplast_layer_1_m3, 1.6)

    def test_counterinclination_drains_are_evenly_spaced(self):
        self.plan.num_drains = 2
        config = RoofConfig(base_slope_direction="width", counter_slope_pct=2.0)
        layer_1 = build_cementoplast(self.plan, config)
        mesh = build_cementoplast_counterinclination(self.plan, config, layer_1=layer_1)
        self.assertAlmostEqual(min(abs(mesh.vertices[:, 1] - 0.0)), 0.0)
        self.assertAlmostEqual(min(abs(mesh.vertices[:, 1] - 1.0)), 0.0)
        self.assertAlmostEqual(min(abs(mesh.vertices[:, 1] - 2.0)), 0.0)
        self.assertAlmostEqual(min(abs(mesh.vertices[:, 1] - 3.0)), 0.0)
        self.assertAlmostEqual(min(abs(mesh.vertices[:, 1] - 4.0)), 0.0)
        self.assertAlmostEqual(abs(mesh.volume), 0.68, places=2)
        self.assertTrue(np.all(mesh.area_faces > 1e-12))

    def test_half_line_has_half_the_counterinclination_volume(self):
        data = RoofInput(10.0, 4.0, 1.0, 0.2, num_drains=2)
        whole = RoofCalculator.calculate(data, RoofConfig(counter_slope_extent="whole"))
        half = RoofCalculator.calculate(data, RoofConfig(counter_slope_extent="half"))
        self.assertEqual(whole.v_cementoplast_layer_2_m3, 0.68)
        self.assertEqual(half.v_cementoplast_layer_2_m3, 0.18)

    def test_outside_layout_splits_drains_between_low_borders(self):
        plan = RoofPlan([(0.0, 0.0), (8.0, 0.0), (8.0, 20.0), (0.0, 20.0)], num_drains=3)
        config = RoofConfig(base_slope_direction="width", base_slope_layout="outside",
                            counter_slope_pct=2.0)
        layer_1 = build_cementoplast(plan, config)
        mesh = build_cementoplast_counterinclination(plan, config, layer_1=layer_1)
        self.assertTrue(mesh.is_watertight)
        self.assertAlmostEqual(abs(mesh.volume), 4.58, places=2)
        self.assertAlmostEqual(mesh.bounds[0, 0], 0.0)
        self.assertAlmostEqual(mesh.bounds[1, 0], 8.0)
        self.assertAlmostEqual(mesh.bounds[1, 1], 20.0)

    def test_components_name_both_cementoplast_layer_volumes(self):
        components = generate_3d_components(self.plan, RoofConfig())
        names = [name for name in components if name.startswith("Cementoplast layer")]
        self.assertEqual(len(names), 2)
        self.assertTrue(all("m3 total" in name for name in names))


class RectangleToolTests(unittest.TestCase):
    def setUp(self):
        self.app = RoofModelerApp.__new__(RoofModelerApp)
        self.app.tool_var = Mock()
        self.app.tool_var.get.return_value = "rectangle"
        self.app.dots = [(1.0, 2.0)]
        self.app.edges = []
        self.app.path = []
        self.app.areas = []
        self.app.ventilation_ducts = []
        self.app.mouse_x = 11
        self.app.mouse_y = 2
        self.app._c_to_m = Mock(side_effect=lambda x, y: (x, y))
        self.app._m_to_c = Mock(side_effect=lambda x, y: (x, y))
        self.app._draw = Mock()
        self.app._sync_params = Mock()
        self.app._push_history = Mock()
        self.app.drawing_type_var = Mock()
        self.app.drawing_type_var.get.return_value = "parapet"
        self.app.parapet_height_var = Mock()
        self.app.parapet_height_var.get.return_value = 1.0
        self.app.parapet_top_var = Mock()
        self.app.parapet_top_var.get.return_value = 0.2
        self.app.wall_height_var = Mock()
        self.app.wall_height_var.get.return_value = 2.5
        self.app.duct_height_var = Mock()
        self.app.duct_height_var.get.return_value = 1.0
        self.app.duct_include_top_var = Mock()
        self.app.duct_include_top_var.get.return_value = True
        self.app.pencil_start = None
        self.app.rectangle_start = None
        self.app.rectangle_stage = "width"
        self.app.rectangle_width = None
        self.app.rectangle_input = ""
        self.app.rectangle_created_dot = False
        self.app.hover_dot = None
        self.app._last_synced_dot = None
        self.app.unit_settings = UnitSettings()

    def test_click_sets_rectangle_start(self):
        self.app._on_rectangle_click(1.0, 2.0)

        self.assertEqual(self.app.rectangle_start, 0)
        self.assertEqual(self.app.rectangle_stage, "width")

    def test_second_click_creates_rectangle(self):
        self.app.rectangle_start = 0
        self.app.mouse_x = 6
        self.app.mouse_y = 7

        self.app._on_rectangle_click(6.0, 7.0)

        self.assertEqual(len(self.app.dots), 4)
        self.assertEqual(self.app.dots[0], (1.0, 2.0))
        self.assertEqual(self.app.dots[1], (6.0, 2.0))
        self.assertEqual(self.app.dots[2], (6.0, 7.0))
        self.assertEqual(self.app.dots[3], (1.0, 7.0))
        self.assertEqual(len(self.app.edges), 4)
        self.assertEqual(len(self.app.areas), 1)
        self.assertEqual(self.app.areas[0], [0, 1, 2, 3])
        self.assertIsNone(self.app.rectangle_start)

    def test_enter_finishes_mouse_driven_rectangle(self):
        self.app.rectangle_start = 0
        self.app.mouse_x = 6
        self.app.mouse_y = 7

        self.app._on_rectangle_key(Mock(keysym="Return", char="\r"))

        self.assertEqual(len(self.app.dots), 4)
        self.assertEqual(self.app.dots[3], (1.0, 7.0))
        self.assertEqual(len(self.app.edges), 4)
        self.assertEqual(len(self.app.areas), 1)
        self.assertIsNone(self.app.rectangle_start)

    def test_tab_switches_from_width_to_height(self):
        self.app.rectangle_start = 0

        self.app._on_rectangle_key(Mock(keysym="5", char="5"))
        self.app._on_rectangle_key(Mock(keysym="Tab", char=""))

        self.assertEqual(self.app.rectangle_stage, "height")
        self.assertEqual(self.app.rectangle_width, 5.0)
        self.assertEqual(self.app.rectangle_input, "")

    def test_enter_finishes_typed_rectangle(self):
        self.app.rectangle_start = 0
        self.app.mouse_x = 11
        self.app.mouse_y = 12

        self.app._on_rectangle_key(Mock(keysym="5", char="5"))
        self.app._on_rectangle_key(Mock(keysym="Tab", char=""))
        self.app._on_rectangle_key(Mock(keysym="3", char="3"))
        self.app._on_rectangle_key(Mock(keysym="Return", char="\r"))

        self.assertEqual(len(self.app.dots), 4)
        self.assertEqual(len(self.app.edges), 4)
        self.assertEqual(len(self.app.areas), 1)
        self.assertIsNone(self.app.rectangle_start)

    def test_escape_cancels_rectangle_draft(self):
        self.app.rectangle_start = 0

        result = self.app._on_escape()

        self.assertEqual(result, "break")
        self.assertIsNone(self.app.rectangle_start)
        self.assertEqual(len(self.app.dots), 1)

    def test_escape_removes_created_rectangle_start_dot(self):
        self.app._on_rectangle_click(5.0, 5.0)
        self.assertEqual(len(self.app.dots), 2)
        created_index = self.app.rectangle_start
        self.assertIsNotNone(created_index)

        result = self.app._on_escape()

        self.assertEqual(result, "break")
        self.assertIsNone(self.app.rectangle_start)
        self.assertEqual(len(self.app.dots), 1)
        self.assertNotIn((5.0, 5.0), self.app.dots)


class PencilIntersectionTests(unittest.TestCase):
    def setUp(self):
        self.app = RoofModelerApp.__new__(RoofModelerApp)
        self.app.dots = [
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
            (-1.0, 5.0),
        ]
        self.app.edges = [
            {"a": 0, "b": 1, "edge_type": "line"},
            {"a": 1, "b": 2, "edge_type": "line"},
            {"a": 2, "b": 3, "edge_type": "line"},
            {"a": 3, "b": 0, "edge_type": "line"},
        ]
        self.app.path = []
        self.app.areas = []
        self.app.ventilation_ducts = []
        self.app.pencil_start = 4
        self.app.drawing_type_var = Mock()
        self.app.drawing_type_var.get.return_value = "line"
        self.app.parapet_height_var = Mock(get=Mock(return_value=1.0))
        self.app.parapet_top_var = Mock(get=Mock(return_value=0.2))
        self.app.wall_height_var = Mock(get=Mock(return_value=2.5))
        self.app.duct_height_var = Mock(get=Mock(return_value=1.0))
        self.app.duct_include_top_var = Mock(get=Mock(return_value=True))
        self.app._push_history = Mock()
        self.app._sync_params = Mock()
        self.app._draw = Mock()
        self.app._c_to_m = Mock(side_effect=lambda x, y: (x, y))
        self.app._m_to_c = Mock(side_effect=lambda x, y: (x, y))
        self.app.hover_dot = None
        self.app.hover_edge = None
        self.app.hover_edge_point = None
        self.app.hover_edge_midpoint = False

    def test_pencil_line_splits_two_intersected_edges(self):
        self.app._on_pencil_click(11.0, 5.0)

        # 5 original + clicked endpoint + 2 intersection dots
        self.assertEqual(len(self.app.dots), 8)
        self.assertIn((0.0, 5.0), self.app.dots)
        self.assertIn((10.0, 5.0), self.app.dots)
        self.assertIn((11.0, 5.0), self.app.dots)
        # original 4 edges + 2 from splits + 3 from the sliced new line
        self.assertEqual(len(self.app.edges), 9)
        # both original vertical edges are now split at y=5
        for edge in self.app.edges:
            endpoints = {self.app.dots[edge["a"]], self.app.dots[edge["b"]]}
            self.assertNotEqual(endpoints, {(0.0, 10.0), (0.0, 0.0)})
            self.assertNotEqual(endpoints, {(10.0, 0.0), (10.0, 10.0)})

    def test_pencil_line_splits_single_intersected_edge(self):
        self.app._on_pencil_click(5.0, 5.0)

        # 5 original + clicked endpoint + 1 intersection dot on left edge
        self.assertEqual(len(self.app.dots), 7)
        self.assertIn((0.0, 5.0), self.app.dots)
        self.assertIn((5.0, 5.0), self.app.dots)
        # original 4 edges + 1 from split + 2 from sliced new line
        self.assertEqual(len(self.app.edges), 7)

    def test_diagonal_line_splits_horizontal_edge(self):
        self.app.dots = [
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
            (4.0, -1.0),
        ]
        self.app.pencil_start = 4
        self.app._on_pencil_click(5.0, 5.0)

        # 5 original + clicked endpoint + 1 intersection dot on bottom edge
        self.assertEqual(len(self.app.dots), 7)
        self.assertIn((4.167, 0.0), self.app.dots)
        self.assertIn((5.0, 5.0), self.app.dots)
        # original 4 edges + 1 from split + 2 from sliced new line
        self.assertEqual(len(self.app.edges), 7)


class RectangleIntersectionTests(unittest.TestCase):
    def setUp(self):
        self.app = RoofModelerApp.__new__(RoofModelerApp)
        self.app.dots = [(0.0, 0.0), (10.0, 0.0), (2.0, -2.0)]
        self.app.edges = [
            {"a": 0, "b": 1, "edge_type": "line", "parapet_height": 1.0, "parapet_top_width": 0.2, "wall_height": 2.5, "duct_height": 1.0, "duct_include_top": True},
        ]
        self.app.path = []
        self.app.areas = []
        self.app.ventilation_ducts = []
        self.app.mouse_x = 2
        self.app.mouse_y = -2
        self.app._c_to_m = Mock(side_effect=lambda x, y: (x, y))
        self.app._m_to_c = Mock(side_effect=lambda x, y: (x, y))
        self.app._draw = Mock()
        self.app._sync_params = Mock()
        self.app._push_history = Mock()
        self.app.drawing_type_var = Mock()
        self.app.drawing_type_var.get.return_value = "line"
        self.app.parapet_height_var = Mock(get=Mock(return_value=1.0))
        self.app.parapet_top_var = Mock(get=Mock(return_value=0.2))
        self.app.wall_height_var = Mock(get=Mock(return_value=2.5))
        self.app.duct_height_var = Mock(get=Mock(return_value=1.0))
        self.app.duct_include_top_var = Mock(get=Mock(return_value=True))
        self.app.hover_dot = None
        self.app.hover_edge = None
        self.app.hover_edge_point = None
        self.app.hover_edge_midpoint = False
        self.app.rectangle_start = 2
        self.app.rectangle_stage = "width"
        self.app.rectangle_width = None
        self.app.rectangle_input = ""
        self.app.rectangle_created_dot = False
        self.app.unit_settings = UnitSettings()

    def test_rectangle_splits_one_intersected_edge(self):
        # rectangle (2,-2) -> (12,1) slices the horizontal edge once on its left side
        self.app._create_rectangle(2, 10.0, 3.0)

        # 3 original + 3 new rectangle corners + 1 intersection dot
        self.assertEqual(len(self.app.dots), 7)
        self.assertIn((2.0, 0.0), self.app.dots)
        # original edge is split, left rectangle side is split
        self.assertEqual(len(self.app.edges), 7)

    def test_rectangle_splits_two_intersected_edges(self):
        # rectangle (2,-2) -> (8,2) slices the horizontal edge on both vertical sides
        self.app._create_rectangle(2, 6.0, 4.0)

        # 3 original + 3 new rectangle corners + 2 intersection dots
        self.assertEqual(len(self.app.dots), 8)
        self.assertIn((2.0, 0.0), self.app.dots)
        self.assertIn((8.0, 0.0), self.app.dots)
        # original edge split into 3 + rectangle sides split on both sides
        self.assertEqual(len(self.app.edges), 9)

    def test_rectangle_area_path_includes_intersections(self):
        self.app.drawing_type_var.get.return_value = "parapet"
        self.app._create_rectangle(2, 6.0, 4.0)

        self.assertEqual(len(self.app.areas), 1)
        area_path = self.app.areas[0]
        # area path should go around the rectangle and include the intersection dots
        self.assertEqual(len(area_path), 6)
        # all 6 dots are distinct
        self.assertEqual(len(set(area_path)), 6)


if __name__ == "__main__":
    unittest.main()
