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
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import split, triangulate, unary_union

from calculator import RoofConfig
from roof_plan import RoofEdge, RoofPlan


INCHES_PER_METER = 39.37007874


def _center_window(window: tk.Toplevel, parent: tk.Widget) -> None:
    """Center a popup window over its parent."""
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    px = parent.winfo_x()
    py = parent.winfo_y()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    x = px + (pw - width) // 2
    y = py + (ph - height) // 2
    window.geometry(f"+{x}+{y}")


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


def build_xps_slab_layers(plan: RoofPlan, config: RoofConfig,
                          base_z: float = 0.0) -> Dict[str, trimesh.Trimesh]:
    """XPS thermal insulation layers on top of the structural slab."""
    if not config.thermal_slab_enabled:
        return {}
    layers: Dict[str, trimesh.Trimesh] = {}
    z = base_z
    heights = _thermal_slab_layer_heights(config)
    for idx, h in enumerate(heights, start=1):
        mesh = _extrude_polygon(plan.polygon, z, z + h)
        layers[f"XPS slab layer {idx} ({config.thermal_slab_height_cm:.0f}cm total, {h*100:.0f}cm)"] = mesh
        z += h
    return layers


def build_additional_slab_epp(plan: RoofPlan, config: RoofConfig,
                              thickness: float = 0.003) -> trimesh.Trimesh:
    """Additional bitum EPP over the slab and up the parapet faces."""
    if (config.waterproofing_group != "bitum" or
            not config.thermal_slab_enabled or
            not config.thermal_slab_bitum_epp):
        return trimesh.Trimesh()

    meshes = [_extrude_polygon(plan.polygon, 0.0, thickness)]
    upstand_height = config.thermal_slab_height_cm / 100.0 + 0.15
    for edge in plan.edges:
        if not edge.is_parapet:
            continue
        mesh = _build_xps_strip_along_edge(
            edge, 0.0, upstand_height, thickness, inside=True
        )
        if not mesh.is_empty:
            meshes.append(mesh)
    return trimesh.util.concatenate(meshes)


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
    inner_p1 = p1 + n * thickness
    inner_p2 = p2 + n * thickness
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


def _insert_intersections(ring: List[Tuple[float, float]], line: LineString) -> List[Tuple[float, float]]:
    """Insert points where the ring edges cross the given line, preserving order."""
    if len(ring) < 2:
        return list(ring)
    result: List[Tuple[float, float]] = []
    for i in range(len(ring)):
        p1 = Point(ring[i])
        p2 = Point(ring[(i + 1) % len(ring)])
        edge = LineString([p1, p2])
        result.append(ring[i])
        inter = edge.intersection(line)
        if inter.is_empty:
            continue
        points = []
        if isinstance(inter, Point):
            points.append((float(inter.x), float(inter.y)))
        elif hasattr(inter, "geoms"):
            for g in inter.geoms:
                if isinstance(g, Point):
                    points.append((float(g.x), float(g.y)))
        if not points:
            continue
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        edge_len_sq = dx * dx + dy * dy
        def _t(pt):
            if edge_len_sq < 1e-18:
                return 0.0
            return ((pt[0] - p1.x) * dx + (pt[1] - p1.y) * dy) / edge_len_sq
        points = sorted(points, key=_t)
        last = ring[i]
        next_pt = ring[(i + 1) % len(ring)]
        for pt in points:
            if math.hypot(pt[0] - last[0], pt[1] - last[1]) < 1e-8:
                continue
            if math.hypot(pt[0] - next_pt[0], pt[1] - next_pt[1]) < 1e-8:
                continue
            result.append(pt)
            last = pt
    deduped: List[Tuple[float, float]] = []
    for pt in result:
        if deduped and math.hypot(pt[0] - deduped[-1][0], pt[1] - deduped[-1][1]) < 1e-8:
            continue
        deduped.append(pt)
    return deduped


