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
        self.point_xy_var = tk.StringVar(value="0.0 ; 0.0")
        self.edge_length_var = tk.StringVar(value="0.0")

        self.pan_x = 50.0
        self.pan_y = 550.0

        self.plan = RoofPlan(points=[])
        self.closed = False
        self.selected_edge: Optional[int] = None
        self.selected_point: Optional[int] = None
        self._last_synced_point: Optional[int] = None
        self._last_synced_edge: Optional[int] = None
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
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=5)
        top.pack(fill=tk.X)

        ttk.Button(top, text="New", command=self._new).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Load plan", command=self._load_plan).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Save plan", command=self._save_plan).pack(side=tk.LEFT, padx=2)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        for text, value in (
            ("Select", "select"),
            ("Pencil", "pencil"),
            ("Eraser", "eraser"),
        ):
            ttk.Radiobutton(
                top,
                text=text,
                variable=self.tool_var,
                value=value,
                command=self._on_tool_change,
            ).pack(side=tk.LEFT, padx=2)

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

        self.edge_section = CollapsibleFrame(self.right_inner, "Selected edge")
        ttk.Radiobutton(self.edge_section.content, text="Parapet", variable=self.edge_type_var, value="parapet").pack(anchor=tk.W)
        ttk.Radiobutton(self.edge_section.content, text="Wall (drip cap)", variable=self.edge_type_var, value="wall").pack(anchor=tk.W)
        ttk.Label(self.edge_section.content, text="Parapet height (m):").pack(anchor=tk.W, pady=(10, 0))
        ttk.Entry(self.edge_section.content, textvariable=self.parapet_height_var, width=15).pack(anchor=tk.W)
        ttk.Label(self.edge_section.content, text="Parapet top width (m):").pack(anchor=tk.W)
        ttk.Entry(self.edge_section.content, textvariable=self.parapet_top_var, width=15).pack(anchor=tk.W)
        ttk.Button(self.edge_section.content, text="Apply to selected edge", command=self._apply_to_selected).pack(anchor=tk.W, pady=5)
        ttk.Button(self.edge_section.content, text="Apply to all edges", command=self._apply_to_all).pack(anchor=tk.W)

        self.point_section = CollapsibleFrame(self.right_inner, "Selected point position")
        ttk.Label(self.point_section.content, text="X ; Y (m):").pack(anchor=tk.W)
        self.point_xy_entry = ttk.Entry(self.point_section.content, textvariable=self.point_xy_var, width=30)
        self.point_xy_entry.pack(anchor=tk.W)
        self.point_xy_entry.bind("<Return>", lambda e: self._apply_to_point())
        ttk.Button(self.point_section.content, text="Apply to point", command=self._apply_to_point).pack(anchor=tk.W, pady=5)
        ttk.Button(self.point_section.content, text="Delete selected point", command=self._delete_selected_point).pack(anchor=tk.W)

        self.edge_length_section = CollapsibleFrame(self.right_inner, "Selected edge length")
        ttk.Label(self.edge_length_section.content, text="Length (m):").pack(anchor=tk.W)
        self.edge_length_entry = ttk.Entry(self.edge_length_section.content, textvariable=self.edge_length_var, width=15)
        self.edge_length_entry.pack(anchor=tk.W)
        self.edge_length_entry.bind("<Return>", lambda e: self._apply_to_edge_length())
        ttk.Button(self.edge_length_section.content, text="Apply to edge length", command=self._apply_to_edge_length).pack(anchor=tk.W, pady=5)
        ttk.Button(self.edge_length_section.content, text="Delete selected line", command=self._delete_selected_line).pack(anchor=tk.W)

        self.actions_section = CollapsibleFrame(self.right_inner, "Actions")
        ttk.Button(self.actions_section.content, text="Close polygon", command=self._close_polygon).pack(anchor=tk.W, pady=2)
        ttk.Button(self.actions_section.content, text="Select template", command=self._select_template).pack(anchor=tk.W, pady=2)
        self.template_path_var = tk.StringVar(value="")
        ttk.Entry(self.actions_section.content, textvariable=self.template_path_var, width=30).pack(anchor=tk.W)

        self.info_section = CollapsibleFrame(self.right_inner, "Info")
        self.info_text = tk.Text(self.info_section.content, height=12, wrap=tk.WORD)
        self.info_text.pack(fill=tk.BOTH, expand=True)

        # initial pack
        self.view_section.pack(fill=tk.X, pady=3, padx=5)
        self.actions_section.pack(fill=tk.X, pady=3, padx=5)
        self.info_section.pack(fill=tk.X, pady=3, padx=5)

    def _on_right_configure(self, event=None):
        self.right_canvas.itemconfig("inner", width=self.right_canvas.winfo_width())
        self.right_canvas.configure(scrollregion=self.right_canvas.bbox("all"))

    def _on_right_scroll(self, event):
        self.right_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_tool_change(self):
        self.selected_edge = None
        self.selected_point = None
        self._sync_params()
        self._draw()

    def _m_to_c(self, x: float, y: float) -> Tuple[float, float]:
        scale = self.scale_var.get()
        cx = self.pan_x + x * scale
        cy = self.pan_y - y * scale
        return (cx, cy)

    def _c_to_m(self, cx: float, cy: float) -> Tuple[float, float]:
        scale = self.scale_var.get()
        x = (cx - self.pan_x) / scale
        y = (self.pan_y - cy) / scale
        return (x, y)

    def _push_history(self):
        if self._history_pos < len(self._history) - 1:
            self._history = self._history[: self._history_pos + 1]
        self._history.append({"plan": self.plan.to_dict(), "closed": self.closed})
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
        self.plan = RoofPlan.from_dict(snap["plan"])
        self.closed = snap["closed"]
        self.selected_edge = None
        self.selected_point = None
        self.num_drains_var.set(self.plan.num_drains)
        self._sync_params()
        self._draw()

    def _new(self):
        self.plan = RoofPlan(points=[], num_drains=self.num_drains_var.get())
        self.closed = False
        self.selected_edge = None
        self.selected_point = None
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

    def _on_click(self, event):
        tool = self.tool_var.get()
        if tool == "pencil":
            self._add_point(event.x, event.y)
        elif tool == "eraser":
            self._erase_at(event.x, event.y)
        else:  # select
            self._select_nearest(event.x, event.y)

    def _on_delete(self, event=None):
        if self.selected_point is not None:
            self._delete_point(self.selected_point)
        elif self.selected_edge is not None:
            self._delete_line(self.selected_edge)
        return "break"

    def _add_point(self, cx: float, cy: float):
        if self.closed:
            return
        x, y = self._c_to_m(cx, cy)
        self.plan.points.append((round(x, 3), round(y, 3)))
        self.plan.num_drains = self.num_drains_var.get()
        self._rebuild_edges()
        self._push_history()
        self._draw()

    def _erase_at(self, cx: float, cy: float):
        pidx = self._find_nearest_point(cx, cy)
        if pidx is not None:
            self._delete_point(pidx)
        else:
            eidx = self._find_nearest_edge(cx, cy)
            if eidx is not None:
                self._delete_line(eidx)

    def _delete_point(self, idx: int):
        if 0 <= idx < len(self.plan.points):
            self.plan.points.pop(idx)
            self._rebuild_edges()
            if self.closed and len(self.plan.points) < 3:
                self.closed = False
            self.selected_edge = None
            self.selected_point = None
            self._push_history()
            self._sync_params()
            self._draw()

    def _delete_line(self, eidx: int):
        n = len(self.plan.points)
        if n < 5:
            messagebox.showwarning("Too few points", "At least 5 points are needed to delete a line and its two dots.")
            return
        idx1 = eidx
        idx2 = (eidx + 1) % n
        # remove the two endpoints of the selected edge, keeping order stable
        first = max(idx1, idx2)
        self.plan.points.pop(first)
        second = min(idx1, idx2)
        self.plan.points.pop(second)
        self._rebuild_edges()
        if len(self.plan.points) < 3:
            self.closed = False
        self.selected_edge = None
        self.selected_point = None
        self._last_synced_point = None
        self._last_synced_edge = None
        self._push_history()
        self._sync_params()
        self._draw()

    def _rebuild_edges(self):
        edges = []
        n = len(self.plan.points)
        for i in range(n):
            p1 = self.plan.points[i]
            p2 = self.plan.points[(i + 1) % n]
            if i < len(self.plan.edges):
                spec = self.plan.edges[i]
                edges.append(
                    RoofEdge(
                        p1=p1,
                        p2=p2,
                        edge_type=spec.edge_type,
                        parapet_height=spec.parapet_height,
                        parapet_top_width=spec.parapet_top_width,
                    )
                )
            else:
                edges.append(RoofEdge(p1=p1, p2=p2))
        self.plan.edges = edges

    def _find_nearest_point(self, cx: float, cy: float, threshold_m: float = 0.3) -> Optional[int]:
        x, y = self._c_to_m(cx, cy)
        p = Point(x, y)
        best_idx = None
        best_dist = float("inf")
        for i, pt in enumerate(self.plan.points):
            d = p.distance(Point(pt))
            if d < best_dist:
                best_dist = d
                best_idx = i
        if best_dist <= threshold_m:
            return best_idx
        return None

    def _find_nearest_edge(self, cx: float, cy: float, threshold_m: float = 0.3) -> Optional[int]:
        x, y = self._c_to_m(cx, cy)
        p = Point(x, y)
        best_idx = None
        best_dist = float("inf")
        for i, e in enumerate(self.plan.edges):
            d = p.distance(LineString([e.p1, e.p2]))
            if d < best_dist:
                best_dist = d
                best_idx = i
        if best_dist <= threshold_m:
            return best_idx
        return None

    def _select_nearest(self, cx: float, cy: float):
        pidx = self._find_nearest_point(cx, cy)
        if pidx is not None:
            self.selected_point = pidx
            self.selected_edge = None
        else:
            eidx = self._find_nearest_edge(cx, cy)
            if eidx is not None:
                self.selected_edge = eidx
                self.selected_point = None
            else:
                self.selected_edge = None
                self.selected_point = None
        self._sync_params()
        self._draw()

    def _sync_params(self):
        # hide all conditional sections first
        self.edge_section.pack_forget()
        self.point_section.pack_forget()
        self.edge_length_section.pack_forget()

        point_has_focus = self.point_xy_entry == self.root.focus_get()
        edge_has_focus = self.edge_length_entry == self.root.focus_get()

        if self.selected_point is not None:
            p = self.plan.points[self.selected_point]
            if self.selected_point != self._last_synced_point or not point_has_focus:
                self.point_xy_var.set(f"{p[0]:.3f} ; {p[1]:.3f}")
            self._last_synced_point = self.selected_point
            self.edge_type_var.set("parapet")
            self.parapet_height_var.set(0.40)
            self.parapet_top_var.set(0.25)
            if self.selected_edge is None or not edge_has_focus:
                self.edge_length_var.set("0.0")
            self.point_section.pack(fill=tk.X, pady=3, padx=5)
        elif self.selected_edge is not None:
            e = self.plan.edges[self.selected_edge]
            self.edge_type_var.set(e.edge_type)
            self.parapet_height_var.set(e.parapet_height)
            self.parapet_top_var.set(e.parapet_top_width)
            if self.selected_edge != self._last_synced_edge or not edge_has_focus:
                self.edge_length_var.set(f"{e.length:.3f}")
            self._last_synced_edge = self.selected_edge
            if self.selected_point is None or not point_has_focus:
                self.point_xy_var.set("0.0 ; 0.0")
            self.edge_section.pack(fill=tk.X, pady=3, padx=5)
            self.edge_length_section.pack(fill=tk.X, pady=3, padx=5)
        else:
            self.point_xy_var.set("0.0 ; 0.0")
            self.edge_length_var.set("0.0")
            self._last_synced_point = None
            self._last_synced_edge = None

        # keep actions and info at the bottom
        self.actions_section.pack_forget()
        self.info_section.pack_forget()
        self.actions_section.pack(fill=tk.X, pady=3, padx=5)
        self.info_section.pack(fill=tk.X, pady=3, padx=5)
        self._on_right_configure()

    def _apply_to_selected(self):
        if self.selected_edge is None:
            return
        edge = self.plan.edges[self.selected_edge]
        edge.edge_type = self.edge_type_var.get()
        edge.parapet_height = self.parapet_height_var.get()
        edge.parapet_top_width = self.parapet_top_var.get()
        self._push_history()
        self._draw()

    def _apply_to_all(self):
        et = self.edge_type_var.get()
        h = self.parapet_height_var.get()
        tw = self.parapet_top_var.get()
        for edge in self.plan.edges:
            edge.edge_type = et
            edge.parapet_height = h
            edge.parapet_top_width = tw
        self._push_history()
        self._draw()

    def _apply_to_point(self):
        if self.selected_point is None:
            return
        raw = self.point_xy_var.get()
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
        self.plan.points[self.selected_point] = (round(x, 3), round(y, 3))
        self._rebuild_edges()
        self.point_xy_var.set(f"{x:.3f} ; {y:.3f}")
        self._last_synced_point = self.selected_point
        self._push_history()
        self._sync_params()
        self._draw()

    def _delete_selected_point(self):
        if self.selected_point is not None:
            self._delete_point(self.selected_point)

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

        n = len(self.plan.points)
        idx1 = self.selected_edge
        idx2 = (self.selected_edge + 1) % n
        p1 = self.plan.points[idx1]
        p2 = self.plan.points[idx2]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        cur_len = math.hypot(dx, dy)
        if cur_len == 0:
            return
        new_x = p1[0] + (dx / cur_len) * new_length
        new_y = p1[1] + (dy / cur_len) * new_length
        self.plan.points[idx2] = (round(new_x, 3), round(new_y, 3))
        self._rebuild_edges()
        self.edge_length_var.set(f"{new_length:.3f}")
        self._last_synced_edge = self.selected_edge
        self._push_history()
        self._sync_params()
        self._draw()

    def _delete_selected_line(self):
        if self.selected_edge is not None:
            self._delete_line(self.selected_edge)

    def _close_polygon(self):
        if len(self.plan.points) < 3:
            messagebox.showwarning("Too few points", "A roof needs at least 3 points.")
            return
        self.closed = True
        self.plan.num_drains = self.num_drains_var.get()
        self._rebuild_edges()
        self._push_history()
        self._draw()

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
        if not self.closed or not self.plan.is_valid:
            messagebox.showwarning("No roof", "Please close a valid roof polygon first.")
            return

        template = self.template_path_var.get()
        if not template or not Path(template).is_file():
            messagebox.showwarning("No template", "Please select a DEVIZ Excel template.")
            return

        price_path = Path("data/price.xlsx").resolve()
        catalog = PriceCatalog(price_path) if price_path.is_file() else None

        self.plan.num_drains = self.num_drains_var.get()
        quantities = RoofCalculator.calculate_from_plan(self.plan)

        out = filedialog.asksaveasfilename(
            title="Save estimate",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
        )
        if not out:
            return

        writer = ExcelEstimateWriter(template, catalog=catalog)

        sem_sheet = self._find_sheet(writer.wb.sheetnames, "sem")
        client_sheet = self._find_sheet(writer.wb.sheetnames, "client")

        summary = {
            "quantities": {k: v for k, v in quantities.__dict__.items()},
            "sheets": {},
        }

        if sem_sheet:
            res = writer.write(
                quantities,
                sheet=sem_sheet,
                overwrite_formulas=True,
                save=False,
            )
            summary["sheets"][sem_sheet] = res["matched"]

        if client_sheet:
            res = writer.write(
                quantities,
                sheet=client_sheet,
                overwrite_formulas=False,
                save=False,
            )
            summary["sheets"][client_sheet] = res["matched"]

        writer.save(out)

        msg = f"Saved: {out}\n\nMatched rows:\n"
        for sheet, matched in summary["sheets"].items():
            msg += f"  {sheet}: {matched}\n"
        msg += f"\nArea: {quantities.s_clear} m²\n"
        msg += f"Perimeter: {quantities.p_perimeter} m\n"
        msg += f"Parapet: {quantities.l_rail_top} m\n"
        msg += f"Drip cap: {quantities.l_drip_cap} m\n"
        messagebox.showinfo("Estimate generated", msg)

    def _find_sheet(self, names, needle):
        for name in names:
            if needle.lower() in name.lower():
                return name
        return None

    def _preview_3d(self):
        if not self.plan.is_valid:
            messagebox.showwarning("No roof", "Draw and close a roof first.")
            return

        faces = self.plan.to_3d_faces()
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

        minx, miny, maxx, maxy = self.plan.bounds
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
        file = filedialog.asksaveasfilename(
            title="Save roof plan",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if file:
            with open(file, "w", encoding="utf-8") as f:
                json.dump(self.plan.to_dict(), f, ensure_ascii=False, indent=2)

    def _load_plan(self):
        file = filedialog.askopenfilename(
            title="Load roof plan",
            filetypes=[("JSON files", "*.json")],
        )
        if file:
            with open(file, "r", encoding="utf-8") as f:
                self.plan = RoofPlan.from_dict(json.load(f))
            self.num_drains_var.set(self.plan.num_drains)
            self.closed = len(self.plan.points) >= 3 and len(self.plan.edges) == len(self.plan.points)
            self.selected_edge = None
            self.selected_point = None
            self._push_history()
            self._sync_params()
            self._draw()

    def _draw(self):
        for item in self.canvas_items:
            self.canvas.delete(item)
        self.canvas_items = []

        # grid: draw a large fixed range, will be clipped by canvas
        for i in range(0, 120):
            cx, _ = self._m_to_c(i, 0)
            self.canvas_items.append(
                self.canvas.create_line(cx, -1000, cx, 1000, fill="#333333", tags="grid")
            )
            self.canvas_items.append(
                self.canvas.create_text(cx + 5, self.pan_y - 5, text=str(i), fill="gray", anchor=tk.NW, font=("", 8))
            )
        for i in range(0, 100):
            _, cy = self._m_to_c(0, i)
            self.canvas_items.append(
                self.canvas.create_line(-1000, cy, 2000, cy, fill="#333333", tags="grid")
            )
            self.canvas_items.append(
                self.canvas.create_text(self.pan_x + 5, cy - 12, text=str(i), fill="gray", anchor=tk.NW, font=("", 8))
            )

        # edges
        for i, e in enumerate(self.plan.edges):
            color = "#e74c3c" if e.is_wall else "#3498db"
            if self.selected_edge == i:
                color = "#f1c40f"
            p1 = self._m_to_c(*e.p1)
            p2 = self._m_to_c(*e.p2)
            line = self.canvas.create_line(
                p1[0], p1[1], p2[0], p2[1], fill=color, width=3, tags="edge"
            )
            self.canvas_items.append(line)
            mid_x = (p1[0] + p2[0]) / 2
            mid_y = (p1[1] + p2[1]) / 2
            self.canvas_items.append(
                self.canvas.create_text(mid_x, mid_y - 10, text=f"{e.length:.2f}m", fill="white", font=("", 8))
            )

        # points
        for i, p in enumerate(self.plan.points):
            cx, cy = self._m_to_c(*p)
            if self.selected_point == i:
                self.canvas_items.append(
                    self.canvas.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, fill="#2ecc71", outline="white")
                )
            else:
                self.canvas_items.append(
                    self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="white", outline="black")
                )
            self.canvas_items.append(
                self.canvas.create_text(cx + 8, cy - 8, text=f"P{i+1} ({p[0]:.2f},{p[1]:.2f})", fill="white", anchor=tk.NW, font=("", 8))
            )

        # info
        self.info_text.delete("1.0", tk.END)
        tool = self.tool_var.get()
        if self.plan.is_valid:
            q = RoofCalculator.calculate_from_plan(self.plan)
            info = (
                f"Tool: {tool}\n"
                f"Points: {len(self.plan.points)}\n"
                f"Area: {self.plan.area:.2f} m²\n"
                f"Perimeter: {self.plan.perimeter:.2f} m\n"
                f"Parapet length: {self.plan.parapet_length:.2f} m\n"
                f"Wall/drip cap: {self.plan.wall_length:.2f} m\n"
                f"Drains: {self.plan.num_drains}\n"
                f"Cementoplast: {q.v_cementoplast_m3} m³\n"
                f"Screed: {q.v_screed_m3} m³\n"
                f"Primer: {q.s_primer} m²\n"
                f"Flex EPP: {q.s_hydrobase_flex_epp} m²\n"
            )
            if self.selected_point is not None:
                pt = self.plan.points[self.selected_point]
                info += f"\nSelected point: P{self.selected_point + 1} ({pt[0]:.2f}, {pt[1]:.2f})\n"
            elif self.selected_edge is not None:
                e = self.plan.edges[self.selected_edge]
                info += f"\nSelected edge {self.selected_edge + 1}: {e.edge_type}, {e.length:.2f} m\n"
        else:
            info = (
                f"Tool: {tool}\n"
                f"Pencil: add points\n"
                f"Eraser: remove points or lines\n"
                f"Select: pick edges or points\n"
                f"Mouse wheel: zoom to cursor\n"
                f"Delete key: remove selection\n"
                f"Ctrl+Z: undo, Ctrl+Shift+Z: redo"
            )
        self.info_text.insert(tk.END, info)


def main():
    root = tk.Tk()
    app = RoofModelerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
