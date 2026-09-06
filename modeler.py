import json
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from shapely.geometry import LineString, Point

from calculator import RoofCalculator
from excel_engine import ExcelEstimateWriter, PriceCatalog
from roof_plan import RoofEdge, RoofPlan

X_AXIS_COLOR = "#ff5555"
Y_AXIS_COLOR = "#55ff55"
RUBBER_DEFAULT = "#ffffff"
RUBBER_SNAP = 0.05  # m


class CollapsibleFrame(ttk.Frame):
    def __init__(self, parent, title, **kwargs):
        super().__init__(parent, **kwargs)
        self.title = title
        self.expanded = True
        self.header = ttk.Button(self, text=f"▼ {title}", command=self.toggle)
        self.header.pack(fill=tk.X)
        self.content = ttk.Frame(self)
        self.content.pack(fill=tk.X, expand=True)

    def toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.content.pack(fill=tk.X, expand=True)
            self.header.configure(text=f"▼ {self.title}")
        else:
            self.content.pack_forget()
            self.header.configure(text=f"▶ {self.title}")


class RoofModelerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Auto Takeoff 3D — Modeler")
        self.root.geometry("1200x800")

        self.scale_var = tk.DoubleVar(value=20.0)
        self.num_drains_var = tk.IntVar(value=2)
        self.tool_var = tk.StringVar(value="pencil")
        self.edge_type_var = tk.StringVar(value="parapet")
        self.parapet_height_var = tk.DoubleVar(value=0.40)
        self.parapet_top_var = tk.DoubleVar(value=0.25)
        self.dot_xy_var = tk.StringVar(value="0.0 ; 0.0")
        self.edge_length_var = tk.StringVar(value="0.0")

        self.pan_x = 50.0
        self.pan_y = 550.0

        # graph
        self.dots: List[Tuple[float, float]] = []
        self.edges: List[Dict[str, Any]] = []
        self.path: List[int] = []
        self.areas: List[List[int]] = []

        self.pencil_start: Optional[int] = None
        self.hover_dot: Optional[int] = None
        self.selected_dot: Optional[int] = None
        self.selected_edge: Optional[int] = None
        self._last_synced_dot: Optional[int] = None
        self._last_synced_edge: Optional[int] = None

        self.mouse_x = 0
        self.mouse_y = 0
        self.canvas_items = []

        self._history: List[Dict[str, Any]] = []
        self._history_pos = -1

        self._build_ui()
        self._push_history()
        self._draw()

        self.root.bind("<Control-z>", self._undo)
        self.root.bind("<Control-Z>", self._undo)
        self.root.bind("<Control-Shift-z>", self._redo)
        self.root.bind("<Control-Shift-Z>", self._redo)
        self.root.bind("<Delete>", self._on_delete)
        self.root.bind("<Escape>", self._on_escape)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        self.canvas.bind("<Motion>", self._on_motion)

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=5)
        top.pack(fill=tk.X)

        ttk.Button(top, text="New", command=self._new).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Load plan", command=self._load_plan).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Save plan", command=self._save_plan).pack(side=tk.LEFT, padx=2)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        for text, value in (("Select", "select"), ("Pencil", "pencil"), ("Eraser", "eraser")):
            ttk.Radiobutton(top, text=text, variable=self.tool_var, value=value, command=self._on_tool_change).pack(side=tk.LEFT, padx=2)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(top, text="Undo (Ctrl+Z)", command=self._undo).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Redo (Ctrl+Shift+Z)", command=self._redo).pack(side=tk.LEFT, padx=2)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(top, text="3D preview", command=self._preview_3d).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Auto generate materials", command=self._auto_generate).pack(side=tk.LEFT, padx=2)

        left = ttk.Frame(self.root, padding=5)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(left, bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)

        # right scrollable panel
        right_outer = ttk.Frame(self.root, width=320)
        right_outer.pack(side=tk.RIGHT, fill=tk.Y)
        right_outer.pack_propagate(False)

        self.right_canvas = tk.Canvas(right_outer, width=320, highlightthickness=0)
        self.right_scroll = ttk.Scrollbar(right_outer, orient=tk.VERTICAL, command=self.right_canvas.yview)
        self.right_canvas.configure(yscrollcommand=self.right_scroll.set)
        self.right_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.right_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.right_canvas.bind("<Configure>", self._on_right_configure)
        self.right_canvas.bind("<Enter>", lambda e: self.right_canvas.focus_set())
        self.right_canvas.bind("<MouseWheel>", self._on_right_scroll)

        self.right_inner = ttk.Frame(self.right_canvas, width=300)
        self.right_inner.bind("<Configure>", self._on_right_configure)
        self.right_canvas.create_window((0, 0), window=self.right_inner, anchor=tk.NW, tags="inner")

        self.view_section = CollapsibleFrame(self.right_inner, "View & drains")
        ttk.Label(self.view_section.content, text="View scale (px/m):").pack(anchor=tk.W)
        ttk.Spinbox(self.view_section.content, from_=5, to=200, textvariable=self.scale_var, width=10).pack(anchor=tk.W)
        ttk.Button(self.view_section.content, text="Apply scale", command=self._draw).pack(anchor=tk.W)
        ttk.Label(self.view_section.content, text="Number of drains:").pack(anchor=tk.W, pady=(10, 0))
        ttk.Spinbox(self.view_section.content, from_=1, to=20, textvariable=self.num_drains_var, width=10).pack(anchor=tk.W)

        self.dot_section = CollapsibleFrame(self.right_inner, "Selected dot")
        ttk.Label(self.dot_section.content, text="X ; Y (m):").pack(anchor=tk.W)
        self.dot_xy_entry = ttk.Entry(self.dot_section.content, textvariable=self.dot_xy_var, width=30)
        self.dot_xy_entry.pack(anchor=tk.W)
        self.dot_xy_entry.bind("<Return>", lambda e: self._apply_to_dot())
        ttk.Button(self.dot_section.content, text="Apply to dot", command=self._apply_to_dot).pack(anchor=tk.W, pady=5)
        ttk.Button(self.dot_section.content, text="Delete dot", command=self._delete_selected_dot).pack(anchor=tk.W)

        self.edge_section = CollapsibleFrame(self.right_inner, "Selected edge")
        ttk.Radiobutton(self.edge_section.content, text="Parapet", variable=self.edge_type_var, value="parapet").pack(anchor=tk.W)
        ttk.Radiobutton(self.edge_section.content, text="Wall (drip cap)", variable=self.edge_type_var, value="wall").pack(anchor=tk.W)
        ttk.Label(self.edge_section.content, text="Parapet height (m):").pack(anchor=tk.W, pady=(10, 0))
        ttk.Entry(self.edge_section.content, textvariable=self.parapet_height_var, width=15).pack(anchor=tk.W)
        ttk.Label(self.edge_section.content, text="Parapet top width (m):").pack(anchor=tk.W)
        ttk.Entry(self.edge_section.content, textvariable=self.parapet_top_var, width=15).pack(anchor=tk.W)
        ttk.Button(self.edge_section.content, text="Apply to edge", command=self._apply_to_edge).pack(anchor=tk.W, pady=5)
        ttk.Label(self.edge_section.content, text="Length (m):").pack(anchor=tk.W, pady=(10, 0))
        self.edge_length_entry = ttk.Entry(self.edge_section.content, textvariable=self.edge_length_var, width=15)
        self.edge_length_entry.pack(anchor=tk.W)
        self.edge_length_entry.bind("<Return>", lambda e: self._apply_to_edge_length())
        ttk.Button(self.edge_section.content, text="Apply to edge length", command=self._apply_to_edge_length).pack(anchor=tk.W, pady=5)
        ttk.Button(self.edge_section.content, text="Delete edge", command=self._delete_selected_edge).pack(anchor=tk.W)

        self.actions_section = CollapsibleFrame(self.right_inner, "Actions")
        ttk.Button(self.actions_section.content, text="Close polygon", command=self._close_polygon).pack(anchor=tk.W, pady=2)
        ttk.Button(self.actions_section.content, text="Select template", command=self._select_template).pack(anchor=tk.W, pady=2)
        self.template_path_var = tk.StringVar(value="")
        ttk.Entry(self.actions_section.content, textvariable=self.template_path_var, width=30).pack(anchor=tk.W)

        self.areas_section = CollapsibleFrame(self.right_inner, "Areas")
        self.areas_text = tk.Text(self.areas_section.content, height=8, wrap=tk.WORD)
        self.areas_text.pack(fill=tk.BOTH, expand=True)
        self.total_area_var = tk.StringVar(value="Total: 0.00 m²")
        ttk.Label(self.areas_section.content, textvariable=self.total_area_var).pack(anchor=tk.W)

        self.info_section = CollapsibleFrame(self.right_inner, "Info")
        self.info_text = tk.Text(self.info_section.content, height=10, wrap=tk.WORD)
        self.info_text.pack(fill=tk.BOTH, expand=True)

        self.view_section.pack(fill=tk.X, pady=3, padx=5)
        self.actions_section.pack(fill=tk.X, pady=3, padx=5)
        self.areas_section.pack(fill=tk.X, pady=3, padx=5)
        self.info_section.pack(fill=tk.X, pady=3, padx=5)

    def _on_right_configure(self, event=None):
        self.right_canvas.itemconfig("inner", width=self.right_canvas.winfo_width())
        self.right_canvas.configure(scrollregion=self.right_canvas.bbox("all"))

    def _on_right_scroll(self, event):
        self.right_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_tool_change(self):
        self.selected_dot = None
        self.selected_edge = None
        self._sync_params()
        self._draw()

    def _m_to_c(self, x: float, y: float) -> Tuple[float, float]:
        scale = self.scale_var.get()
        return (self.pan_x + x * scale, self.pan_y - y * scale)

    def _c_to_m(self, cx: float, cy: float) -> Tuple[float, float]:
        scale = self.scale_var.get()
        return ((cx - self.pan_x) / scale, (self.pan_y - cy) / scale)

    def _push_history(self):
        if self._history_pos < len(self._history) - 1:
            self._history = self._history[: self._history_pos + 1]
        self._history.append({
            "dots": list(self.dots),
            "edges": [dict(e) for e in self.edges],
            "path": list(self.path),
            "areas": [list(a) for a in self.areas],
            "pencil_start": self.pencil_start,
        })
        self._history_pos = len(self._history) - 1

    def _undo(self, event=None):
        if self._history_pos > 0:
            self._history_pos -= 1
            self._restore_history()
        return "break"

    def _redo(self, event=None):
        if self._history_pos < len(self._history) - 1:
            self._history_pos += 1
            self._restore_history()
        return "break"

    def _restore_history(self):
        snap = self._history[self._history_pos]
        self.dots = [tuple(p) for p in snap["dots"]]
        self.edges = [dict(e) for e in snap["edges"]]
        self.path = list(snap["path"])
        self.areas = [list(a) for a in snap["areas"]]
        self.pencil_start = snap["pencil_start"]
        self.selected_dot = None
        self.selected_edge = None
        self._sync_params()
        self._draw()

    def _new(self):
        self.dots = []
        self.edges = []
        self.path = []
        self.areas = []
        self.pencil_start = None
        self.selected_dot = None
        self.selected_edge = None
        self.pan_x = 50.0
        self.pan_y = 550.0
        self._push_history()
        self._sync_params()
        self._draw()

    def _on_mousewheel(self, event):
        mx, my = event.x, event.y
        wx, wy = self._c_to_m(mx, my)
        current = self.scale_var.get()
        step = (event.delta / 120.0) * 2.0
        new_val = max(5.0, min(200.0, current + step))
        self.scale_var.set(new_val)
        self.pan_x = mx - wx * new_val
        self.pan_y = my + wy * new_val
        self._draw()

    def _on_motion(self, event):
        self.mouse_x, self.mouse_y = event.x, event.y
        self.hover_dot = self._find_nearest_dot(event.x, event.y)
        self._draw()

    def _on_click(self, event):
        tool = self.tool_var.get()
        if tool == "pencil":
            self._on_pencil_click(event.x, event.y)
        elif tool == "eraser":
            self._on_eraser_click(event.x, event.y)
        else:
            self._on_select_click(event.x, event.y)

    def _on_escape(self, event=None):
        if self.pencil_start is not None:
            self.pencil_start = None
            self._draw()
        return "break"

    def _on_delete(self, event=None):
        if self.selected_dot is not None:
            self._erase_dot(self.selected_dot)
        elif self.selected_edge is not None:
            self._delete_edge(self.selected_edge)
        return "break"

    def _on_pencil_click(self, cx: float, cy: float):
        near = self._find_nearest_dot(cx, cy)

        if self.pencil_start is None:
            if near is not None:
                self.pencil_start = near
                if not self.path or near not in self.path:
                    # start a fresh path from this dot
                    self.path = [near]
            else:
                x, y = self._c_to_m(cx, cy)
                self.dots.append((round(x, 3), round(y, 3)))
                new_idx = len(self.dots) - 1
                self.pencil_start = new_idx
                self.path = [new_idx]
            self._push_history()
            self._sync_params()
            self._draw()
            return

        # clicking the same dot cancels (same as Esc)
        if near is not None and near == self.pencil_start:
            self.pencil_start = None
            self._push_history()
            self._sync_params()
            self._draw()
            return

        if near is not None:
            a, b = self.pencil_start, near
            # if the target dot is already in use, connect and then release the pencil
            target_degree = sum(1 for e in self.edges if near in (e["a"], e["b"]))
            self.edges.append({
                "a": a,
                "b": b,
                "edge_type": "parapet",
                "parapet_height": 0.40,
                "parapet_top_width": 0.25,
            })
            self._insert_into_path(self.pencil_start, near)
            self.pencil_start = near if target_degree == 0 else None
        else:
            x, y = self._c_to_m(cx, cy)
            self.dots.append((round(x, 3), round(y, 3)))
            new_idx = len(self.dots) - 1
            a = self.pencil_start
            self.edges.append({
                "a": a,
                "b": new_idx,
                "edge_type": "parapet",
                "parapet_height": 0.40,
                "parapet_top_width": 0.25,
            })
            self._insert_into_path(self.pencil_start, new_idx)
            self.pencil_start = new_idx

        # check if current path has become a closed loop
        if len(self.path) >= 3 and self._path_is_closed():
            self.areas.append(list(self.path))
            self.path = []
            self.pencil_start = None

        self._push_history()
        self._sync_params()
        self._draw()

    def _insert_into_path(self, start_idx: int, new_idx: int):
        if new_idx in self.path:
            return
        if start_idx in self.path:
            pos = self.path.index(start_idx)
            self.path.insert(pos + 1, new_idx)
        else:
            self.path = [start_idx, new_idx]

    def _edge_exists(self, a: int, b: int) -> bool:
        return any({e["a"], e["b"]} == {a, b} for e in self.edges)

    def _path_is_closed(self) -> bool:
        n = len(self.path)
        if n < 3:
            return False
        for i in range(n):
            a = self.path[i]
            b = self.path[(i + 1) % n]
            if not self._edge_exists(a, b):
                return False
        return True

    def _on_eraser_click(self, cx: float, cy: float):
        pidx = self._find_nearest_dot(cx, cy)
        if pidx is not None:
            self._erase_dot(pidx)
        else:
            eidx = self._find_nearest_edge(cx, cy)
            if eidx is not None:
                self._delete_edge(eidx)

    def _on_select_click(self, cx: float, cy: float):
        pidx = self._find_nearest_dot(cx, cy)
        if pidx is not None:
            self.selected_dot = pidx
            self.selected_edge = None
        else:
            eidx = self._find_nearest_edge(cx, cy)
            if eidx is not None:
                self.selected_dot = None
                self.selected_edge = eidx
            else:
                self.selected_dot = None
                self.selected_edge = None
        self._sync_params()
        self._draw()

    def _find_nearest_dot(self, cx: float, cy: float, threshold_m: float = 0.3) -> Optional[int]:
        x, y = self._c_to_m(cx, cy)
        p = Point(x, y)
        best = None
        best_dist = float("inf")
        for i, pt in enumerate(self.dots):
            d = p.distance(Point(pt))
            if d < best_dist:
                best_dist = d
                best = i
        return best if best_dist <= threshold_m else None

    def _find_nearest_edge(self, cx: float, cy: float, threshold_m: float = 0.3) -> Optional[int]:
        x, y = self._c_to_m(cx, cy)
        p = Point(x, y)
        best = None
        best_dist = float("inf")
        for i, e in enumerate(self.edges):
            p1 = self.dots[e["a"]]
            p2 = self.dots[e["b"]]
            d = p.distance(LineString([p1, p2]))
            if d < best_dist:
                best_dist = d
                best = i
        return best if best_dist <= threshold_m else None

    def _apply_to_dot(self):
        if self.selected_dot is None:
            return
        raw = self.dot_xy_var.get()
        parts = [p.strip() for p in raw.split(";")]
        if len(parts) != 2:
            messagebox.showwarning("Invalid input", "Use format: X ; Y")
            return
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            messagebox.showwarning("Invalid input", "X and Y must be numbers.")
            return
        self.dots[self.selected_dot] = (round(x, 3), round(y, 3))
        self.dot_xy_var.set(f"{x:.3f} ; {y:.3f}")
        self._last_synced_dot = self.selected_dot
        self._push_history()
        self._sync_params()
        self._draw()

    def _delete_selected_dot(self):
        if self.selected_dot is not None:
            self._erase_dot(self.selected_dot)

    def _apply_to_edge(self):
        if self.selected_edge is None:
            return
        e = self.edges[self.selected_edge]
        e["edge_type"] = self.edge_type_var.get()
        e["parapet_height"] = self.parapet_height_var.get()
        e["parapet_top_width"] = self.parapet_top_var.get()
        self._push_history()
        self._draw()

    def _apply_to_edge_length(self):
        if self.selected_edge is None:
            return
        try:
            new_length = float(self.edge_length_var.get())
        except ValueError:
            messagebox.showwarning("Invalid input", "Edge length must be a number.")
            return
        if new_length <= 0:
            messagebox.showwarning("Invalid input", "Edge length must be positive.")
            return

        e = self.edges[self.selected_edge]
        a = e["a"]
        b = e["b"]
        p1 = self.dots[a]
        p2 = self.dots[b]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        cur_len = math.hypot(dx, dy)
        if cur_len == 0:
            return
        new_x = p1[0] + (dx / cur_len) * new_length
        new_y = p1[1] + (dy / cur_len) * new_length
        self.dots[b] = (round(new_x, 3), round(new_y, 3))
        self.edge_length_var.set(f"{new_length:.3f}")
        self._last_synced_edge = self.selected_edge
        self._push_history()
        self._sync_params()
        self._draw()

    def _delete_selected_edge(self):
        if self.selected_edge is not None:
            self._delete_edge(self.selected_edge)

    def _delete_edge(self, eidx: int):
        if not (0 <= eidx < len(self.edges)):
            return
        e = self.edges.pop(eidx)
        a, b = e["a"], e["b"]

        # remove endpoint dots only when no other edge uses them
        deg_a = sum(1 for ed in self.edges if a in (ed["a"], ed["b"]))
        deg_b = sum(1 for ed in self.edges if b in (ed["a"], ed["b"]))

        if deg_a == 0:
            self._delete_dot(a)
            b = b - 1 if b > a else b
        if deg_b == 0:
            self._delete_dot(b)

        self.selected_dot = None
        self.selected_edge = None
        self._push_history()
        self._sync_params()
        self._draw()

    def _erase_dot(self, idx: int):
        to_remove = [i for i, e in enumerate(self.edges) if idx in (e["a"], e["b"])]
        for i in reversed(to_remove):
            self.edges.pop(i)
        self._delete_dot(idx)
        self._push_history()
        self._sync_params()
        self._draw()

    def _delete_dot(self, idx: int):
        if not (0 <= idx < len(self.dots)):
            return
        self.dots.pop(idx)
        for e in self.edges:
            if e["a"] > idx:
                e["a"] -= 1
            if e["b"] > idx:
                e["b"] -= 1
        # reindex path, areas, pencil, selection
        self.path = [(i - 1 if i > idx else i) for i in self.path if i != idx]
        self.areas = [[(j - 1 if j > idx else j) for j in a if j != idx] for a in self.areas]
        self.areas = [a for a in self.areas if len(a) >= 3]

        if self.pencil_start == idx:
            self.pencil_start = None
        elif self.pencil_start is not None and self.pencil_start > idx:
            self.pencil_start -= 1
        if self.hover_dot is not None:
            if self.hover_dot == idx:
                self.hover_dot = None
            elif self.hover_dot > idx:
                self.hover_dot -= 1
        if self._last_synced_dot is not None:
            self._last_synced_dot = (self._last_synced_dot - 1 if self._last_synced_dot > idx else self._last_synced_dot) if self._last_synced_dot != idx else None

    def _sync_params(self):
        self.dot_section.pack_forget()
        self.edge_section.pack_forget()

        dot_has_focus = self.dot_xy_entry == self.root.focus_get()
        edge_has_focus = self.edge_length_entry == self.root.focus_get()

        if self.selected_dot is not None:
            p = self.dots[self.selected_dot]
            if self.selected_dot != self._last_synced_dot or not dot_has_focus:
                self.dot_xy_var.set(f"{p[0]:.3f} ; {p[1]:.3f}")
            self._last_synced_dot = self.selected_dot
            self.dot_section.pack(fill=tk.X, pady=3, padx=5)

        if self.selected_edge is not None:
            e = self.edges[self.selected_edge]
            p1 = self.dots[e["a"]]
            p2 = self.dots[e["b"]]
            length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            self.edge_type_var.set(e["edge_type"])
            self.parapet_height_var.set(e["parapet_height"])
            self.parapet_top_var.set(e["parapet_top_width"])
            if self.selected_edge != self._last_synced_edge or not edge_has_focus:
                self.edge_length_var.set(f"{length:.3f}")
            self._last_synced_edge = self.selected_edge
            self.dot_xy_var.set("0.0 ; 0.0")
            self.edge_section.pack(fill=tk.X, pady=3, padx=5)
        else:
            self.dot_xy_var.set("0.0 ; 0.0")
            self.edge_length_var.set("0.0")

        self.actions_section.pack_forget()
        self.areas_section.pack_forget()
        self.info_section.pack_forget()
        self.actions_section.pack(fill=tk.X, pady=3, padx=5)
        self.areas_section.pack(fill=tk.X, pady=3, padx=5)
        self.info_section.pack(fill=tk.X, pady=3, padx=5)
        self._on_right_configure()

    def _close_polygon(self):
        if len(self.path) < 3:
            messagebox.showwarning("Too few points", "At least 3 dots are needed to close an area.")
            return
        a = self.path[-1]
        b = self.path[0]
        if a != b:
            self.edges.append({
                "a": a,
                "b": b,
                "edge_type": "parapet",
                "parapet_height": 0.40,
                "parapet_top_width": 0.25,
            })
        self.areas.append(list(self.path))
        self.path = []
        self.pencil_start = None
        self._push_history()
        self._sync_params()
        self._draw()

    def _build_plan_for_area(self, area_path: List[int]) -> Optional[RoofPlan]:
        if len(area_path) < 3:
            return None
        points = [self.dots[i] for i in area_path]
        n = len(area_path)
        plan_edges = []
        for k in range(n):
            a = area_path[k]
            b = area_path[(k + 1) % n]
            p1 = self.dots[a]
            p2 = self.dots[b]
            props = {"edge_type": "parapet", "parapet_height": 0.40, "parapet_top_width": 0.25}
            for e in self.edges:
                if {e["a"], e["b"]} == {a, b}:
                    props = {
                        "edge_type": e["edge_type"],
                        "parapet_height": e["parapet_height"],
                        "parapet_top_width": e["parapet_top_width"],
                    }
                    break
            plan_edges.append(RoofEdge(p1=p1, p2=p2, **props))
        return RoofPlan(points=points, edges=plan_edges, num_drains=self.num_drains_var.get())

    def _calculate_areas(self) -> List[Dict[str, Any]]:
        results = []
        for area_path in self.areas:
            plan = self._build_plan_for_area(area_path)
            if plan and plan.is_valid:
                q = RoofCalculator.calculate_from_plan(plan)
                results.append({
                    "area": q.s_clear,
                    "perimeter": q.p_perimeter,
                    "parapet": q.l_rail_top,
                    "drip": q.l_drip_cap,
                })
            else:
                results.append({"area": 0.0, "perimeter": 0.0, "parapet": 0.0, "drip": 0.0})
        return results

    def _select_template(self):
        cash = Path("data/cash").resolve()
        file = filedialog.askopenfilename(
            title="Select DEVIZ template",
            initialdir=str(cash) if cash.is_dir() else str(Path.cwd()),
            filetypes=[("Excel files", "*.xlsx")],
        )
        if file:
            self.template_path_var.set(file)

    def _auto_generate(self):
        if not self.areas:
            messagebox.showwarning("No roof", "Please draw and close at least one roof area first.")
            return

        template = self.template_path_var.get()
        if not template or not Path(template).is_file():
            messagebox.showwarning("No template", "Please select a DEVIZ Excel template.")
            return

        price_path = Path("data/price.xlsx").resolve()
        catalog = PriceCatalog(price_path) if price_path.is_file() else None

        # generate one file per area
        outputs = []
        for idx, area_path in enumerate(self.areas):
            plan = self._build_plan_for_area(area_path)
            if plan is None or not plan.is_valid:
                continue
            quantities = RoofCalculator.calculate_from_plan(plan)

            out = filedialog.asksaveasfilename(
                title=f"Save estimate for area {idx + 1}",
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx")],
            )
            if not out:
                continue

            writer = ExcelEstimateWriter(template, catalog=catalog)
            sem_sheet = self._find_sheet(writer.wb.sheetnames, "sem")
            client_sheet = self._find_sheet(writer.wb.sheetnames, "client")

            if sem_sheet:
                writer.write(quantities, sheet=sem_sheet, overwrite_formulas=True, save=False)
            if client_sheet:
                writer.write(quantities, sheet=client_sheet, overwrite_formulas=False, save=False)
            writer.save(out)
            outputs.append(out)

        if outputs:
            messagebox.showinfo("Estimates generated", "\n".join(outputs))

    def _find_sheet(self, names, needle):
        for name in names:
            if needle.lower() in name.lower():
                return name
        return None

    def _preview_3d(self):
        if not self.areas:
            messagebox.showwarning("No roof", "Draw and close an area first.")
            return
        # preview the first area for now
        plan = self._build_plan_for_area(self.areas[0])
        if plan is None or not plan.is_valid:
            messagebox.showwarning("No roof", "First area is not valid.")
            return

        faces = plan.to_3d_faces()
        if not faces:
            messagebox.showwarning("No faces", "Could not build a 3D mesh.")
            return

        fig = plt.figure()
        ax = fig.add_subplot(111, projection="3d")

        colors = []
        for face in faces:
            z_vals = [p[2] for p in face]
            colors.append("#3498db" if max(z_vals) > 0.01 else "#2ecc71")

        poly3d = Poly3DCollection(faces, alpha=0.7, facecolors=colors, edgecolors="k")
        ax.add_collection3d(poly3d)

        minx, miny, maxx, maxy = plan.bounds
        ax.set_xlim(minx - 1, maxx + 1)
        ax.set_ylim(miny - 1, maxy + 1)
        zmax = max((max(p[2] for p in f) for f in faces), default=1)
        ax.set_zlim(0, zmax + 1)
        ax.set_xlabel("X (m)")
        ax.set_ylabel("Y (m)")
        ax.set_zlabel("Z (m)")
        ax.set_title("Roof 3D preview")
        plt.show(block=False)

    def _save_plan(self):
        file = filedialog.asksaveasfilename(title="Save roof plan", defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if file:
            data = {
                "dots": [list(p) for p in self.dots],
                "edges": list(self.edges),
                "path": self.path,
                "areas": self.areas,
                "num_drains": self.num_drains_var.get(),
            }
            with open(file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_plan(self):
        file = filedialog.askopenfilename(title="Load roof plan", filetypes=[("JSON files", "*.json")])
        if file:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.dots = [tuple(p) for p in data.get("dots", [])]
            self.edges = [dict(e) for e in data.get("edges", [])]
            self.path = list(data.get("path", []))
            self.areas = [list(a) for a in data.get("areas", [])]
            self.num_drains_var.set(data.get("num_drains", 2))
            self.pencil_start = None
            self.selected_dot = None
            self.selected_edge = None
            self._push_history()
            self._sync_params()
            self._draw()

    def _draw(self):
        for item in self.canvas_items:
            self.canvas.delete(item)
        self.canvas_items = []

        # grid
        for i in range(-20, 120):
            cx, _ = self._m_to_c(i, 0)
            self.canvas_items.append(self.canvas.create_line(cx, -2000, cx, 2000, fill="#333333", tags="grid"))
            if 0 <= i <= 110:
                self.canvas_items.append(self.canvas.create_text(cx + 5, self.pan_y + 5, text=str(i), fill="gray", anchor=tk.NW, font=("", 8)))
        for i in range(-20, 100):
            _, cy = self._m_to_c(0, i)
            self.canvas_items.append(self.canvas.create_line(-2000, cy, 4000, cy, fill="#333333", tags="grid"))
            if 0 <= i <= 90:
                self.canvas_items.append(self.canvas.create_text(self.pan_x + 5, cy - 12, text=str(i), fill="gray", anchor=tk.NW, font=("", 8)))

        # axes
        self.canvas_items.append(self.canvas.create_line(-2000, self.pan_y, 4000, self.pan_y, fill=X_AXIS_COLOR, width=2))
        self.canvas_items.append(self.canvas.create_line(self.pan_x, -2000, self.pan_x, 2000, fill=Y_AXIS_COLOR, width=2))
        self.canvas_items.append(self.canvas.create_text(self.pan_x + 40, self.pan_y - 10, text="X", fill=X_AXIS_COLOR, font=("", 10, "bold")))
        self.canvas_items.append(self.canvas.create_text(self.pan_x + 10, self.pan_y - 40, text="Y", fill=Y_AXIS_COLOR, font=("", 10, "bold")))

        # edges
        for i, e in enumerate(self.edges):
            p1 = self.dots[e["a"]]
            p2 = self.dots[e["b"]]
            color = "#e74c3c" if e["edge_type"] == "wall" else "#3498db"
            if self.selected_edge == i:
                color = "#f1c40f"
            c1 = self._m_to_c(*p1)
            c2 = self._m_to_c(*p2)
            self.canvas_items.append(self.canvas.create_line(c1[0], c1[1], c2[0], c2[1], fill=color, width=3, tags="edge"))
            mid_x = (c1[0] + c2[0]) / 2
            mid_y = (c1[1] + c2[1]) / 2
            length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            self.canvas_items.append(self.canvas.create_text(mid_x, mid_y - 10, text=f"{length:.2f}m", fill="white", font=("", 8)))

        # dots
        for i, p in enumerate(self.dots):
            cx, cy = self._m_to_c(*p)
            if self.hover_dot == i or self.pencil_start == i:
                self.canvas_items.append(self.canvas.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, fill="#2ecc71", outline="white"))
            elif self.selected_dot == i:
                self.canvas_items.append(self.canvas.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, fill="#f1c40f", outline="white"))
            else:
                self.canvas_items.append(self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="white", outline="black"))
            self.canvas_items.append(self.canvas.create_text(cx + 8, cy - 8, text=f"P{i+1} ({p[0]:.2f},{p[1]:.2f})", fill="white", anchor=tk.NW, font=("", 8)))

        # hover coordinate label above the dot
        if self.hover_dot is not None:
            p = self.dots[self.hover_dot]
            cx, cy = self._m_to_c(*p)
            self.canvas_items.append(self.canvas.create_text(cx, cy - 18, text=f"{p[0]:.2f} ; {p[1]:.2f}", fill="#f1c40f", anchor=tk.S, font=("", 9, "bold")))

        # rubber band
        if self.pencil_start is not None and self.tool_var.get() == "pencil":
            p1 = self.dots[self.pencil_start]
            p2_m = self._c_to_m(self.mouse_x, self.mouse_y)
            c1 = self._m_to_c(*p1)
            color = RUBBER_DEFAULT
            if abs(p2_m[1] - p1[1]) < RUBBER_SNAP:
                color = X_AXIS_COLOR
            elif abs(p2_m[0] - p1[0]) < RUBBER_SNAP:
                color = Y_AXIS_COLOR
            self.canvas_items.append(self.canvas.create_line(c1[0], c1[1], self.mouse_x, self.mouse_y, fill=color, width=2, dash=(4, 4)))

        # areas list + total
        self.areas_text.delete("1.0", tk.END)
        area_results = self._calculate_areas()
        total = 0.0
        for idx, r in enumerate(area_results, 1):
            self.areas_text.insert(tk.END, f"Area {idx}: {r['area']} m², P={r['perimeter']} m\n")
            total += r["area"]
        self.total_area_var.set(f"Total: {total:.2f} m²")

        # info
        self.info_text.delete("1.0", tk.END)
        tool = self.tool_var.get()
        info = (
            f"Tool: {tool}\n"
            f"Dots: {len(self.dots)}\n"
            f"Lines: {len(self.edges)}\n"
            f"Current path: {len(self.path)}\n"
            f"Areas: {len(self.areas)}\n"
            f"Total area: {total:.2f} m²\n"
        )
        if self.selected_dot is not None:
            p = self.dots[self.selected_dot]
            info += f"\nSelected dot: P{self.selected_dot + 1} ({p[0]:.2f} ; {p[1]:.2f})\n"
        elif self.selected_edge is not None:
            e = self.edges[self.selected_edge]
            p1, p2 = self.dots[e["a"]], self.dots[e["b"]]
            length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            info += f"\nSelected edge: {e['edge_type']}, {length:.2f} m\n"
        self.info_text.insert(tk.END, info)


def main():
    root = tk.Tk()
    app = RoofModelerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