def _build_sloped_surface(plan: RoofPlan, base_z: float, min_thickness: float,
                          config: RoofConfig) -> trimesh.Trimesh:
    """Create a watertight cementoplast slope with center-ridge or border-to-border fall."""
    poly = plan.polygon
    if poly.is_empty:
        return trimesh.Trimesh()

    slope = config.base_slope_pct / 100.0
    minx, miny, maxx, maxy = poly.bounds
    center_x = (minx + maxx) / 2.0
    center_y = (miny + maxy) / 2.0

    direction = config.base_slope_direction
    if direction == "length":
        split_line = LineString([(center_x, miny - 1.0), (center_x, maxy + 1.0)])
        def _thickness_at(x: float, y: float) -> float:
            return min_thickness + slope * abs(float(x) - center_x)
    elif direction == "width":
        split_line = LineString([(minx - 1.0, center_y), (maxx + 1.0, center_y)])
        def _thickness_at(x: float, y: float) -> float:
            return min_thickness + slope * abs(float(y) - center_y)
    elif direction == "left":
        split_line = LineString([(minx - 1.0, miny - 1.0), (minx - 1.0, maxy + 1.0)])
        def _thickness_at(x: float, y: float) -> float:
            return min_thickness + slope * (float(x) - minx)
    elif direction == "right":
        split_line = LineString([(maxx + 1.0, miny - 1.0), (maxx + 1.0, maxy + 1.0)])
        def _thickness_at(x: float, y: float) -> float:
            return min_thickness + slope * (maxx - float(x))
    elif direction == "forward":
        split_line = LineString([(minx - 1.0, maxy + 1.0), (maxx + 1.0, maxy + 1.0)])
        def _thickness_at(x: float, y: float) -> float:
            return min_thickness + slope * (maxy - float(y))
    else:
        split_line = LineString([(minx - 1.0, miny - 1.0), (maxx + 1.0, miny - 1.0)])
        def _thickness_at(x: float, y: float) -> float:
            return min_thickness + slope * (float(y) - miny)

    # Unified vertex pool. Ridge points (where top height equals base_z) are
    # stored as a single vertex shared by the top sheet, bottom sheet and walls.
    vertices: List[Tuple[float, float, float]] = []
    vertex_map: Dict[Tuple[float, float], Tuple[int, int]] = {}

    def _get_indices(x: float, y: float) -> Tuple[int, int]:
        key = (round(float(x), 9), round(float(y), 9))
        if key in vertex_map:
            return vertex_map[key]
        z_top = base_z + _thickness_at(x, y)
        z_bot = base_z
        if abs(z_top - z_bot) < 1e-9:
            idx = len(vertices)
            vertices.append((x, y, z_top))
            vertex_map[key] = (idx, idx)
        else:
            top_idx = len(vertices)
            vertices.append((x, y, z_top))
            bot_idx = len(vertices)
            vertices.append((x, y, z_bot))
            vertex_map[key] = (top_idx, bot_idx)
        return vertex_map[key]

    def _top_vi(x: float, y: float) -> int:
        return _get_indices(x, y)[0]

    def _bottom_vi(x: float, y: float) -> int:
        return _get_indices(x, y)[1]

    faces: List[List[int]] = []

    # Top surface: split by the ridge/center line so each half can be triangulated
    # with a planar top surface. This gives the exact V-shape and creates the
    # internal ridge edge (shared by exactly two top faces).
    split_result = split(poly, split_line)
    top_parts = [
        g for g in getattr(split_result, "geoms", [split_result])
        if isinstance(g, Polygon) and not g.is_empty
    ]
    for part in top_parts:
        for tri in triangulate(part):
            coords = list(tri.exterior.coords)[:-1]
            if len(coords) != 3:
                continue
            faces.append([_top_vi(x, y) for x, y in coords])

    # Bottom surface: triangulate the original polygon, then insert any ridge
    # points that lie on its boundary edges. This keeps the ridge points on the
    # bottom boundary (so vertical walls can connect) while avoiding an internal
    # ridge edge in the bottom sheet.
    tri_verts_xy, tri_faces = trimesh.creation.triangulate_polygon(poly)
    tri_verts_xy = np.array(tri_verts_xy, dtype=float)

    # Keep every vertex returned by triangulate_polygon. Some triangulation
    # engines include a closing vertex that duplicates the first coordinate and
    # still reference its distinct index from tri_faces. Removing it leaves
    # valid face indices pointing past the end of bottom_verts.
    bottom_verts: List[Tuple[float, float]] = [(float(x), float(y)) for x, y in tri_verts_xy]
    bottom_faces: List[List[int]] = [[int(a), int(b), int(c)] for a, b, c in tri_faces
                                      if not (int(a) == int(b) == int(c))]

    # Find all ridge points that lie on the original polygon boundary.
    ridge_points: List[Tuple[float, float]] = []
    boundary = poly.boundary
    ridge_inter = boundary.intersection(split_line)
    if isinstance(ridge_inter, Point):
        ridge_points.append((float(ridge_inter.x), float(ridge_inter.y)))
    elif hasattr(ridge_inter, "geoms"):
        for g in ridge_inter.geoms:
            if isinstance(g, Point):
                ridge_points.append((float(g.x), float(g.y)))

    def _point_on_segment(p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float], tol: float = 1e-9) -> bool:
        ap = (p[0] - a[0], p[1] - a[1])
        ab = (b[0] - a[0], b[1] - a[1])
        ab_len_sq = ab[0] ** 2 + ab[1] ** 2
        if ab_len_sq < tol:
            return math.hypot(ap[0], ap[1]) < tol
        t = (ap[0] * ab[0] + ap[1] * ab[1]) / ab_len_sq
        if t < -tol or t > 1 + tol:
            return False
        closest = (a[0] + t * ab[0], a[1] + t * ab[1])
        return math.hypot(p[0] - closest[0], p[1] - closest[1]) < tol

    for rp in ridge_points:
        # Skip if it coincides with an existing bottom vertex.
        skip = False
        for vi, v in enumerate(bottom_verts):
            if math.hypot(v[0] - rp[0], v[1] - rp[1]) < 1e-9:
                skip = True
                break
        if skip:
            continue
        # Find the edge containing this ridge point and split adjacent faces.
        edge_to_faces: Dict[Tuple[int, int], List[int]] = {}
        for fi, f in enumerate(bottom_faces):
            for k in range(3):
                edge = tuple(sorted([f[k], f[(k + 1) % 3]]))
                edge_to_faces.setdefault(edge, []).append(fi)

        split_edge = None
        for edge, adjacent in edge_to_faces.items():
            a, b = edge
            if _point_on_segment(rp, bottom_verts[a], bottom_verts[b]):
                split_edge = (a, b, adjacent)
                break
        if split_edge is None:
            continue
        a, b, adjacent = split_edge
        new_idx = len(bottom_verts)
        bottom_verts.append(rp)
        replacements: Dict[int, List[int]] = {}
        for fi in adjacent:
            f = bottom_faces[fi]
            other = [v for v in f if v not in (a, b)]
            if len(other) != 1:
                continue
            c = other[0]
            # Replace triangle (a,b,c) with (a,new,c) and (new,b,c).
            replacements[fi] = [[a, new_idx, c], [new_idx, b, c]]
        for fi in sorted(replacements.keys(), reverse=True):
            old = bottom_faces.pop(fi)
            for nf in reversed(replacements[fi]):
                bottom_faces.insert(fi, nf)

    # Add bottom faces to the unified mesh with downward normals.
    bottom_index_local: Dict[Tuple[float, float], int] = {}
    def _map_bottom_vert(x: float, y: float) -> int:
        key = (round(float(x), 9), round(float(y), 9))
        if key not in bottom_index_local:
            bottom_index_local[key] = _bottom_vi(x, y)
        return bottom_index_local[key]

    for f in bottom_faces:
        x1, y1 = bottom_verts[f[0]]
        x2, y2 = bottom_verts[f[1]]
        x3, y3 = bottom_verts[f[2]]
        # Invert so normals point down.
        faces.append([_map_bottom_vert(x1, y1), _map_bottom_vert(x3, y3), _map_bottom_vert(x2, y2)])

    def _is_degenerate(f: List[int]) -> bool:
        v0 = np.array(vertices[f[0]])
        v1 = np.array(vertices[f[1]])
        v2 = np.array(vertices[f[2]])
        return float(np.linalg.norm(np.cross(v1 - v0, v2 - v0))) < 1e-12

    # Vertical walls along the augmented rings to close the solid.
    augmented_exterior = _insert_intersections(list(poly.exterior.coords)[:-1], split_line)
    augmented_interiors = [
        _insert_intersections(list(interior.coords)[:-1], split_line)
        for interior in poly.interiors
    ]
    rings = [augmented_exterior] + augmented_interiors
    for ring_idx, ring in enumerate(rings):
        exterior = ring_idx == 0
        m = len(ring)
        for i in range(m):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % m]
            at = _top_vi(x1, y1)
            bt = _top_vi(x2, y2)
            ab = _bottom_vi(x1, y1)
            bb = _bottom_vi(x2, y2)

            at_ridge = vertices[at][2] == base_z
            bt_ridge = vertices[bt][2] == base_z

            candidates: List[List[int]] = []
            if exterior:
                # Exterior ring is CCW; outward normal points away from polygon interior.
                if at_ridge and bt_ridge:
                    continue
                if at_ridge:
                    # A_top == A_bottom; wall is a single triangle A-B_bottom-B_top.
                    candidates.append([at, bb, bt])
                elif bt_ridge:
                    # B_top == B_bottom; wall is a single triangle A_top-A_bottom-B.
                    candidates.append([at, ab, bb])
                else:
                    candidates.append([at, bb, bt])
                    candidates.append([at, ab, bb])
            else:
                # Interior rings are CW; outward normal points into the hole.
                if at_ridge and bt_ridge:
                    continue
                if at_ridge:
                    candidates.append([at, bt, bb])
                elif bt_ridge:
                    candidates.append([at, bb, ab])
                else:
                    candidates.append([at, bt, bb])
                    candidates.append([at, bb, ab])

            for f in candidates:
                if not _is_degenerate(f):
                    faces.append(f)

    if not faces:
        return trimesh.Trimesh()

    return trimesh.Trimesh(
        vertices=np.array(vertices, dtype=float),
        faces=np.array(faces, dtype=int),
        process=False,
    )


