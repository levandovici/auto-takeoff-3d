"""Detailed 3D roof model generation and export.

Produces individual meshes for the structural slab, parapets, walls,
XPS thermal insulation layers, cementoplast slope/counter-slope and screed.
Meshes are returned as trimesh.Trimesh objects so they can be embedded in
a matplotlib 3D view or exported to SKP, GLB, OBJ, DAE etc.
"""

import math
import os
import subprocess
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import trimesh
from shapely.geometry import Point, Polygon
from shapely.ops import triangulate, unary_union

from calculator import RoofConfig
from roof_plan import RoofEdge, RoofPlan


INCHES_PER_METER = 39.37007874


def _to_inches(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Return a copy of the mesh scaled from meters to inches."""
    m = mesh.copy()
    m.apply_scale(INCHES_PER_METER)
    return m


def _triangulate_z(poly: Polygon, z: float) -> np.ndarray:
    """Return (N,3,3) triangles for a polygon lying at constant z (meters)."""
    triangles = []
    for tri in triangulate(poly):
        coords = list(tri.exterior.coords)[:-1]
        triangle = [(x, y, z) for x, y in coords]
        triangles.append(triangle)
    return np.array(triangles, dtype=float) if triangles else np.zeros((0, 3, 3), dtype=float)


def _triangles_to_mesh(triangles: np.ndarray, color: Optional[List[int]] = None) -> trimesh.Trimesh:
    """Convert (N,3,3) triangles to a trimesh.Trimesh."""
    if len(triangles) == 0:
        return trimesh.Trimesh()
    vertices = triangles.reshape(-1, 3)
    faces = np.arange(len(vertices)).reshape(-1, 3)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    if color:
        mesh.visual.vertex_colors = color * len(mesh.vertices) if len(color) == 3 else color
    return mesh


def _extrude_polygon(poly, z_bottom: float, z_top: float) -> trimesh.Trimesh:
    """Extrude a shapely Polygon or MultiPolygon along the Z axis."""
    if poly.is_empty:
        return trimesh.Trimesh()

    # unary_union of edge strips can produce a MultiPolygon
    polys = [poly] if isinstance(poly, Polygon) else [
        g for g in getattr(poly, "geoms", []) if isinstance(g, Polygon) and not g.is_empty
    ]

    meshes = []
    height = z_top - z_bottom
    for p in polys:
        try:
            mesh = trimesh.creation.extrude_polygon(p, height=height)
        except Exception:
            # Fallback for tricky polygons: triangulate top/bottom and build side walls manually
            mesh = _extrude_triangulated(p, z_bottom, z_top)
        else:
            mesh.vertices[:, 2] += z_bottom
        meshes.append(mesh)

    meshes = [m for m in meshes if len(m.faces) > 0]
    if not meshes:
        return trimesh.Trimesh()
    return trimesh.util.concatenate(meshes)


def _extrude_triangulated(poly: Polygon, z_bottom: float, z_top: float) -> trimesh.Trimesh:
    """Fallback extrusion using triangulated caps and vertical walls."""
    meshes = []
    top = _triangulate_z(poly, z_top)
    bottom = _triangulate_z(poly, z_bottom)
    # Flip bottom triangles so normals point down
    bottom = bottom[:, ::-1, :]
    meshes.append(_triangles_to_mesh(top))
    meshes.append(_triangles_to_mesh(bottom))

    coords = list(poly.exterior.coords)[:-1]
    for i in range(len(coords)):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % len(coords)]
        wall = [
            (x1, y1, z_bottom),
            (x2, y2, z_bottom),
            (x2, y2, z_top),
            (x1, y1, z_top),
        ]
        wall_mesh = trimesh.creation.extrude_polygon(Polygon(wall), height=0.0)
        meshes.append(wall_mesh)

    return trimesh.util.concatenate([m for m in meshes if len(m.faces) > 0])


def build_slab(plan: RoofPlan, thickness: float = 0.25) -> trimesh.Trimesh:
    """Structural concrete slab (meters)."""
    return _extrude_polygon(plan.polygon, -thickness, 0.0)


def build_parapets(plan: RoofPlan, height: float = 0.5, top_width: float = 0.2) -> trimesh.Trimesh:
    """Parapet volumes around parapet-type edges."""
    parapet_edges = [e for e in plan.edges if e.is_parapet]
    if not parapet_edges:
        return trimesh.Trimesh()
    strips = []
    for edge in parapet_edges:
        p1, p2 = np.array(edge.p1), np.array(edge.p2)
        d = p2 - p1
        length = float(np.linalg.norm(d))
        if length < 1e-9:
            continue
        n = np.array([-d[1], d[0]]) / length
        rect = Polygon([
            tuple(p1),
            tuple(p2),
            tuple(p2 + n * top_width),
            tuple(p1 + n * top_width),
        ])
        strips.append(rect)
    if not strips:
        return trimesh.Trimesh()
    ring = unary_union(strips)
    if ring.is_empty:
        return trimesh.Trimesh()
    return _extrude_polygon(ring, 0.0, height)


def build_walls(plan: RoofPlan, height: float = 2.5, width: float = 0.15) -> trimesh.Trimesh:
    """Wall volumes along wall-type edges."""
    wall_edges = [e for e in plan.edges if e.is_wall]
    if not wall_edges:
        return trimesh.Trimesh()
    strips = []
    for edge in wall_edges:
        p1, p2 = np.array(edge.p1), np.array(edge.p2)
        d = p2 - p1
        length = float(np.linalg.norm(d))
        if length < 1e-9:
            continue
        n = np.array([-d[1], d[0]]) / length
        # Wall sits outside the roof footprint
        rect = Polygon([
            tuple(p1),
            tuple(p2),
            tuple(p2 + n * width),
            tuple(p1 + n * width),
        ])
        strips.append(rect)
    if not strips:
        return trimesh.Trimesh()
    union = unary_union(strips)
    return _extrude_polygon(union, 0.0, height)


def _thermal_slab_layer_heights(config: RoofConfig) -> List[float]:
    """Thickness of each XPS slab layer in meters."""
    total = config.thermal_slab_height_cm / 100.0
    if config.thermal_slab_layers == 1:
        return [total]
    if config.thermal_slab_height_cm == 10.0:
        return [0.05, 0.05]
    if config.thermal_slab_height_cm == 15.0:
        return [0.10, 0.05]
    if config.thermal_slab_height_cm == 20.0:
        return [0.10, 0.10]
    half = total / 2.0
    return [half, half]


def build_xps_slab_layers(plan: RoofPlan, config: RoofConfig) -> Dict[str, trimesh.Trimesh]:
    """XPS thermal insulation layers on top of the structural slab."""
    if not config.thermal_slab_enabled:
        return {}
    layers: Dict[str, trimesh.Trimesh] = {}
    z = 0.0
    heights = _thermal_slab_layer_heights(config)
    for idx, h in enumerate(heights, start=1):
        mesh = _extrude_polygon(plan.polygon, z, z + h)
        layers[f"XPS slab layer {idx} ({config.thermal_slab_height_cm:.0f}cm total, {h*100:.0f}cm)"] = mesh
        z += h
    return layers


def _build_xps_strip_along_edge(edge: RoofEdge, z_bottom: float, z_top: float,
                               thickness: float, inside: bool = True) -> trimesh.Trimesh:
    """Thin XPS strip on a vertical wall/parapet face."""
    p1, p2 = np.array(edge.p1), np.array(edge.p2)
    d = p2 - p1
    length = float(np.linalg.norm(d))
    if length < 1e-9:
        return trimesh.Trimesh()
    n = np.array([-d[1], d[0]]) / length
    if not inside:
        n = -n
    # The strip is on the inside face and extends inward by thickness
    inner_p1 = p1 - n * thickness
    inner_p2 = p2 - n * thickness
    rect = Polygon([
        tuple(p1),
        tuple(p2),
        tuple(inner_p2),
        tuple(inner_p1),
    ])
    return _extrude_polygon(rect, z_bottom, z_top)


def build_xps_parapet(plan: RoofPlan, config: RoofConfig) -> trimesh.Trimesh:
    """XPS insulation on the interior vertical faces of parapets."""
    if not config.thermal_parapet_enabled:
        return trimesh.Trimesh()
    thickness = config.thermal_parapet_width_cm / 100.0
    meshes = []
    for edge in plan.edges:
        if not edge.is_parapet:
            continue
        h = edge.parapet_height
        m = _build_xps_strip_along_edge(edge, 0.0, h, thickness, inside=True)
        meshes.append(m)
    if not meshes:
        return trimesh.Trimesh()
    return trimesh.util.concatenate([m for m in meshes if len(m.faces) > 0])


def build_xps_walls(plan: RoofPlan, config: RoofConfig) -> trimesh.Trimesh:
    """XPS insulation on wall-type edges."""
    if not config.thermal_parapet_enabled:
        return trimesh.Trimesh()
    thickness = config.thermal_parapet_wall_width_cm / 100.0
    meshes = []
    for edge in plan.edges:
        if not edge.is_wall:
            continue
        h = edge.wall_height
        m = _build_xps_strip_along_edge(edge, 0.0, h, thickness, inside=True)
        meshes.append(m)
    if not meshes:
        return trimesh.Trimesh()
    return trimesh.util.concatenate([m for m in meshes if len(m.faces) > 0])


def _point_distance_to_boundary(poly: Polygon, x: float, y: float) -> float:
    """Shortest distance from a point to the polygon boundary."""
    return poly.exterior.distance(Point(float(x), float(y)))


def _build_sloped_surface(plan: RoofPlan, base_z: float, min_thickness: float,
                          config: RoofConfig) -> trimesh.Trimesh:
    """Create a triangulated surface showing base slope + counter-slope."""
    poly = plan.polygon
    minx, miny, maxx, maxy = poly.bounds
    # Use a regular grid; cell size ~ 0.25 m for decent detail without being huge
    cell = 0.25
    nx = max(2, int(math.ceil((maxx - minx) / cell)) + 1)
    ny = max(2, int(math.ceil((maxy - miny) / cell)) + 1)
    xs = np.linspace(minx, maxx, nx)
    ys = np.linspace(miny, maxy, ny)

    # Base slope geometry
    if config.base_slope_direction == "length":
        span = maxx - minx
        high_axis = 0  # X
    else:
        span = maxy - miny
        high_axis = 1  # Y
    h_base = span * (config.base_slope_pct / 100.0)

    # Counter-slope geometry
    if config.base_slope_direction == "length":
        counter_span = (maxy - miny) / 2.0
    else:
        counter_span = (maxx - minx) / 2.0
    if config.counter_slope_extent == "half":
        counter_span /= 2.0
    h_counter = counter_span * 2.0 * (config.counter_slope_pct / 100.0)

    vertices = []
    indices = {}
    idx = 0
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            p = Point(float(x), float(y))
            if not poly.contains(p):
                indices[(i, j)] = -1
                continue
            if high_axis == 0:
                dist_high = x - minx
            else:
                dist_high = y - miny
            base_drop = (dist_high / span) * h_base if span > 0 else 0.0
            d_wall = _point_distance_to_boundary(poly, x, y)
            if d_wall < counter_span and counter_span > 0:
                wall_rise = h_counter * (1.0 - d_wall / counter_span)
            else:
                wall_rise = 0.0
            z = base_z + min_thickness + base_drop + wall_rise
            vertices.append([x, y, z])
            indices[(i, j)] = idx
            idx += 1

    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = indices.get((i, j), -1)
            b = indices.get((i + 1, j), -1)
            c = indices.get((i + 1, j + 1), -1)
            d = indices.get((i, j + 1), -1)
            if a >= 0 and b >= 0 and c >= 0 and d >= 0:
                faces.append([a, b, c])
                faces.append([a, c, d])

    if not faces:
        return trimesh.Trimesh()

    top = trimesh.Trimesh(vertices=np.array(vertices, dtype=float), faces=np.array(faces, dtype=int))
    # Build a solid by adding a flat bottom at base_z so it has visible thickness
    bottom = top.copy()
    bottom.vertices = bottom.vertices.copy()
    bottom.vertices[:, 2] = base_z
    bottom.invert()  # flip normals down
    return trimesh.util.concatenate([top, bottom])


def build_cementoplast(plan: RoofPlan, config: RoofConfig,
                       base_z: float = 0.0, min_thickness: float = 0.03) -> trimesh.Trimesh:
    """Cementoplast slope/counter-slope layer."""
    if not config.cementoplast_enabled:
        return trimesh.Trimesh()
    return _build_sloped_surface(plan, base_z, min_thickness, config)


def build_screed(plan: RoofPlan, config: RoofConfig, base_z: float = 0.0,
                 thickness: float = 0.05) -> trimesh.Trimesh:
    """Protective screed on top of the cementoplast."""
    if not config.screed_enabled:
        return trimesh.Trimesh()
    return _extrude_polygon(plan.polygon, base_z, base_z + thickness)


def generate_3d_components(plan: RoofPlan, config: RoofConfig) -> Dict[str, trimesh.Trimesh]:
    """Build all roof components as individual meshes (meters)."""
    components: Dict[str, trimesh.Trimesh] = {}

    # Structural slab
    components["Slab"] = build_slab(plan)

    # Edges
    parapet_height = max(e.parapet_height for e in plan.edges) if any(e.is_parapet for e in plan.edges) else 0.5
    top_width = max(e.parapet_top_width for e in plan.edges) if any(e.is_parapet for e in plan.edges) else 0.2
    wall_height = max(e.wall_height for e in plan.edges) if any(e.is_wall for e in plan.edges) else 2.5
    components["Parapets"] = build_parapets(plan, height=parapet_height, top_width=top_width)
    components["Walls"] = build_walls(plan, height=wall_height, width=0.15)

    # XPS slab
    xps_layers = build_xps_slab_layers(plan, config)
    components.update(xps_layers)

    # XPS on vertical faces
    if config.thermal_parapet_enabled:
        components["XPS parapet faces"] = build_xps_parapet(plan, config)
        components["XPS wall faces"] = build_xps_walls(plan, config)

    # Stacking height for cementoplast/screed
    z_stack = 0.0
    heights = _thermal_slab_layer_heights(config)
    if config.thermal_slab_enabled:
        z_stack += sum(heights)

    components["Cementoplast"] = build_cementoplast(plan, config, base_z=z_stack)
    if not components["Cementoplast"].is_empty:
        # Approx top of cementoplast is base_z + min thickness; actual surface varies with slope
        z_stack += 0.03

    components["Screed"] = build_screed(plan, config, base_z=z_stack)

    return components


def _components_to_scene(components: Dict[str, trimesh.Trimesh]) -> trimesh.Trimesh:
    """Merge all component meshes into one scene, coloring each differently."""
    meshes = []
    palette = [
        [200, 200, 200, 255],   # Slab gray
        [180, 120, 80, 255],    # Parapets brown
        [160, 160, 160, 255],   # Walls gray
        [0, 150, 200, 255],     # XPS blue
        [0, 180, 220, 255],
        [34, 139, 34, 255],     # Cementoplast green
        [255, 200, 100, 255],   # Screed tan
    ]
    for i, (name, mesh) in enumerate(components.items()):
        if mesh.is_empty:
            continue
        color = palette[i % len(palette)]
        colored = mesh.copy()
        colored.visual.vertex_colors = color
        meshes.append(colored)
    if not meshes:
        return trimesh.Trimesh()
    return trimesh.util.concatenate(meshes)


def export_glb(components: Dict[str, trimesh.Trimesh], path: str) -> None:
    """Export components to a GLB (glTF 2.0 binary) file."""
    scene = trimesh.Scene()
    for name, mesh in components.items():
        if mesh.is_empty:
            continue
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    scene.export(path)


def export_obj(components: Dict[str, trimesh.Trimesh], path: str) -> None:
    """Export components to an OBJ file (with MTL)."""
    scene = trimesh.Scene()
    for name, mesh in components.items():
        if mesh.is_empty:
            continue
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    scene.export(path)


def export_dae(components: Dict[str, trimesh.Trimesh], path: str) -> None:
    """Export components to a COLLADA .dae file (SketchUp can import)."""
    meshes = [m for m in components.values() if not m.is_empty]
    if not meshes:
        raise ValueError("No geometry to export")
    combined = trimesh.util.concatenate(meshes)
    combined.export(path, file_type="dae")


def export_skp(components: Dict[str, trimesh.Trimesh], path: str,
               material_colors: Optional[Dict[str, Tuple[int, int, int]]] = None) -> None:
    """Export components to a SketchUp .skp file using OpenSKP (units = inches)."""
    try:
        from openskp import create
    except ImportError as exc:  # pragma: no cover
        raise ImportError("OpenSKP is required for .skp export: pip install openskp") from exc

    builder = create()
    default_colors = material_colors or {
        "Slab": (180, 180, 180),
        "Parapets": (180, 120, 80),
        "Walls": (160, 160, 160),
        "XPS": (0, 150, 200),
        "Cementoplast": (34, 139, 34),
        "Screed": (255, 200, 100),
        "Other": (200, 200, 200),
    }

    # Materials must be added before any layer
    material_handles = {}
    for name, mesh in components.items():
        if mesh.is_empty:
            continue
        color = default_colors.get(name, default_colors["Other"])
        material_handles[name] = builder.add_material(name, color)

    layer = builder.add_layer("Roof 3D")

    for name, mesh in components.items():
        if mesh.is_empty or name not in material_handles:
            continue
        mesh_in = _to_inches(mesh)
        for face in mesh_in.faces:
            pts = [tuple(mesh_in.vertices[v]) for v in face]
            # OpenSKP expects points ordered to form a planar face; triangles are fine
            builder.add_face(pts, material=material_handles[name], layer=layer)

    builder.save(path)


_PREVIEW_DIR = os.path.join(tempfile.gettempdir(), "auto_takeoff_3d_preview")
os.makedirs(_PREVIEW_DIR, exist_ok=True)


def preview_polyscope(components: Dict[str, trimesh.Trimesh]) -> Optional[subprocess.Popen]:
    """Launch Polyscope in a separate process to preview the given components."""
    glb_path = os.path.join(_PREVIEW_DIR, "preview.glb")
    try:
        export_glb(components, glb_path)
    except Exception as exc:
        messagebox.showerror("Preview failed", f"Could not prepare preview:\n{exc}")
        return None

    cmd = [
        sys.executable,
        "-c",
        (
            "import trimesh, polyscope as ps; "
            f"scene = trimesh.load({glb_path!r}, force='scene'); "
            "ps.set_program_name('Auto Takeoff 3D Preview'); "
            "ps.init(); "
            "[ps.register_surface_mesh(name, geom.vertices, geom.faces) "
            "for name, geom in scene.geometry.items()]; "
            "ps.show()"
        ),
    ]
    try:
        kwargs: Dict[str, Any] = {}
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(cmd, **kwargs)
    except Exception as exc:
        messagebox.showerror("Preview failed", f"Could not launch Polyscope:\n{exc}")
        return None


class GenerateModelDialog(tk.Toplevel):
    """Dialog to toggle roof components and export to 3D formats."""

    COLORS = {
        "Slab": "#b0b0b0",
        "Parapets": "#c19a6b",
        "Walls": "#808080",
        "XPS": "#00a8e8",
        "XPS slab": "#00a8e8",
        "XPS parapet": "#00c8ff",
        "XPS wall": "#0088cc",
        "Cementoplast": "#2e8b57",
        "Screed": "#f4c430",
    }

    def __init__(self, parent, components: Dict[str, trimesh.Trimesh]):
        super().__init__(parent)
        self.title("Generated 3D model")
        self.geometry("420x520")
        self.resizable(False, True)
        self.transient(parent)

        self.components = components
        self.vars: Dict[str, tk.BooleanVar] = {}

        self._build_ui()
        self.focus_set()

    def _build_ui(self):
        ttk.Label(self, text="Toggle elements and export", font=("", 10, "bold")).pack(pady=(10, 5))

        check_frame = ttk.LabelFrame(self, text="Visible components")
        check_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        if not self.components:
            ttk.Label(check_frame, text="No geometry was generated for this plan.").pack(padx=10, pady=10)
        else:
            all_btn_frame = ttk.Frame(check_frame)
            all_btn_frame.pack(anchor=tk.W, padx=5, pady=2)
            ttk.Button(all_btn_frame, text="All on", command=self._all_on).pack(side=tk.LEFT, padx=2)
            ttk.Button(all_btn_frame, text="All off", command=self._all_off).pack(side=tk.LEFT, padx=2)

            for name, mesh in sorted(self.components.items()):
                var = tk.BooleanVar(value=not mesh.is_empty)
                self.vars[name] = var
                chk = ttk.Checkbutton(check_frame, text=name, variable=var)
                chk.pack(anchor=tk.W, padx=5, pady=1)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btn_frame, text="Export SKP", command=self._export_skp).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Export 3D...", command=self._export_3d).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT, padx=2)

    def _all_on(self):
        for var in self.vars.values():
            var.set(True)

    def _all_off(self):
        for var in self.vars.values():
            var.set(False)

    def _selected_components(self) -> Dict[str, trimesh.Trimesh]:
        return {name: mesh for name, mesh in self.components.items() if self.vars[name].get()}

    def _export_skp(self):
        selected = self._selected_components()
        if not selected:
            messagebox.showwarning("No selection", "Select at least one component to export.")
            return
        path = filedialog.asksaveasfilename(
            title="Export SketchUp model",
            defaultextension=".skp",
            filetypes=[("SketchUp files", "*.skp")],
        )
        if not path:
            return
        try:
            export_skp(selected, path)
            messagebox.showinfo("Export complete", f"Saved SketchUp model:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))

    def _export_3d(self):
        selected = self._selected_components()
        if not selected:
            messagebox.showwarning("No selection", "Select at least one component to export.")
            return
        path = filedialog.asksaveasfilename(
            title="Export 3D model",
            defaultextension=".glb",
            filetypes=[("glTF binary", "*.glb"), ("Wavefront OBJ", "*.obj"), ("COLLADA", "*.dae")],
        )
        if not path:
            return
        try:
            ext = Path(path).suffix.lower()
            if ext == ".glb":
                export_glb(selected, path)
            elif ext == ".obj":
                export_obj(selected, path)
            elif ext == ".dae":
                export_dae(selected, path)
            else:
                export_glb(selected, path)
            messagebox.showinfo("Export complete", f"Saved 3D model:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
