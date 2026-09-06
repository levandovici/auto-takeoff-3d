import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import triangulate


@dataclass
class RoofEdge:
    p1: Tuple[float, float]
    p2: Tuple[float, float]
    edge_type: str = "parapet"  # "parapet" or "wall"
    parapet_height: float = 0.40
    parapet_top_width: float = 0.25

    def __post_init__(self):
        if self.edge_type not in ("parapet", "wall"):
            raise ValueError("edge_type must be 'parapet' or 'wall'")

    @property
    def length(self) -> float:
        return LineString([self.p1, self.p2]).length

    @property
    def is_wall(self) -> bool:
        return self.edge_type == "wall"

    @property
    def is_parapet(self) -> bool:
        return self.edge_type == "parapet"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "p1": list(self.p1),
            "p2": list(self.p2),
            "edge_type": self.edge_type,
            "parapet_height": self.parapet_height,
            "parapet_top_width": self.parapet_top_width,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RoofEdge":
        return cls(
            p1=tuple(d["p1"]),
            p2=tuple(d["p2"]),
            edge_type=d["edge_type"],
            parapet_height=d["parapet_height"],
            parapet_top_width=d["parapet_top_width"],
        )


@dataclass
class RoofPlan:
    points: List[Tuple[float, float]]
    edges: List[RoofEdge] = field(default_factory=list)
    num_drains: int = 2

    def __post_init__(self):
        if not self.edges:
            self._rebuild_edges()

    def _rebuild_edges(self):
        n = len(self.points)
        self.edges = []
        for i in range(n):
            p1 = self.points[i]
            p2 = self.points[(i + 1) % n]
            self.edges.append(RoofEdge(p1=p1, p2=p2))

    @property
    def polygon(self) -> Polygon:
        return Polygon(self.points)

    @property
    def is_valid(self) -> bool:
        return self.polygon.is_valid and len(self.points) >= 3

    @property
    def area(self) -> float:
        return self.polygon.area

    @property
    def perimeter(self) -> float:
        return self.polygon.length

    @property
    def parapet_length(self) -> float:
        return sum(e.length for e in self.edges if e.is_parapet)

    @property
    def wall_length(self) -> float:
        return sum(e.length for e in self.edges if e.is_wall)

    @property
    def drip_cap_length(self) -> float:
        return self.wall_length

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        return self.polygon.bounds

    @property
    def shortest_dimension(self) -> float:
        minx, miny, maxx, maxy = self.bounds
        return min(maxx - minx, maxy - miny)

    @property
    def centroid(self) -> Tuple[float, float]:
        c = self.polygon.centroid
        return (c.x, c.y)

    def dist_to_drain(self) -> float:
        if self.num_drains < 1:
            return 0.0
        return math.sqrt(self.area / self.num_drains) / 2.0

    def to_3d_faces(self) -> List[List[Tuple[float, float, float]]]:
        faces = []
        try:
            for tri in triangulate(self.polygon):
                tri_points = list(tri.exterior.coords)[:-1]
                top = [(x, y, 0.0) for (x, y) in tri_points]
                faces.append(top)
        except Exception:
            pass

        for edge in self.edges:
            if edge.is_wall:
                continue
            x1, y1 = edge.p1
            x2, y2 = edge.p2
            h = edge.parapet_height
            side = [
                (x1, y1, 0.0),
                (x2, y2, 0.0),
                (x2, y2, h),
                (x1, y1, h),
            ]
            faces.append(side)

        return faces

    def to_dict(self) -> Dict[str, Any]:
        return {
            "points": [list(p) for p in self.points],
            "edges": [e.to_dict() for e in self.edges],
            "num_drains": self.num_drains,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RoofPlan":
        plan = cls(
            points=[tuple(p) for p in d["points"]],
            num_drains=d.get("num_drains", 2),
        )
        if "edges" in d and d["edges"]:
            plan.edges = [RoofEdge.from_dict(e) for e in d["edges"]]
        else:
            plan._rebuild_edges()
        return plan

    @classmethod
    def rectangle(cls, length: float, width: float) -> "RoofPlan":
        points = [
            (0.0, 0.0),
            (length, 0.0),
            (length, width),
            (0.0, width),
        ]
        return cls(points=points)