def build_cementoplast(plan: RoofPlan, config: RoofConfig,
                       base_z: float = 0.0, min_thickness: float = 0.0) -> trimesh.Trimesh:
    """Build the configured center-ridge or border-to-border cementoplast slope."""
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

    epp_enabled = (
        config.waterproofing_group == "bitum" and
        config.thermal_slab_enabled and
        config.thermal_slab_bitum_epp
    )
    epp_thickness = 0.003 if epp_enabled else 0.0
    components["Additional bitum EPP floor slab"] = build_additional_slab_epp(plan, config)

    # XPS slab
    xps_layers = build_xps_slab_layers(plan, config, base_z=epp_thickness)
    components.update(xps_layers)

    # XPS on vertical faces
    if config.thermal_parapet_enabled:
        components["XPS parapet faces"] = build_xps_parapet(plan, config)
        components["XPS wall faces"] = build_xps_walls(plan, config)

    # Stacking height for cementoplast/screed
    z_stack = epp_thickness
    heights = _thermal_slab_layer_heights(config)
    if config.thermal_slab_enabled:
        z_stack += sum(heights)

    components["Cementoplast"] = build_cementoplast(plan, config, base_z=z_stack)
    if not components["Cementoplast"].is_empty:
        # Place the next layer on top of the highest cementoplast point.
        z_stack = float(components["Cementoplast"].bounds[1, 2])

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
        "Additional bitum EPP": (47, 79, 79),
        "Slab": (180, 180, 180),
        "Parapets": (180, 120, 80),
        "Walls": (160, 160, 160),
        "XPS": (0, 150, 200),
        "Cementoplast": (34, 139, 34),
        "Screed": (255, 200, 100),
        "Other": (200, 200, 200),
    }

    def _component_name(name: str) -> str:
        return name.split(": ", 1)[-1]

    def _component_color(name: str) -> Tuple[int, int, int]:
        component_name = _component_name(name)
        for prefix, color in default_colors.items():
            if component_name.startswith(prefix):
                return color
        return default_colors["Other"]

    material_handles = {}
    for name, mesh in components.items():
        if mesh.is_empty:
            continue
        material_handles[name] = builder.add_material(name, _component_color(name))

    layer_handles = {}
    for name, mesh in components.items():
        if mesh.is_empty:
            continue
        layer_name = _component_name(name)
        if layer_name not in layer_handles:
            layer_handles[layer_name] = builder.add_layer(layer_name, color=_component_color(name))

    for name, mesh in components.items():
        if mesh.is_empty or name not in material_handles:
            continue
        mesh_in = _to_inches(mesh)
        layer_name = _component_name(name)
        layer = layer_handles[layer_name]
        with builder.add_group(name=name, layer=layer) as group:
            for face in mesh_in.faces:
                pts = [tuple(mesh_in.vertices[v]) for v in face]
                group.add_face(pts, material=material_handles[name], layer=layer)

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
            "ps.set_program_name('Takeoff Auto 3D Preview'); "
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
        "Additional bitum EPP": "#2f4f4f",
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
        _center_window(self, parent)
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
            messagebox.showwarning("No selection", "Select at least one component to export.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            title="Export SketchUp model",
            defaultextension=".skp",
            filetypes=[("SketchUp files", "*.skp")],
            parent=self,
        )
        if not path:
            return
        try:
            export_skp(selected, path)
            messagebox.showinfo("Export complete", f"Saved SketchUp model:\n{path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)

    def _export_3d(self):
        selected = self._selected_components()
        if not selected:
            messagebox.showwarning("No selection", "Select at least one component to export.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            title="Export 3D model",
            defaultextension=".glb",
            filetypes=[("glTF binary", "*.glb"), ("Wavefront OBJ", "*.obj"), ("COLLADA", "*.dae")],
            parent=self,
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
            messagebox.showinfo("Export complete", f"Saved 3D model:\n{path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
