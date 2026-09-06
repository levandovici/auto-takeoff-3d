import json
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from shapely.geometry import LineString, Point

from calculator import RoofCalculator
from excel_engine import ExcelEstimateWriter, PriceCatalog
from roof_plan import RoofEdge, RoofPlan
from workspace_inspector import discover_client_folders


class RoofModelerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Auto Takeoff 3D — Modeler")
        self.root.geometry("1200x750")

        self.scale_var = tk.DoubleVar(value=20.0)
        self.num_drains_var = tk.IntVar(value=2)
        self.edge_type_var = tk.StringVar(value="parapet")
        self.parapet_height_var = tk.DoubleVar(value=0.40)
        self.parapet_top_var = tk.DoubleVar(value=0.25)

        self.plan = RoofPlan(points=[])
        self.closed = False
        self.selected_edge: Optional[int] = None
        self.canvas_items = []

        self._build_ui()
        self._draw()

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=5)
        top.pack(fill=tk.X)

        ttk.Button(top, text="New", command=self._new).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Load plan", command=self._load_plan).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Save plan", command=self._save_plan).pack(side=tk.LEFT, padx=2)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(top, text="3D preview", command=self._preview_3d).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Auto generate materials", command=self._auto_generate).pack(side=tk.LEFT, padx=2)

        left = ttk.Frame(self.root, padding=5)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(left, bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Button-3>", self._on_right_click)

        right = ttk.Frame(self.root, padding=10, width=320)
        right.pack(side=tk.RIGHT, fill=tk.Y)
        right.pack_propagate(False)

        ttk.Label(right, text="View scale (px/m):").pack(anchor=tk.W)
        ttk.Spinbox(right, from_=5, to=100, textvariable=self.scale_var, width=10).pack(anchor=tk.W)

        ttk.Label(right, text="Number of drains:").pack(anchor=tk.W, pady=(10, 0))
        ttk.Spinbox(right, from_=1, to=20, textvariable=self.num_drains_var, width=10).pack(anchor=tk.W)

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(right, text="Selected edge").pack(anchor=tk.W)
        ttk.Radiobutton(right, text="Parapet", variable=self.edge_type_var, value="parapet").pack(anchor=tk.W)
        ttk.Radiobutton(right, text="Wall (drip cap)", variable=self.edge_type_var, value="wall").pack(anchor=tk.W)

        ttk.Label(right, text="Parapet height (m):").pack(anchor=tk.W, pady=(10, 0))
        ttk.Entry(right, textvariable=self.parapet_height_var, width=12).pack(anchor=tk.W)
        ttk.Label(right, text="Parapet top width (m):").pack(anchor=tk.W)
        ttk.Entry(right, textvariable=self.parapet_top_var, width=12).pack(anchor=tk.W)

        ttk.Button(right, text="Apply to selected edge", command=self._apply_to_selected).pack(anchor=tk.W, pady=5)
        ttk.Button(right, text="Apply to all edges", command=self._apply_to_all).pack(anchor=tk.W)

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Button(right, text="Close polygon", command=self._close_polygon).pack(anchor=tk.W, pady=2)
        ttk.Button(right, text="Select template", command=self._select_template).pack(anchor=tk.W, pady=2)

        self.template_path_var = tk.StringVar(value="")
        ttk.Entry(right, textvariable=self.template_path_var, width=30).pack(anchor=tk.W)

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        self.info_text = tk.Text(right, height=12, wrap=tk.WORD)
        self.info_text.pack(fill=tk.BOTH, expand=True)

    def _m_to_c(self, x: float, y: float) -> Tuple[float, float]:
        scale = self.scale_var.get()
        cx = 50 + x * scale
        cy = 550 - y * scale
        return (cx, cy)

    def _c_to_m(self, cx: float, cy: float) -> Tuple[float, float]:
        scale = self.scale_var.get()
        x = (cx - 50) / scale
        y = (550 - cy) / scale
        return (x, y)

    def _new(self):
        self.plan = RoofPlan(points=[], num_drains=self.num_drains_var.get())
        self.closed = False
        self.selected_edge = None
        self._draw()

    def _on_click(self, event):
        if self.closed:
            self._select_edge(event.x, event.y)
            return
        x, y = self._c_to_m(event.x, event.y)
        self.plan.points.append((round(x, 3), round(y, 3)))
        self._rebuild_edges()
        self._draw()

    def _on_right_click(self, event):
        if not self.closed or not self.plan.edges:
            return
        idx = self._find_nearest_edge(event.x, event.y)
        if idx is not None:
            self.selected_edge = idx
            edge = self.plan.edges[idx]
            edge.edge_type = "wall" if edge.is_parapet else "parapet"
            self._sync_params_from_edge()
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

    def _select_edge(self, cx: float, cy: float):
        idx = self._find_nearest_edge(cx, cy)
        if idx is not None:
            self.selected_edge = idx
            self._sync_params_from_edge()
            self._draw()

    def _sync_params_from_edge(self):
        if self.selected_edge is None:
            return
        edge = self.plan.edges[self.selected_edge]
        self.edge_type_var.set(edge.edge_type)
        self.parapet_height_var.set(edge.parapet_height)
        self.parapet_top_var.set(edge.parapet_top_width)

    def _apply_to_selected(self):
        if self.selected_edge is None:
            return
        edge = self.plan.edges[self.selected_edge]
        edge.edge_type = self.edge_type_var.get()
        edge.parapet_height = self.parapet_height_var.get()
        edge.parapet_top_width = self.parapet_top_var.get()
        self._draw()

    def _apply_to_all(self):
        et = self.edge_type_var.get()
        h = self.parapet_height_var.get()
        tw = self.parapet_top_var.get()
        for edge in self.plan.edges:
            edge.edge_type = et
            edge.parapet_height = h
            edge.parapet_top_width = tw
        self._draw()

    def _close_polygon(self):
        if len(self.plan.points) < 3:
            messagebox.showwarning("Too few points", "A roof needs at least 3 points.")
            return
        self.closed = True
        self._rebuild_edges()
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
            self._draw()

    def _draw(self):
        for item in self.canvas_items:
            self.canvas.delete(item)
        self.canvas_items = []

        scale = self.scale_var.get()

        # grid
        for i in range(0, 50):
            x_m = i
            cx, _ = self._m_to_c(x_m, 0)
            if cx > 1050:
                break
            self.canvas_items.append(
                self.canvas.create_line(cx, 0, cx, 600, fill="#333333", tags="grid")
            )
            self.canvas_items.append(
                self.canvas.create_text(cx + 5, 590, text=str(x_m), fill="gray", anchor=tk.NW, font=("", 8))
            )
        for i in range(0, 40):
            y_m = i
            _, cy = self._m_to_c(0, y_m)
            if cy < 0:
                break
            self.canvas_items.append(
                self.canvas.create_line(0, cy, 1050, cy, fill="#333333", tags="grid")
            )
            self.canvas_items.append(
                self.canvas.create_text(5, cy - 12, text=str(y_m), fill="gray", anchor=tk.NW, font=("", 8))
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
            self.canvas_items.append(
                self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="white", outline="black")
            )
            self.canvas_items.append(
                self.canvas.create_text(cx + 8, cy - 8, text=f"P{i+1} ({p[0]:.2f},{p[1]:.2f})", fill="white", anchor=tk.NW, font=("", 8))
            )

        # info
        self.info_text.delete("1.0", tk.END)
        if self.plan.is_valid:
            q = RoofCalculator.calculate_from_plan(self.plan)
            info = (
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
        else:
            info = "Click on the canvas to add points.\nRight-click an edge to toggle wall/parapet.\nUse the side panel to set edge parameters."
        self.info_text.insert(tk.END, info)


def main():
    root = tk.Tk()
    app = RoofModelerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
