import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
class RoofQuantities:
    s_clear: float
    p_perimeter: float
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


class RoofCalculator:
    MIN_CEMENT_THICKNESS = 0.03  # 3 cm minimum under slope
    SCREED_THICKNESS = 0.05      # 5 cm concrete screed
    PRIMER_VERT_EXTENSION = 0.30  # 30 cm primer up-stand
    ULTRA_VERT_EXTENSION = 0.15   # 15 cm = total foam height (margin rule)
    PARAPET_OUTER_DROP = 0.05     # 5 cm Flex drop over parapet
    MAIN_SLOPE_PCT = 0.02
    COUNTER_SLOPE_PCT = 0.02

    @classmethod
    def calculate(cls, data: RoofInput) -> RoofQuantities:
        L, W = data.length, data.width
        S_clear = L * W
        P = 2 * (L + W)

        # 1. Primer & base hydro-insulation (margin rule: foam thickness not deducted)
        S_primer = S_clear + (P * cls.PRIMER_VERT_EXTENSION)
        S_ultra = S_clear + (P * cls.ULTRA_VERT_EXTENSION)

        # 2. Insulation: 10 cm + 5 cm = 15 cm total
        V_insulation = S_clear * (0.10 + 0.05)
        S_insulation = S_clear * 2

        # 3. Main slope (2% along the shorter dimension split)
        D_main = W / 2.0
        h_main_raw = D_main * cls.MAIN_SLOPE_PCT
        h_main = math.ceil(h_main_raw * 10.0) / 10.0
        if h_main < 0.10:
            h_main = 0.10
        V_main = S_clear * (cls.MIN_CEMENT_THICKNESS + h_main / 2.0)

        # 4. Counter-slope toward drains
        dist_to_drain = (L / max(1, data.num_drains)) / 2.0
        h_counter = dist_to_drain * cls.COUNTER_SLOPE_PCT
        V_counter = (S_clear * 0.15) * (h_counter / 3.0)
        V_cementoplast = V_main + V_counter

        # 5. Concrete screed
        V_screed = S_clear * cls.SCREED_THICKNESS

        # 6. Parapet wrap for Flex EPP & Flex EKP
        parapet_wrap = data.parapet_height + data.parapet_top_width + cls.PARAPET_OUTER_DROP
        S_flex_epp = S_clear + (P * parapet_wrap)
        S_flex_ekp = S_clear + (P * parapet_wrap)

        def _r(value: float) -> float:
            return round(value, 2)

        return RoofQuantities(
            s_clear=_r(S_clear),
            p_perimeter=_r(P),
            s_primer=_r(S_primer),
            s_hydrobase_ultra=_r(S_ultra),
            l_rail_base=_r(P),
            v_insulation_m3=_r(V_insulation),
            s_insulation_sqm=_r(S_insulation),
            v_cementoplast_m3=_r(V_cementoplast),
            v_screed_m3=_r(V_screed),
            s_hydrobase_flex_epp=_r(S_flex_epp),
            s_hydrobase_flex_ekp=_r(S_flex_ekp),
            l_rail_top=_r(P),
            l_drip_cap=0.0,
        )

    @classmethod
    def calculate_from_plan(cls, plan: "RoofPlan") -> RoofQuantities:
        import roof_plan

        S_clear = plan.area
        P_total = plan.perimeter
        P_parapet = plan.parapet_length
        P_wall = plan.wall_length

        # Use average parapet wrap over parapet edges
        if P_parapet > 0:
            wrap_total = sum(
                e.length * (e.parapet_height + e.parapet_top_width + cls.PARAPET_OUTER_DROP)
                for e in plan.edges
                if e.is_parapet
            )
            avg_wrap = wrap_total / P_parapet
        else:
            avg_wrap = 0.0

        S_primer = S_clear + (P_total * cls.PRIMER_VERT_EXTENSION)
        S_ultra = S_clear + (P_total * cls.ULTRA_VERT_EXTENSION)

        V_insulation = S_clear * (0.10 + 0.05)
        S_insulation = S_clear * 2

        D_main = plan.shortest_dimension / 2.0
        h_main_raw = D_main * cls.MAIN_SLOPE_PCT
        h_main = math.ceil(h_main_raw * 10.0) / 10.0
        if h_main < 0.10:
            h_main = 0.10
        V_main = S_clear * (cls.MIN_CEMENT_THICKNESS + h_main / 2.0)

        dist_to_drain = plan.dist_to_drain()
        h_counter = dist_to_drain * cls.COUNTER_SLOPE_PCT
        V_counter = (S_clear * 0.15) * (h_counter / 3.0)
        V_cementoplast = V_main + V_counter

        V_screed = S_clear * cls.SCREED_THICKNESS

        S_flex_epp = S_clear + (P_parapet * avg_wrap)
        S_flex_ekp = S_clear + (P_parapet * avg_wrap)

        def _r(value: float) -> float:
            return round(value, 2)

        return RoofQuantities(
            s_clear=_r(S_clear),
            p_perimeter=_r(P_total),
            s_primer=_r(S_primer),
            s_hydrobase_ultra=_r(S_ultra),
            l_rail_base=_r(P_total),
            v_insulation_m3=_r(V_insulation),
            s_insulation_sqm=_r(S_insulation),
            v_cementoplast_m3=_r(V_cementoplast),
            v_screed_m3=_r(V_screed),
            s_hydrobase_flex_epp=_r(S_flex_epp),
            s_hydrobase_flex_ekp=_r(S_flex_ekp),
            l_rail_top=_r(P_parapet),
            l_drip_cap=_r(P_wall),
        )
