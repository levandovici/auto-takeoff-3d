import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from roof_plan import RoofPlan


@dataclass
class RoofInput:
    length: float                    # L (m)
    width: float                     # W (m)
    parapet_height: float            # H_parapet (m)
    parapet_top_width: float         # W_parapet_top (m)
    num_drains: int = 2

    def __post_init__(self):
        for name, value in (
            ("length", self.length),
            ("width", self.width),
            ("parapet_height", self.parapet_height),
            ("parapet_top_width", self.parapet_top_width),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")
        if self.num_drains < 1:
            self.num_drains = 1


@dataclass
class RoofConfig:
    """Configuration for the material / layer assembly used by auto-generate."""
    # Waterproofing family
    waterproofing_group: str = "bitum"               # "bitum" or "pvc"

    # Bitum options
    bitum_material: str = "Ultra"                     # "Elast", "Ultra", "Flex"
    bitum_layers: int = 2                             # 1 or 2
    bitum_include_parapets: bool = True

    # PVC options
    pvc_material: str = "Flagon"                      # "Protan", "Flagon", "Fatrafol"
    pvc_geotextil_layers: int = 1                     # 0, 1 or 2
    pvc_include_parapets: bool = True

    # Thermal insulation of the floor slab
    thermal_slab_enabled: bool = True
    thermal_slab_layers: int = 2
    thermal_slab_height_cm: float = 15.0

    # Thermal insulation of the parapet
    thermal_parapet_enabled: bool = False
    thermal_parapet_width_cm: float = 5.0            # parapet edges
    thermal_parapet_wall_width_cm: float = 10.0      # wall edges

    # Base bitum EPP under thermal insulation (always bitum EPP)
    base_bitum_under_thermal: str = "EPP"             # fixed, but material grade comes from bitum_material
    thermal_slab_bitum_epp: bool = True                # extra bitum EPP layer on the floor slab
    thermal_slab_bitum_epp_material: str = "Ultra"       # Elast / Ultra / Flex for the extra slab layer

    # Mesh
    mesh_enabled: bool = True

    # Cementoplast
    cementoplast_enabled: bool = True
    base_slope_direction: str = "width"                # "width" or "length" (inclination span)
    base_slope_pct: float = 2.0                        # 2% - 5%
    # Counter-slope fields are kept for backward compatibility but are no longer used.
    counter_slope_extent: str = "center"             # deprecated
    counter_slope_pct: float = 2.0                     # deprecated

    # Screed
    screed_enabled: bool = True
    screed_thickness_cm: float = 5.0                   # 5, 6 or 7 cm

    # Common
    primer_vert_extension: float = 0.30                # m
    parapet_outer_drop: float = 0.05                   # m

    def __post_init__(self):
        self.waterproofing_group = self.waterproofing_group.lower()
        if self.waterproofing_group not in ("bitum", "pvc"):
            raise ValueError("waterproofing_group must be 'bitum' or 'pvc'")
        if self.bitum_material not in ("Elast", "Ultra", "Flex"):
            raise ValueError("bitum_material must be 'Elast', 'Ultra' or 'Flex'")
        if self.thermal_slab_bitum_epp_material not in ("Elast", "Ultra", "Flex"):
            raise ValueError("thermal_slab_bitum_epp_material must be 'Elast', 'Ultra' or 'Flex'")
        if self.bitum_layers not in (1, 2):
            raise ValueError("bitum_layers must be 1 or 2")
        if self.pvc_material not in ("Protan", "Flagon", "Fatrafol"):
            raise ValueError("pvc_material must be 'Protan', 'Flagon' or 'Fatrafol'")
        if self.pvc_geotextil_layers not in (0, 1, 2):
            raise ValueError("pvc_geotextil_layers must be 0, 1 or 2")
        if self.base_slope_direction not in ("width", "length"):
            raise ValueError("base_slope_direction must be 'width' or 'length'")
        if self.counter_slope_extent not in ("center", "half"):
            raise ValueError("counter_slope_extent must be 'center' or 'half'")


@dataclass
class RoofQuantities:
    s_clear: float
    p_perimeter: float
    parapet_length: float
    wall_length: float

    s_primer: float
    s_hydrobase_ultra: float
    l_rail_base: float
    v_insulation_m3: float
    s_insulation_sqm: float
    v_cementoplast_m3: float
    v_screed_m3: float
    s_hydrobase_flex_epp: float
    s_hydrobase_flex_ekp: float
    l_rail_top: float
    l_drip_cap: float = 0.0

    # Extended quantities for the configurable generator
    s_bitum_base_epp: float = 0.0            # base bitum EPP layer (under thermal insulation)
    s_top_epp: float = 0.0                   # top bitum EPP waterproofing (horizontal field only)
    s_top_ekp: float = 0.0                   # top bitum EKP waterproofing (horizontal field only)
    s_parapet_wrap: float = 0.0              # interior vertical + top + 5 cm outer side of parapet
    s_slab_epp: float = 0.0                  # extra bitum EPP layer on the floor slab
    s_geotextil: float = 0.0                 # geotextil for PVC assemblies
    s_pvc_field: float = 0.0                 # PVC membrane on horizontal field
    s_pvc_parapet: float = 0.0               # PVC membrane on parapets / verticals
    s_mesh: float = 0.0                      # Plasa sudata VR-1 (quantity in estimate units)

    v_thermal_slab_m3: float = 0.0
    s_thermal_slab_m2: float = 0.0
    v_thermal_parapet_m3: float = 0.0
    s_thermal_parapet_m2: float = 0.0
    s_thermal_parapet_edge_m2: float = 0.0  # parapet-type edges only
    s_thermal_wall_m2: float = 0.0           # wall-type edges only
    l_thermal_parapet_ml: float = 0.0

    edge_summary: List[Tuple[str, float, float, float]] = field(default_factory=list)


class RoofCalculator:
    DEFAULT_CONFIG = RoofConfig()
    MIN_CEMENT_THICKNESS = 0.03  # 3 cm minimum under slope
    PRIMER_VERT_EXTENSION = 0.30  # 30 cm primer up-stand
    ULTRA_VERT_EXTENSION = 0.15   # 15 cm = total foam height (margin rule)
    PARAPET_OUTER_DROP = 0.05     # 5 cm Flex drop over parapet
    MESH_UNIT_COEFFICIENT = 2.4   # 2 because mesh piece is 2x1m + 1.2 waste/overlap

    # Predefined thermal slab assemblies (layers x total_height_cm)
    THERMAL_ASSEMBLIES = {
        (1, 10.0): [(10.0,)],
        (2, 10.0): [(5.0, 5.0)],
        (2, 15.0): [(10.0, 5.0)],
        (2, 20.0): [(10.0, 10.0)],
    }

    @classmethod
    def _thermal_slab_layers(cls, layers: int, total_height_cm: float) -> List[float]:
        key = (layers, round(total_height_cm, 1))
        if key in cls.THERMAL_ASSEMBLIES:
            return list(cls.THERMAL_ASSEMBLIES[key][0])
        # Fallback: split evenly
        if layers == 1:
            return [total_height_cm]
        half = total_height_cm / 2.0
        return [half, half]

    @classmethod
    def _base_slope_height(cls, dimension: float, slope_pct: float) -> float:
        """Round slope height up to the nearest cm; minimum 5 cm."""
        h = dimension / 2.0 * (slope_pct / 100.0)
        return max(0.05, math.ceil(h * 100.0) / 100.0)

    @classmethod
    def _calculate_with_geometry(
        cls,
        length: float,
        width: float,
        S_clear: float,
        P_total: float,
        P_parapet: float,
        P_wall: float,
        edge_summary: List[Tuple[str, float, float, float]],
        ventilation_duct_area: float,
        ventilation_duct_perimeter: float,
        num_drains: int,
        config: RoofConfig,
    ) -> RoofQuantities:
        # Parapet / wall wrap area for bitum / PVC membranes
        if config.waterproofing_group == "bitum":
            include_parapets = config.bitum_include_parapets
        else:
            include_parapets = config.pvc_include_parapets

        if include_parapets:
            wrap_total = sum(
                length * (height + top_width + cls.PARAPET_OUTER_DROP)
                for edge_type, length, height, top_width in edge_summary
                if edge_type == "parapet"
            )
        else:
            # only 15 cm vertical up-stand
            wrap_total = P_parapet * 0.15
        wrap_total += ventilation_duct_area

        S_primer = S_clear + (P_total * config.primer_vert_extension)
        S_ultra = S_clear + (P_total * cls.ULTRA_VERT_EXTENSION)

        # Bitum top layer(s) — horizontal field separate from full parapet wrap
        S_top_epp = 0.0
        S_top_ekp = 0.0
        S_parapet_wrap = 0.0
        if config.waterproofing_group == "bitum":
            S_parapet_wrap = wrap_total
            if config.bitum_layers == 1:
                S_top_ekp = S_clear
            else:
                S_top_epp = S_clear
                S_top_ekp = S_clear

        # PVC membrane
        S_pvc_field = 0.0
        S_pvc_parapet = 0.0
        S_geotextil = 0.0
        if config.waterproofing_group == "pvc":
            S_pvc_field = S_clear
            S_pvc_parapet = wrap_total
            if config.pvc_geotextil_layers > 0:
                S_geotextil = (S_clear + wrap_total) * config.pvc_geotextil_layers

        # Thermal insulation of the floor slab
        v_thermal_slab = 0.0
        s_thermal_slab = 0.0
        if config.thermal_slab_enabled:
            total_h = config.thermal_slab_height_cm / 100.0
            v_thermal_slab = S_clear * total_h
            s_thermal_slab = S_clear  # work area is the slab area, layers handled in materials
            layer_heights = cls._thermal_slab_layers(config.thermal_slab_layers, config.thermal_slab_height_cm)
        else:
            layer_heights = []

        # Thermal insulation of the parapet (interior vertical surface, not the outer wrap)
        v_thermal_parapet = 0.0
        s_thermal_parapet = 0.0
        s_thermal_parapet_edge = 0.0
        s_thermal_wall = 0.0
        l_thermal_parapet = 0.0
        if config.thermal_parapet_enabled:
            for etype, length, height, top_width in edge_summary:
                vertical_area = length * height
                if etype == "wall":
                    width_m = config.thermal_parapet_wall_width_cm / 100.0
                    s_thermal_wall += vertical_area
                else:
                    width_m = config.thermal_parapet_width_cm / 100.0
                    s_thermal_parapet_edge += vertical_area
                l_thermal_parapet += length
                s_thermal_parapet += vertical_area
                v_thermal_parapet += vertical_area * width_m

        # Base bitum EPP layer under thermal insulation (only when thermal slab enabled and bitum selected)
        S_bitum_base_epp = 0.0
        S_slab_epp = 0.0
        if config.waterproofing_group == "bitum" and config.thermal_slab_enabled:
            # 30 cm strip around the perimeter; this layer is only for the floor slab
            S_bitum_base_epp = S_clear + (P_total * config.primer_vert_extension)
            if config.thermal_slab_bitum_epp:
                S_slab_epp = S_clear

        # Mesh (Plasa sudata VR-1)
        s_mesh = 0.0
        if config.mesh_enabled:
            s_mesh = math.ceil(S_clear * cls.MESH_UNIT_COEFFICIENT / 2.0) * 2.0

        # Cementoplast slope volume (single layer, ridge along center line)
        v_cementoplast = 0.0
        if config.cementoplast_enabled:
            # base_slope_direction indicates the inclination span:
            # "length" -> slope spans the length; center ridge runs along the width.
            # "width"  -> slope spans the width; center ridge runs along the length.
            span_dim = length if config.base_slope_direction == "length" else width
            h_base = cls._base_slope_height(span_dim, config.base_slope_pct)
            v_cementoplast = S_clear * h_base / 2.0

        # Screed
        v_screed = 0.0
        if config.screed_enabled:
            v_screed = S_clear * (config.screed_thickness_cm / 100.0)

        # Legacy insulation placeholder (used when thermal slab is disabled / old path)
        v_insulation = v_thermal_slab
        s_insulation = s_thermal_slab

        def _r(value: float) -> float:
            return round(value, 2)

        return RoofQuantities(
            s_clear=_r(S_clear),
            p_perimeter=_r(P_total),
            parapet_length=_r(P_parapet),
            wall_length=_r(P_wall),
            s_primer=_r(S_primer),
            s_hydrobase_ultra=_r(S_ultra),
            l_rail_base=_r(P_total + ventilation_duct_perimeter),
            v_insulation_m3=_r(v_insulation),
            s_insulation_sqm=_r(s_insulation),
            v_cementoplast_m3=_r(v_cementoplast),
            v_screed_m3=_r(v_screed),
            s_hydrobase_flex_epp=_r(S_top_epp),
            s_hydrobase_flex_ekp=_r(S_top_ekp),
            l_rail_top=_r(P_parapet),
            l_drip_cap=_r(P_wall),
            s_bitum_base_epp=_r(S_bitum_base_epp),
            s_top_epp=_r(S_top_epp),
            s_top_ekp=_r(S_top_ekp),
            s_parapet_wrap=_r(S_parapet_wrap),
            s_slab_epp=_r(S_slab_epp),
            s_geotextil=_r(S_geotextil),
            s_pvc_field=_r(S_pvc_field),
            s_pvc_parapet=_r(S_pvc_parapet),
            s_mesh=_r(s_mesh),
            v_thermal_slab_m3=_r(v_thermal_slab),
            s_thermal_slab_m2=_r(s_thermal_slab),
            v_thermal_parapet_m3=_r(v_thermal_parapet),
            s_thermal_parapet_m2=_r(s_thermal_parapet),
            s_thermal_parapet_edge_m2=_r(s_thermal_parapet_edge),
            s_thermal_wall_m2=_r(s_thermal_wall),
            l_thermal_parapet_ml=_r(l_thermal_parapet),
            edge_summary=edge_summary,
        )

    @classmethod
    def calculate(cls, data: RoofInput, config: Optional[RoofConfig] = None) -> RoofQuantities:
        config = config or cls.DEFAULT_CONFIG
        L, W = data.length, data.width
        S_clear = L * W
        P = 2 * (L + W)
        edge_summary = [("parapet", P, data.parapet_height, data.parapet_top_width)]
        return cls._calculate_with_geometry(
            length=L,
            width=W,
            S_clear=S_clear,
            P_total=P,
            P_parapet=P,
            P_wall=0.0,
            edge_summary=edge_summary,
            ventilation_duct_area=0.0,
            ventilation_duct_perimeter=0.0,
            num_drains=data.num_drains,
            config=config,
        )

    @classmethod
    def calculate_from_plan(cls, plan: "RoofPlan", config: Optional[RoofConfig] = None) -> RoofQuantities:
        import roof_plan
        config = config or cls.DEFAULT_CONFIG

        S_clear = plan.area
        P_total = plan.perimeter
        P_parapet = plan.parapet_length
        P_wall = plan.wall_length

        edge_summary = [
            (e.edge_type, e.length, e.parapet_height, e.parapet_top_width)
            for e in plan.edges
        ]

        minx, miny, maxx, maxy = plan.bounds
        length = maxx - minx
        width = maxy - miny
        return cls._calculate_with_geometry(
            length=length,
            width=width,
            S_clear=S_clear,
            P_total=P_total,
            P_parapet=P_parapet,
            P_wall=P_wall,
            edge_summary=edge_summary,
            ventilation_duct_area=plan.ventilation_duct_area,
            ventilation_duct_perimeter=plan.ventilation_duct_perimeter,
            num_drains=plan.num_drains,
            config=config,
        )
