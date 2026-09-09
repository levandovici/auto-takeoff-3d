import json
import math
import os
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from shapely.geometry import LineString, Point, Polygon

from calculator import RoofCalculator, RoofConfig
from deviz_generator import generate_deviz, geotextil_breakdown
from excel_engine import ExcelEstimateWriter, PriceCatalog
from pdf_generator import generate_pdf_client
from roof_plan import RoofEdge, RoofPlan, VentilationDuct
from roof_3d import (
    GenerateModelDialog,
    export_dae,
    export_glb,
    export_obj,
    export_skp,
    generate_3d_components,
    preview_polyscope,
)


X_AXIS_COLOR = "#ff5555"
Y_AXIS_COLOR = "#55ff55"
RUBBER_DEFAULT = "#ffffff"
RUBBER_SNAP = 0.05  # m

LAST_MATERIAL_CONFIG_PATH = Path(__file__).parent / "last_material_config.json"


def _load_last_material_config() -> Dict[str, Any]:
    if LAST_MATERIAL_CONFIG_PATH.exists():
        try:
            with open(LAST_MATERIAL_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_last_material_config(config: RoofConfig) -> None:
    data = asdict(config)
    with open(LAST_MATERIAL_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_COMPONENT_COLORS = {
    "Slab": "#e74c3c",
    "Parapet": "#3498db",
    "Wall": "#f1c40f",
    "XPS": "#2ecc71",
    "Cementoplast": "#9b59b6",
    "Screed": "#e67e22",
    "Mesh": "#1abc9c",
}


def _color_for_component(name: str) -> str:
    for key, color in _COMPONENT_COLORS.items():
        if key in name:
            return color
    return "#cccccc"


def _hex_to_rgb(color: str) -> Tuple[float, float, float]:
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return tuple(int(color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


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


class MaterialConfigDialog(tk.Toplevel):
    """Collect all options for the configurable material/deviz generator."""

    BITUM_MATERIALS = ["Elast", "Ultra", "Flex"]
    PVC_MATERIALS = ["Protan", "Flagon", "Fatrafol"]
    THERMAL_HEIGHTS = [10.0, 15.0, 20.0]
    PARAPET_WIDTHS = [3.0, 5.0, 10.0]
    WALL_WIDTHS = [10.0, 15.0, 20.0, 25.0, 30.0]
    SLOPE_PCTS = [2.0, 3.0, 4.0, 5.0]
    SCREED_THICKNESSES = [5.0, 6.0, 7.0]

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Material generation options")
        self.geometry("620x780")
        self.resizable(False, True)
        self.result: Optional[RoofConfig] = None

        # Variables
        self.group_var = tk.StringVar(value="bitum")
        self.bitum_material_var = tk.StringVar(value="Ultra")
        self.bitum_layers_var = tk.IntVar(value=2)
        self.bitum_parapets_var = tk.BooleanVar(value=True)
        self.pvc_material_var = tk.StringVar(value="Flagon")
        self.pvc_geotextil_var = tk.IntVar(value=1)
        self.pvc_parapets_var = tk.BooleanVar(value=True)

        self.thermal_slab_var = tk.BooleanVar(value=True)
        self.thermal_slab_layers_var = tk.IntVar(value=2)
        self.thermal_slab_height_var = tk.DoubleVar(value=15.0)

        self.thermal_parapet_var = tk.BooleanVar(value=False)
        self.thermal_parapet_width_var = tk.DoubleVar(value=5.0)
        self.thermal_parapet_wall_width_var = tk.DoubleVar(value=10.0)
        self.thermal_slab_bitum_epp_var = tk.BooleanVar(value=True)
        self.thermal_slab_bitum_epp_material_var = tk.StringVar(value="Ultra")

        self.mesh_var = tk.BooleanVar(value=True)

        self.cementoplast_var = tk.BooleanVar(value=True)
        self.base_dir_var = tk.StringVar(value="width")
        self.base_pct_var = tk.DoubleVar(value=2.0)
        self.counter_extent_var = tk.StringVar(value="center")
        self.counter_pct_var = tk.DoubleVar(value=2.0)

        self.screed_var = tk.BooleanVar(value=True)
        self.screed_thickness_var = tk.DoubleVar(value=5.0)

        self._load_last_config()
        self._build_ui()
        self._on_group_changed()

        self.grab_set()
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.wait_visibility()
        self.focus_set()

    def _load_last_config(self):
        data = _load_last_material_config()
        if not data:
            return
        mapping = {
            "waterproofing_group": self.group_var,
            "bitum_material": self.bitum_material_var,
            "bitum_layers": self.bitum_layers_var,
            "bitum_include_parapets": self.bitum_parapets_var,
            "pvc_material": self.pvc_material_var,
            "pvc_geotextil_layers": self.pvc_geotextil_var,
            "pvc_include_parapets": self.pvc_parapets_var,
            "thermal_slab_enabled": self.thermal_slab_var,
            "thermal_slab_layers": self.thermal_slab_layers_var,
            "thermal_slab_height_cm": self.thermal_slab_height_var,
            "thermal_parapet_enabled": self.thermal_parapet_var,
            "thermal_parapet_width_cm": self.thermal_parapet_width_var,
            "thermal_parapet_wall_width_cm": self.thermal_parapet_wall_width_var,
            "thermal_slab_bitum_epp": self.thermal_slab_bitum_epp_var,
            "thermal_slab_bitum_epp_material": self.thermal_slab_bitum_epp_material_var,
            "mesh_enabled": self.mesh_var,
            "cementoplast_enabled": self.cementoplast_var,
            "base_slope_direction": self.base_dir_var,
            "base_slope_pct": self.base_pct_var,
            "counter_slope_extent": self.counter_extent_var,
            "counter_slope_pct": self.counter_pct_var,
            "screed_enabled": self.screed_var,
            "screed_thickness_cm": self.screed_thickness_var,
        }
        for key, var in mapping.items():
            if key in data:
                try:
                    var.set(data[key])
                except tk.TclError:
                    pass

    def _build_ui(self):
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.frame = ttk.Frame(canvas)
        self.frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Waterproofing group
        ttk.Label(self.frame, text="Waterproofing group", font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
        group_frame = ttk.Frame(self.frame)
        group_frame.pack(fill="x", padx=10, pady=5)
        for g in ("bitum", "pvc"):
            ttk.Radiobutton(group_frame, text=g.capitalize(), variable=self.group_var, value=g,
                            command=self._on_group_changed).pack(side="left", padx=10)

        self.bitum_frame = ttk.LabelFrame(self.frame, text="Bitum settings")
        self.bitum_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(self.bitum_frame, text="Material:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Combobox(self.bitum_frame, textvariable=self.bitum_material_var, values=self.BITUM_MATERIALS,
                     state="readonly", width=12).grid(row=0, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(self.bitum_frame, text="Layers:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Spinbox(self.bitum_frame, from_=1, to=2, textvariable=self.bitum_layers_var, width=5).grid(row=1, column=1, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(self.bitum_frame, text="Include parapets", variable=self.bitum_parapets_var).grid(row=2, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        self.pvc_frame = ttk.LabelFrame(self.frame, text="PVC settings")
        self.pvc_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(self.pvc_frame, text="Material:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Combobox(self.pvc_frame, textvariable=self.pvc_material_var, values=self.PVC_MATERIALS,
                     state="readonly", width=12).grid(row=0, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(self.pvc_frame, text="Geotextil layers:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Spinbox(self.pvc_frame, from_=0, to=2, textvariable=self.pvc_geotextil_var, width=5).grid(row=1, column=1, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(self.pvc_frame, text="Include parapets", variable=self.pvc_parapets_var).grid(row=2, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # Thermal insulation slab
        slab_frame = ttk.LabelFrame(self.frame, text="Thermal insulation of floor slab")
        slab_frame.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(slab_frame, text="Enabled", variable=self.thermal_slab_var).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Label(slab_frame, text="Layers:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Spinbox(slab_frame, from_=1, to=2, textvariable=self.thermal_slab_layers_var, width=5).grid(row=1, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(slab_frame, text="Total height (cm):").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        ttk.Combobox(slab_frame, textvariable=self.thermal_slab_height_var, values=self.THERMAL_HEIGHTS,
                     state="readonly", width=6).grid(row=2, column=1, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(slab_frame, text="Additional bitum EPP layer for floor slab",
                        variable=self.thermal_slab_bitum_epp_var).grid(row=3, column=0, columnspan=2, sticky="w", padx=5, pady=2)
        ttk.Label(slab_frame, text="Material:").grid(row=4, column=0, sticky="w", padx=5, pady=2)
        ttk.Combobox(slab_frame, textvariable=self.thermal_slab_bitum_epp_material_var,
                     values=self.BITUM_MATERIALS, state="readonly", width=10).grid(row=4, column=1, sticky="w", padx=5, pady=2)

        # Thermal insulation parapet
        par_frame = ttk.LabelFrame(self.frame, text="Thermal insulation of parapet")
        par_frame.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(par_frame, text="Enabled", variable=self.thermal_parapet_var).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Label(par_frame, text="Parapet width (cm):").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Combobox(par_frame, textvariable=self.thermal_parapet_width_var, values=self.PARAPET_WIDTHS,
                     state="readonly", width=6).grid(row=1, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(par_frame, text="Wall width (cm):").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        ttk.Combobox(par_frame, textvariable=self.thermal_parapet_wall_width_var, values=self.WALL_WIDTHS,
                     state="readonly", width=6).grid(row=2, column=1, sticky="w", padx=5, pady=2)

        # Mesh
        ttk.Checkbutton(self.frame, text="Plasa sudata VR-1 mesh", variable=self.mesh_var).pack(anchor="w", padx=15, pady=5)

        # Cementoplast
        cp_frame = ttk.LabelFrame(self.frame, text="Cement-plastic composite slopes")
        cp_frame.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(cp_frame, text="Enabled", variable=self.cementoplast_var).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Label(cp_frame, text="Base slope direction:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Combobox(cp_frame, textvariable=self.base_dir_var, values=["width", "length"],
                     state="readonly", width=10).grid(row=1, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(cp_frame, text="Base slope %:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        ttk.Combobox(cp_frame, textvariable=self.base_pct_var, values=self.SLOPE_PCTS,
                     state="readonly", width=6).grid(row=2, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(cp_frame, text="Counter slope extent:").grid(row=3, column=0, sticky="w", padx=5, pady=2)
        ttk.Combobox(cp_frame, textvariable=self.counter_extent_var, values=["center", "half"],
                     state="readonly", width=10).grid(row=3, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(cp_frame, text="Counter slope %:").grid(row=4, column=0, sticky="w", padx=5, pady=2)
        ttk.Combobox(cp_frame, textvariable=self.counter_pct_var, values=self.SLOPE_PCTS,
                     state="readonly", width=6).grid(row=4, column=1, sticky="w", padx=5, pady=2)

        # Screed
        screed_frame = ttk.LabelFrame(self.frame, text="Screed (sapa semiuda)")
        screed_frame.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(screed_frame, text="Enabled", variable=self.screed_var).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Label(screed_frame, text="Thickness (cm):").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Combobox(screed_frame, textvariable=self.screed_thickness_var, values=self.SCREED_THICKNESSES,
                     state="readonly", width=6).grid(row=1, column=1, sticky="w", padx=5, pady=2)

        # Buttons
        btn_frame = ttk.Frame(self.frame)
        btn_frame.pack(fill="x", padx=10, pady=15)
        ttk.Button(btn_frame, text="Generate", command=self._ok).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self._cancel).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Save as default", command=self._save_defaults).pack(side="right", padx=5)

    def _on_group_changed(self):
        group = self.group_var.get()
        if group == "bitum":
            self._enable(self.bitum_frame, True)
            self._enable(self.pvc_frame, False)
        else:
            self._enable(self.bitum_frame, False)
            self._enable(self.pvc_frame, True)

    @staticmethod
    def _enable(frame: ttk.LabelFrame, enabled: bool):
        state = "!disabled" if enabled else "disabled"
        for child in frame.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

    def _build_config(self) -> RoofConfig:
        return RoofConfig(
            waterproofing_group=self.group_var.get(),
            bitum_material=self.bitum_material_var.get(),
            bitum_layers=self.bitum_layers_var.get(),
            bitum_include_parapets=self.bitum_parapets_var.get(),
            pvc_material=self.pvc_material_var.get(),
            pvc_geotextil_layers=self.pvc_geotextil_var.get(),
            pvc_include_parapets=self.pvc_parapets_var.get(),
            thermal_slab_enabled=self.thermal_slab_var.get(),
            thermal_slab_layers=self.thermal_slab_layers_var.get(),
            thermal_slab_height_cm=self.thermal_slab_height_var.get(),
            thermal_parapet_enabled=self.thermal_parapet_var.get(),
            thermal_parapet_width_cm=self.thermal_parapet_width_var.get(),
            thermal_parapet_wall_width_cm=self.thermal_parapet_wall_width_var.get(),
            thermal_slab_bitum_epp=self.thermal_slab_bitum_epp_var.get(),
            thermal_slab_bitum_epp_material=self.thermal_slab_bitum_epp_material_var.get(),
            mesh_enabled=self.mesh_var.get(),
            cementoplast_enabled=self.cementoplast_var.get(),
            base_slope_direction=self.base_dir_var.get(),
            base_slope_pct=self.base_pct_var.get(),
            counter_slope_extent=self.counter_extent_var.get(),
            counter_slope_pct=self.counter_pct_var.get(),
            screed_enabled=self.screed_var.get(),
            screed_thickness_cm=self.screed_thickness_var.get(),
        )

    def _ok(self):
        self.result = self._build_config()
        _save_last_material_config(self.result)
        self.destroy()

    def _save_defaults(self):
        config = self._build_config()
        _save_last_material_config(config)
        messagebox.showinfo("Saved", "Current options saved as default.")

    def _cancel(self):
        self.result = None
        self.destroy()


class MaterialPricesDialog(tk.Toplevel):
    """Edit material prices stored in materials_config.json."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Material prices")
        self.geometry("520x520")
        self.transient(parent)

        self.config_path = Path(__file__).parent / "materials_config.json"
        self.materials: Dict[str, float] = {}
        self._load()

        ttk.Label(self, text="Double-click a price to edit, then Save.").pack(pady=5)

        columns = ("material", "price")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=18)
        self.tree.heading("material", text="Material")
        self.tree.heading("price", text="Price")
        self.tree.column("material", width=350)
        self.tree.column("price", width=100, anchor="e")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        ttk.Button(self, text="Save", command=self._save).pack(pady=5)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._populate()
        self.tree.bind("<Double-1>", self._on_double_click)

    def _load(self):
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.materials = {k: float(v) for k, v in data.get("prices", {}).items()}
        else:
            self.materials = {}

    def _populate(self):
        for name, price in sorted(self.materials.items()):
            self.tree.insert("", tk.END, values=(name, f"{price:.2f}"))

    def _on_double_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        item = self.tree.identify_row(event.y)
        if not item or col != "#2":
            return
        values = self.tree.item(item, "values")
        name = values[0]

        bbox = self.tree.bbox(item, column=col)
        entry = tk.Entry(self.tree, justify="right")
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.insert(0, values[1])
        entry.select_range(0, tk.END)
        entry.focus()

        def _commit(_):
            try:
                new_price = float(entry.get())
            except ValueError:
                entry.destroy()
                return
            self.materials[name] = new_price
            self.tree.item(item, values=(name, f"{new_price:.2f}"))
            entry.destroy()

        entry.bind("<Return>", _commit)
        entry.bind("<FocusOut>", lambda _: entry.destroy())

    def _save(self):
        data = {"prices": self.materials}
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # Force deviz_generator to reload prices on next generation
        from deviz_generator import load_materials_config
        load_materials_config(str(self.config_path))
        messagebox.showinfo("Saved", f"Material prices saved to\n{self.config_path}")


class RoofModelerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Auto Takeoff 3D — Modeler")
        self.root.geometry("1200x800")

        self.scale_var = tk.DoubleVar(value=20.0)
        self.num_drains_var = tk.IntVar(value=2)
        self.tool_var = tk.StringVar(value="select")
        self.drawing_type_var = tk.StringVar(value="parapet")
        self.edge_type_var = tk.StringVar(value="parapet")
        self.parapet_height_var = tk.DoubleVar(value=1.0)
        self.parapet_top_var = tk.DoubleVar(value=0.2)
        self.wall_height_var = tk.DoubleVar(value=2.5)
        self.duct_height_var = tk.DoubleVar(value=1.0)
        self.duct_include_top_var = tk.BooleanVar(value=True)
        self.dot_xy_var = tk.StringVar(value="0.0 ; 0.0")
        self.edge_length_var = tk.StringVar(value="0.0")
        self.mode_var = tk.StringVar(value="2D")
        self.view_btn_text = tk.StringVar(value="3D")

        self.last_config: Optional[RoofConfig] = self._load_last_config()
        self.model3d_components: Optional[Dict[str, "trimesh.Trimesh"]] = None
        self._3d_view_built = False
        self._3d_dirty = True
        self._polyscope_proc: Optional[Any] = None

        self.pan_x = 50.0
        self.pan_y = 550.0

        # graph
        self.dots: List[Tuple[float, float]] = []
        self.edges: List[Dict[str, Any]] = []
        self.path: List[int] = []
        self.areas: List[List[int]] = []
        self.ventilation_ducts: List[Dict[str, Any]] = []

        self.pencil_start: Optional[int] = None
        self.hover_dot: Optional[int] = None
        self.selected_dot: Optional[int] = None
        self.selected_edge: Optional[int] = None
        self._last_synced_dot: Optional[int] = None
        self._last_synced_edge: Optional[int] = None
        self._applying_edge = False

        self.mouse_x = 0
        self.mouse_y = 0
        self.canvas_items = []

        self._history: List[Dict[str, Any]] = []
        self._history_pos = -1

        self._build_ui()
        self._bind_edge_var_traces()

        icon_path = Path(__file__).parent / "auto_takeoff_3d.ico"
        if icon_path.is_file():
            self.root.iconbitmap(str(icon_path))

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
        menubar = tk.Menu(self.root)
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Material prices", command=self._edit_material_prices)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        export3d_menu = tk.Menu(menubar, tearoff=0)
        export3d_menu.add_command(label="SketchUp (.skp)", command=lambda: self._export_3d("skp"))
        export3d_menu.add_command(label="glTF binary (.glb)", command=lambda: self._export_3d("glb"))
        export3d_menu.add_command(label="COLLADA (.dae)", command=lambda: self._export_3d("dae"))
        export3d_menu.add_command(label="Wavefront OBJ (.obj)", command=lambda: self._export_3d("obj"))
        menubar.add_cascade(label="Export 3D", menu=export3d_menu)

        self.root.config(menu=menubar)

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
        ttk.Button(top, textvariable=self.view_btn_text, command=self._toggle_view_mode, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Preview", command=self._preview_3d).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Generate model", command=self._generate_model).pack(side=tk.LEFT, padx=2)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(top, text="Generate Excel", command=self._auto_generate).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Generate Excel & PDF", command=self._generate_excel_and_pdf).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Settings", command=self._configure_settings).pack(side=tk.LEFT, padx=2)

        left = ttk.Frame(self.root, padding=5)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.view_container = ttk.Frame(left)
        self.view_container.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.view_container, bg="#1e1e1e", highlightthickness=0)
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

        self.pencil_section = CollapsibleFrame(self.right_inner, "Pencil settings")
        for text, value in (("Line", "line"), ("Parapet", "parapet"), ("Wall", "wall"), ("Ventilation duct", "ventilation_duct")):
            ttk.Radiobutton(self.pencil_section.content, text=text, variable=self.drawing_type_var, value=value, command=self._sync_params).pack(anchor=tk.W)

        self.dot_section = CollapsibleFrame(self.right_inner, "Selected dot")
        ttk.Label(self.dot_section.content, text="X ; Y (m):").pack(anchor=tk.W)
        self.dot_xy_entry = ttk.Entry(self.dot_section.content, textvariable=self.dot_xy_var, width=30)
        self.dot_xy_entry.pack(anchor=tk.W)
        self.dot_xy_entry.bind("<Return>", lambda e: self._apply_to_dot())
        ttk.Button(self.dot_section.content, text="Apply to dot", command=self._apply_to_dot).pack(anchor=tk.W, pady=5)
        ttk.Button(self.dot_section.content, text="Delete dot", command=self._delete_selected_dot).pack(anchor=tk.W)

        self.edge_section = CollapsibleFrame(self.right_inner, "Selected edge")
        ttk.Radiobutton(self.edge_section.content, text="Line", variable=self.edge_type_var, value="line", command=self._apply_to_edge).pack(anchor=tk.W)
        ttk.Radiobutton(self.edge_section.content, text="Parapet", variable=self.edge_type_var, value="parapet", command=self._apply_to_edge).pack(anchor=tk.W)
        ttk.Radiobutton(self.edge_section.content, text="Wall (drip cap)", variable=self.edge_type_var, value="wall", command=self._apply_to_edge).pack(anchor=tk.W)
        ttk.Radiobutton(self.edge_section.content, text="Ventilation duct", variable=self.edge_type_var, value="ventilation_duct", command=self._apply_to_edge).pack(anchor=tk.W)

        self.parapet_height_row = ttk.Frame(self.edge_section.content)
        self.parapet_height_row.pack(anchor=tk.W, fill=tk.X)
        ttk.Label(self.parapet_height_row, text="Parapet height (m):").pack(anchor=tk.W)
        ttk.Entry(self.parapet_height_row, textvariable=self.parapet_height_var, width=15).pack(anchor=tk.W)

        self.parapet_top_row = ttk.Frame(self.edge_section.content)
        self.parapet_top_row.pack(anchor=tk.W, fill=tk.X)
        ttk.Label(self.parapet_top_row, text="Parapet top width (m):").pack(anchor=tk.W)
        ttk.Entry(self.parapet_top_row, textvariable=self.parapet_top_var, width=15).pack(anchor=tk.W)

        self.wall_height_row = ttk.Frame(self.edge_section.content)
        self.wall_height_row.pack(anchor=tk.W, fill=tk.X)
        ttk.Label(self.wall_height_row, text="Wall height (m):").pack(anchor=tk.W)
        ttk.Entry(self.wall_height_row, textvariable=self.wall_height_var, width=15).pack(anchor=tk.W)

        self.duct_settings_row = ttk.Frame(self.edge_section.content)
        ttk.Label(self.duct_settings_row, text="Duct height (m):").pack(anchor=tk.W)
        ttk.Entry(self.duct_settings_row, textvariable=self.duct_height_var, width=15).pack(anchor=tk.W)
        ttk.Checkbutton(self.duct_settings_row, text="Include top area", variable=self.duct_include_top_var).pack(anchor=tk.W)

        self.pencil_duct_settings_row = ttk.Frame(self.pencil_section.content)
        ttk.Label(self.pencil_duct_settings_row, text="Duct height (m):").pack(anchor=tk.W)
        ttk.Entry(self.pencil_duct_settings_row, textvariable=self.duct_height_var, width=15).pack(anchor=tk.W)
        ttk.Checkbutton(self.pencil_duct_settings_row, text="Include top area", variable=self.duct_include_top_var).pack(anchor=tk.W)

        ttk.Label(self.edge_section.content, text="Length (m):").pack(anchor=tk.W, pady=(10, 0))
        self.edge_length_entry = ttk.Entry(self.edge_section.content, textvariable=self.edge_length_var, width=15)
        self.edge_length_entry.pack(anchor=tk.W)
        self.edge_length_entry.bind("<Return>", lambda e: self._apply_to_edge_length())
        ttk.Button(self.edge_section.content, text="Apply to edge length", command=self._apply_to_edge_length).pack(anchor=tk.W, pady=5)
        ttk.Button(self.edge_section.content, text="Delete edge", command=self._delete_selected_edge).pack(anchor=tk.W)

        self.actions_section = CollapsibleFrame(self.right_inner, "Actions")
        ttk.Button(self.actions_section.content, text="Close polygon", command=self._close_polygon).pack(anchor=tk.W, pady=2)

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

    def _bind_edge_var_traces(self):
        self.parapet_height_var.trace_add("write", self._on_edge_prop_change)
        self.parapet_top_var.trace_add("write", self._on_edge_prop_change)
        self.wall_height_var.trace_add("write", self._on_edge_prop_change)
        self.duct_height_var.trace_add("write", self._on_edge_prop_change)
        self.duct_include_top_var.trace_add("write", self._on_edge_prop_change)

    def _on_edge_prop_change(self, *args):
        if self._applying_edge or self.selected_edge is None:
            return
        self._apply_to_edge()

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
            "ventilation_ducts": [dict(duct, path=list(duct["path"])) for duct in self.ventilation_ducts],
            "pencil_start": self.pencil_start,
            "num_drains": self.num_drains_var.get(),
        })
        self._history_pos = len(self._history) - 1
        self._3d_dirty = True
        if getattr(self, "mode_var", None) and self.mode_var.get() == "3D":
            self._draw_3d()

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
        self.ventilation_ducts = [dict(duct, path=list(duct["path"])) for duct in snap.get("ventilation_ducts", [])]
        self._migrate_legacy_duct_areas()
        self.pencil_start = snap["pencil_start"]
        self.num_drains_var.set(snap.get("num_drains", 2))
        self.selected_dot = None
        self.selected_edge = None
        self._sync_params()
        self._draw()

    def _new(self):
        self.dots = []
        self.edges = []
        self.path = []
        self.areas = []
        self.ventilation_ducts = []
        self.pencil_start = None
        self.selected_dot = None
        self.selected_edge = None
        self.pan_x = 50.0
        self.pan_y = 550.0
        self._history = []
        self._history_pos = -1
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

    def _new_edge(self, a: int, b: int) -> Dict[str, Any]:
        return {
            "a": a,
            "b": b,
            "edge_type": self.drawing_type_var.get(),
            "parapet_height": self.parapet_height_var.get(),
            "parapet_top_width": self.parapet_top_var.get(),
            "wall_height": self.wall_height_var.get(),
            "duct_height": self.duct_height_var.get(),
            "duct_include_top": self.duct_include_top_var.get(),
        }

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
            self.edges.append(self._new_edge(a, b))
            self._insert_into_path(self.pencil_start, near)
            self.pencil_start = near if target_degree == 0 else None
        else:
            x, y = self._c_to_m(cx, cy)
            self.dots.append((round(x, 3), round(y, 3)))
            new_idx = len(self.dots) - 1
            a = self.pencil_start
            self.edges.append(self._new_edge(a, new_idx))
            self._insert_into_path(self.pencil_start, new_idx)
            self.pencil_start = new_idx

        # check if current path has become a closed loop
        if len(self.path) >= 3 and self._path_is_closed():
            self._finish_closed_path()

        if self.drawing_type_var.get() == "line":
            self.path = []
            self.pencil_start = None

        self._push_history()
        self._sync_params()
        self._draw()

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
        if self._applying_edge or self.selected_edge is None:
            return
        self._applying_edge = True
        try:
            e = self.edges[self.selected_edge]
            e["edge_type"] = self.edge_type_var.get()
            e["parapet_height"] = self.parapet_height_var.get()
            e["parapet_top_width"] = self.parapet_top_var.get()
            e["wall_height"] = self.wall_height_var.get()
            e["duct_height"] = self.duct_height_var.get()
            e["duct_include_top"] = self.duct_include_top_var.get()
            self._sync_duct_from_edge(self.selected_edge)
            self._sync_params()
            self._draw()
        finally:
            self._applying_edge = False

    def _sync_duct_from_edge(self, edge_index: int):
        edge = self.edges[edge_index]
        for duct in self.ventilation_ducts:
            path = duct["path"]
            pairs = [{path[i], path[(i + 1) % len(path)]} for i in range(len(path))]
            if {edge["a"], edge["b"]} in pairs:
                duct["height"] = edge["duct_height"]
                duct["include_top"] = edge["duct_include_top"]
                for other in self.edges:
                    if other.get("edge_type") == "ventilation_duct" and {other["a"], other["b"]} in pairs:
                        other["duct_height"] = edge["duct_height"]
                        other["duct_include_top"] = edge["duct_include_top"]
                break

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
        self.ventilation_ducts = [
            duct for duct in self.ventilation_ducts
            if {a, b} not in [
                {duct["path"][i], duct["path"][(i + 1) % len(duct["path"])]}
                for i in range(len(duct["path"]))
            ]
        ]

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
        for duct in self.ventilation_ducts:
            duct["path"] = [(j - 1 if j > idx else j) for j in duct["path"] if j != idx]
        self.ventilation_ducts = [duct for duct in self.ventilation_ducts if len(duct["path"]) >= 3]

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
        self.pencil_section.pack_forget()
        self.pencil_duct_settings_row.pack_forget()
        self.dot_section.pack_forget()
        self.edge_section.pack_forget()
        self.duct_settings_row.pack_forget()

        if self.tool_var.get() == "pencil":
            self.pencil_section.pack(fill=tk.X, pady=3, padx=5)
            if self.drawing_type_var.get() == "ventilation_duct":
                self.pencil_duct_settings_row.pack(anchor=tk.W, fill=tk.X)

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
            if self.selected_edge != self._last_synced_edge:
                self.edge_type_var.set(e["edge_type"])
                self.parapet_height_var.set(e["parapet_height"])
                self.parapet_top_var.set(e["parapet_top_width"])
                self.wall_height_var.set(e.get("wall_height", 2.5))
                self.duct_height_var.set(e.get("duct_height", 1.0))
                self.duct_include_top_var.set(e.get("duct_include_top", True))
            if self.selected_edge != self._last_synced_edge or not edge_has_focus:
                self.edge_length_var.set(f"{length:.3f}")
            self._last_synced_edge = self.selected_edge
            self.dot_xy_var.set("0.0 ; 0.0")
            self.edge_section.pack(fill=tk.X, pady=3, padx=5)

            self.parapet_height_row.pack_forget()
            self.parapet_top_row.pack_forget()
            self.wall_height_row.pack_forget()
            if e["edge_type"] == "wall":
                self.wall_height_row.pack(anchor=tk.W, fill=tk.X)
            elif e["edge_type"] == "parapet":
                self.parapet_height_row.pack(anchor=tk.W, fill=tk.X)
                self.parapet_top_row.pack(anchor=tk.W, fill=tk.X)
            elif e["edge_type"] == "ventilation_duct":
                self.duct_settings_row.pack(anchor=tk.W, fill=tk.X)
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

    def _finish_closed_path(self):
        path = list(self.path)
        if self.drawing_type_var.get() == "ventilation_duct":
            self.ventilation_ducts.append({
                "path": path,
                "height": self.duct_height_var.get(),
                "include_top": self.duct_include_top_var.get(),
            })
        elif self.drawing_type_var.get() in ("parapet", "wall"):
            self.areas.append(path)
        self.path = []
        self.pencil_start = None

    def _close_polygon(self):
        if len(self.path) < 3:
            messagebox.showwarning("Too few points", "At least 3 dots are needed to close an area.")
            return
        a = self.path[-1]
        b = self.path[0]
        if a != b:
            self.edges.append(self._new_edge(a, b))
        self._finish_closed_path()
        self._push_history()
        self._sync_params()
        self._draw()

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

    def _insert_into_path(self, start_idx: int, new_idx: int):
        if new_idx in self.path:
            return
        if start_idx in self.path:
            pos = self.path.index(start_idx)
            self.path.insert(pos + 1, new_idx)
        else:
            self.path = [start_idx, new_idx]

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
            props = {"edge_type": "parapet", "parapet_height": 1.0, "parapet_top_width": 0.2, "wall_height": 2.5}
            for e in self.edges:
                if {e["a"], e["b"]} == {a, b}:
                    props = {
                        "edge_type": e["edge_type"],
                        "parapet_height": e.get("parapet_height", 1.0),
                        "parapet_top_width": e.get("parapet_top_width", 0.2),
                        "wall_height": e.get("wall_height", 2.5),
                    }
                    break
            plan_edges.append(RoofEdge(p1=p1, p2=p2, **props))
        roof_polygon = Polygon(points)
        ducts = []
        for duct in self.ventilation_ducts:
            duct_points = [self.dots[i] for i in duct["path"]]
            duct_polygon = Polygon(duct_points)
            if duct_polygon.is_valid and roof_polygon.covers(duct_polygon.representative_point()):
                ducts.append(VentilationDuct(
                    points=duct_points,
                    height=duct.get("height", 1.0),
                    include_top=duct.get("include_top", True),
                ))
        return RoofPlan(points=points, edges=plan_edges, num_drains=self.num_drains_var.get(), ventilation_ducts=ducts)

    def _calculate_areas(self) -> List[Dict[str, Any]]:
        results = []
        for area_path in self.areas:
            plan = self._build_plan_for_area(area_path)
            if plan and plan.is_valid:
                q = RoofCalculator.calculate_from_plan(plan)
                gt = geotextil_breakdown(plan, q.s_clear)
                ducts = [{
                    "closed_area": duct.polygon.area,
                    "height": duct.height,
                    "perimeter": duct.perimeter,
                    "vertical_area": duct.vertical_area,
                    "include_top": duct.include_top,
                    "top_area": duct.top_area,
                    "total_area": duct.material_area,
                } for duct in plan.ventilation_ducts]
                total_material_area = gt["total"] + plan.ventilation_duct_area
                results.append({
                    "area": q.s_clear,
                    "perimeter": q.p_perimeter,
                    "parapet": q.l_rail_top,
                    "drip": q.l_drip_cap,
                    "duct_area": plan.ventilation_duct_area,
                    "duct_perimeter": plan.ventilation_duct_perimeter,
                    "ducts": ducts,
                    "vertical": gt["vertical"],
                    "top": gt["top"],
                    "side": gt["side"],
                    "geotextil_total": total_material_area,
                    "geotextil_qty": float(math.ceil(total_material_area / 100.0) * 100.0),
                })
            else:
                results.append({"area": 0.0, "perimeter": 0.0, "parapet": 0.0, "drip": 0.0,
                                "duct_area": 0.0, "duct_perimeter": 0.0, "ducts": [],
                                "vertical": 0.0, "top": 0.0, "side": 0.0,
                                "geotextil_total": 0.0, "geotextil_qty": 0.0})
        return results

    def _edit_material_prices(self):
        dialog = MaterialPricesDialog(self.root)
        self.root.wait_window(dialog)

    def _auto_generate(self):
        self._generate_estimates(include_pdf=False)

    def _generate_excel_and_pdf(self):
        self._generate_estimates(include_pdf=True)

    def _generate_estimates(self, include_pdf: bool = False):
        if not self.areas:
            messagebox.showwarning("No roof", "Please draw and close at least one roof area first.")
            return

        config = self.last_config if self.last_config is not None else RoofConfig()

        # generate one file per area
        outputs = []
        for idx, area_path in enumerate(self.areas):
            plan = self._build_plan_for_area(area_path)
            if plan is None or not plan.is_valid:
                continue
            quantities = RoofCalculator.calculate_from_plan(plan, config=config)

            out = filedialog.asksaveasfilename(
                title=f"Save estimate for area {idx + 1}",
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx")],
            )
            if not out:
                continue

            generate_deviz(plan, quantities, out, num_drains=self.num_drains_var.get(), config=config)
            outputs.append(out)

            if include_pdf:
                pdf_path = str(Path(out).with_suffix(".pdf"))
                try:
                    generate_pdf_client(
                        plan,
                        quantities,
                        pdf_path,
                        excel_path=out,
                        num_drains=self.num_drains_var.get(),
                        config=config,
                    )
                    outputs.append(pdf_path)
                except Exception as exc:
                    messagebox.showerror("PDF export failed", str(exc))

        if outputs:
            self._show_generation_result(outputs)

    def _show_generation_result(self, outputs: List[str]):
        dialog = tk.Toplevel(self.root)
        dialog.title("Estimates generated")
        dialog.transient(self.root)
        dialog.geometry("500x220")
        dialog.resizable(False, False)

        ttk.Label(dialog, text="Generated files:").pack(pady=(10, 5))
        listbox = tk.Listbox(dialog, width=70, height=6)
        for out in outputs:
            listbox.insert(tk.END, out)
        listbox.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="OK", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Open", command=lambda: self._open_generated(dialog, outputs[-1])).pack(side=tk.LEFT, padx=5)

    @staticmethod
    def _open_generated(dialog: tk.Toplevel, path: str):
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("Open failed", str(e))
        dialog.destroy()

    def _configure_settings(self):
        """Open material settings and store them for generation/export."""
        dialog = MaterialConfigDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result is not None:
            self.last_config = dialog.result
            _save_last_material_config(self.last_config)

    def _load_last_config(self) -> Optional[RoofConfig]:
        data = _load_last_material_config()
        if not data:
            return None
        try:
            return RoofConfig(**data)
        except Exception:
            return None

    def _ensure_model_generated(self) -> bool:
        """Generate the 3D components if a roof exists and cache them."""
        if not self.areas:
            self.model3d_components = {}
            self._3d_dirty = False
            return False
        if self.model3d_components is not None and not self._3d_dirty:
            return True

        if self.last_config is None:
            self.last_config = RoofConfig()

        components: Dict[str, "trimesh.Trimesh"] = {}
        for idx, area_path in enumerate(self.areas):
            plan = self._build_plan_for_area(area_path)
            if plan is None or not plan.is_valid:
                continue
            area_components = generate_3d_components(plan, self.last_config)
            for name, mesh in area_components.items():
                if getattr(mesh, "is_empty", False) or len(getattr(mesh, "faces", [])) == 0:
                    continue
                components[f"Area {idx + 1}: {name}"] = mesh

        self.model3d_components = components
        self._3d_dirty = False
        return bool(components)

    def _generate_model(self):
        """Generate the 3D model and open the component/export dialog."""
        self._ensure_model_generated()
        if not self.model3d_components:
            messagebox.showwarning("No roof", "Draw and close at least one roof area first.")
            return
        GenerateModelDialog(self.root, self.model3d_components)

    def _preview_3d(self):
        """Launch the optional Polyscope preview window for the current model."""
        self._ensure_model_generated()
        if not self.model3d_components:
            messagebox.showwarning("No roof", "Draw and close at least one roof area first.")
            return
        if self._polyscope_proc is not None and self._polyscope_proc.poll() is None:
            return
        self._polyscope_proc = preview_polyscope(self.model3d_components)

    def _toggle_view_mode(self):
        if self.mode_var.get() == "2D":
            self._set_view_mode("3D")
        else:
            self._set_view_mode("2D")

    def _set_view_mode(self, mode: str):
        if mode == "2D":
            if self._3d_view_built:
                self.canvas3d_widget.pack_forget()
            self.canvas.pack(fill=tk.BOTH, expand=True)
            self.mode_var.set("2D")
            self.view_btn_text.set("3D")
        else:
            if not self._3d_view_built:
                self._build_3d_view()
            self.canvas.pack_forget()
            self.canvas3d_widget.pack(fill=tk.BOTH, expand=True)
            self.mode_var.set("3D")
            self.view_btn_text.set("2D")
            self._draw_3d()

    def _build_3d_view(self):
        self.fig = Figure(figsize=(8, 6), dpi=100, facecolor="#1e1e1e")
        self.ax3d = self.fig.add_subplot(111, projection="3d")
        self.ax3d.set_facecolor("#1e1e1e")
        self.ax3d.xaxis.pane.fill = False
        self.ax3d.yaxis.pane.fill = False
        self.ax3d.zaxis.pane.fill = False
        self.ax3d.xaxis.pane.set_edgecolor("#555555")
        self.ax3d.yaxis.pane.set_edgecolor("#555555")
        self.ax3d.zaxis.pane.set_edgecolor("#555555")
        self.canvas3d = FigureCanvasTkAgg(self.fig, master=self.view_container)
        self.canvas3d_widget = self.canvas3d.get_tk_widget()
        self.canvas3d_widget.configure(bg="#1e1e1e", highlightthickness=0)
        self._3d_view_built = True

    def _draw_3d(self):
        if not self._3d_view_built:
            self._build_3d_view()
        self.ax3d.clear()
        self.ax3d.set_facecolor("#1e1e1e")

        self._ensure_model_generated()
        components = self.model3d_components or {}

        all_vertices: List[Any] = []
        for name, mesh in components.items():
            if getattr(mesh, "is_empty", False) or len(getattr(mesh, "faces", [])) == 0:
                continue
            faces = mesh.vertices[mesh.faces]
            color = _color_for_component(name)
            rgb = _hex_to_rgb(color)
            coll = Poly3DCollection(faces, facecolors=rgb, edgecolors="none", alpha=0.9)
            self.ax3d.add_collection3d(coll)
            all_vertices.append(mesh.vertices)

        if all_vertices:
            verts = np.vstack(all_vertices)
            mins = verts.min(axis=0)
            maxs = verts.max(axis=0)
            ranges = maxs - mins
            max_range = max(ranges.max(), 1e-6)
            centers = (mins + maxs) / 2
            self.ax3d.set_xlim(centers[0] - max_range, centers[0] + max_range)
            self.ax3d.set_ylim(centers[1] - max_range, centers[1] + max_range)
            self.ax3d.set_zlim(centers[2] - max_range, centers[2] + max_range)
        else:
            self.ax3d.set_xlim(-10, 10)
            self.ax3d.set_ylim(-10, 10)
            self.ax3d.set_zlim(-1, 10)

        self.ax3d.set_xlabel("X", color="white")
        self.ax3d.set_ylabel("Y", color="white")
        self.ax3d.set_zlabel("Z", color="white")
        self.ax3d.tick_params(colors="white")
        self.canvas3d.draw()

    def _export_3d(self, fmt: str):
        if not self.areas:
            messagebox.showwarning("No roof", "Draw and close an area first.")
            return
        plan = self._build_plan_for_area(self.areas[0])
        if plan is None or not plan.is_valid:
            messagebox.showwarning("No roof", "First area is not valid.")
            return

        config = self.last_config if self.last_config is not None else RoofConfig()

        ext_map = {"skp": "*.skp", "glb": "*.glb", "dae": "*.dae", "obj": "*.obj"}
        title_map = {
            "skp": "SketchUp model",
            "glb": "glTF binary model",
            "dae": "COLLADA model",
            "obj": "Wavefront OBJ model",
        }
        filetypes = [(title_map.get(fmt, "3D model"), ext_map.get(fmt, "*.*"))]
        path = filedialog.asksaveasfilename(
            title=f"Export {title_map.get(fmt, '3D model')}",
            defaultextension=f".{fmt}",
            filetypes=filetypes,
        )
        if not path:
            return

        components = generate_3d_components(plan, config)
        try:
            if fmt == "skp":
                export_skp(components, path)
            elif fmt == "glb":
                export_glb(components, path)
            elif fmt == "dae":
                export_dae(components, path)
            elif fmt == "obj":
                export_obj(components, path)
            messagebox.showinfo("Export complete", f"Saved:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))

    def _save_plan(self):
        file = filedialog.asksaveasfilename(
            title="Save roof plan",
            defaultextension=".toff",
            filetypes=[("TakeOff roof plan", "*.toff")],
        )
        if file:
            data = {
                "version": 1,
                "current": {
                    "dots": [list(p) for p in self.dots],
                    "edges": list(self.edges),
                    "path": self.path,
                    "areas": self.areas,
                    "ventilation_ducts": self.ventilation_ducts,
                    "num_drains": self.num_drains_var.get(),
                },
                "history": self._history,
                "history_pos": self._history_pos,
            }
            with open(file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _migrate_legacy_duct_areas(self):
        roof_areas = []
        known_duct_paths = {frozenset(duct["path"]) for duct in self.ventilation_ducts}
        for area_path in self.areas:
            boundary_edges = []
            for i in range(len(area_path)):
                pair = {area_path[i], area_path[(i + 1) % len(area_path)]}
                edge = next((e for e in self.edges if {e["a"], e["b"]} == pair), None)
                if edge is not None:
                    boundary_edges.append(edge)
            if len(boundary_edges) == len(area_path) and all(e.get("edge_type") == "ventilation_duct" for e in boundary_edges):
                path_key = frozenset(area_path)
                if path_key not in known_duct_paths:
                    first_edge = boundary_edges[0]
                    self.ventilation_ducts.append({
                        "path": list(area_path),
                        "height": first_edge.get("duct_height", 1.0),
                        "include_top": first_edge.get("duct_include_top", True),
                    })
                    known_duct_paths.add(path_key)
            else:
                roof_areas.append(area_path)
        self.areas = roof_areas

    def _load_plan(self, path: str = ""):
        if not path:
            path = filedialog.askopenfilename(
                title="Load roof plan",
                filetypes=[("TakeOff roof plan", "*.toff"), ("JSON plan", "*.json")],
            )
        if path:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            current = data.get("current", data)
            self.dots = [tuple(p) for p in current.get("dots", [])]
            self.edges = [dict(e) for e in current.get("edges", [])]
            self.path = list(current.get("path", []))
            self.areas = [list(a) for a in current.get("areas", [])]
            self.ventilation_ducts = [dict(duct, path=list(duct["path"])) for duct in current.get("ventilation_ducts", [])]
            self._migrate_legacy_duct_areas()
            self.num_drains_var.set(current.get("num_drains", 2))
            self.pencil_start = None
            self.selected_dot = None
            self.selected_edge = None
            if "history" in data and "history_pos" in data:
                self._history = data["history"]
                self._history_pos = data["history_pos"]
            else:
                self._history = []
                self._history_pos = -1
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
        self.canvas_items.append(self.canvas.create_text(self.pan_x + 12, self.pan_y + 18, text="X", fill=X_AXIS_COLOR, font=("", 10, "bold")))
        self.canvas_items.append(self.canvas.create_text(self.pan_x - 18, self.pan_y - 12, text="Y", fill=Y_AXIS_COLOR, font=("", 10, "bold")))

        # edges
        for i, e in enumerate(self.edges):
            p1 = self.dots[e["a"]]
            p2 = self.dots[e["b"]]
            color = {
                "line": "#bdc3c7",
                "parapet": "#3498db",
                "wall": "#e74c3c",
                "ventilation_duct": "#2ecc71",
            }.get(e.get("edge_type"), "#bdc3c7")
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

        # rubber band and alignment guides
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
            length = math.hypot(p2_m[0] - p1[0], p2_m[1] - p1[1])
            mid_x = (c1[0] + self.mouse_x) / 2
            mid_y = (c1[1] + self.mouse_y) / 2
            self.canvas_items.append(self.canvas.create_text(mid_x, mid_y - 12, text=f"{length:.2f}m", fill="white", font=("", 9, "bold")))

            # dashed guide lines from any dot that shares X or Y with the mouse
            for i, p in enumerate(self.dots):
                if i == self.pencil_start:
                    continue
                c = self._m_to_c(*p)
                aligned_x = abs(p[0] - p2_m[0]) < RUBBER_SNAP
                aligned_y = abs(p[1] - p2_m[1]) < RUBBER_SNAP
                if aligned_x and not aligned_y:
                    self.canvas_items.append(self.canvas.create_line(c[0], c[1], self.mouse_x, self.mouse_y, fill="#aaaaaa", width=1, dash=(3, 3)))
                elif aligned_y and not aligned_x:
                    self.canvas_items.append(self.canvas.create_line(c[0], c[1], self.mouse_x, self.mouse_y, fill="#aaaaaa", width=1, dash=(3, 3)))
                elif aligned_x and aligned_y:
                    # mouse is exactly on this dot; draw a small cross
                    self.canvas_items.append(self.canvas.create_line(c[0] - 6, c[1], c[0] + 6, c[1], fill="#f1c40f", width=2))
                    self.canvas_items.append(self.canvas.create_line(c[0], c[1] - 6, c[0], c[1] + 6, fill="#f1c40f", width=2))

        # areas list + total
        self.areas_text.delete("1.0", tk.END)
        area_results = self._calculate_areas()
        total = 0.0
        for idx, r in enumerate(area_results, 1):
            self.areas_text.insert(tk.END, f"Area {idx}: {r['area']:.2f} m², P={r['perimeter']:.2f} m\n")
            for duct_idx, duct in enumerate(r["ducts"], 1):
                self.areas_text.insert(tk.END, f"  Ventilation duct {duct_idx}: closed area {duct['closed_area']:.2f} m²\n")
                self.areas_text.insert(tk.END, f"    Perimeter: {duct['perimeter']:.2f} m, height: {duct['height']:.2f} m\n")
                self.areas_text.insert(tk.END, f"    Vertical area: {duct['vertical_area']:.2f} m²\n")
                if duct["include_top"]:
                    self.areas_text.insert(tk.END, f"    Top area: {duct['top_area']:.2f} m²\n")
                self.areas_text.insert(tk.END, f"    Total duct material area: {duct['total_area']:.2f} m²\n")
                self.areas_text.insert(tk.END, f"    Rail length: {duct['perimeter']:.2f} m\n")
            self.areas_text.insert(tk.END, f"  Vertical parapets area: {r['vertical']:.2f} m²\n")
            self.areas_text.insert(tk.END, f"  Parapets top area: {r['top']:.2f} m²\n")
            self.areas_text.insert(tk.END, f"  Parapets outer side area: {r['side']:.2f} m²\n")
            self.areas_text.insert(tk.END, f"  Total area 1: {r['geotextil_total']:.2f} m² (qty {r['geotextil_qty']:.2f} m²)\n\n")
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


def main(load_path: str = ""):
    root = tk.Tk()
    app = RoofModelerApp(root)
    if load_path and Path(load_path).is_file():
        app._load_plan(load_path)
    root.mainloop()


if __name__ == "__main__":
    main()
