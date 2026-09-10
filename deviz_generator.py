import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.properties import PageSetupProperties

from calculator import RoofConfig, RoofQuantities
from excel_engine import PriceCatalog
from roof_plan import RoofPlan

TNR = "Times New Roman"

_PRICE_CATALOG: Optional[PriceCatalog] = None


def _get_price_catalog() -> Optional[PriceCatalog]:
    global _PRICE_CATALOG
    if _PRICE_CATALOG is None:
        price_path = Path(__file__).parent / "data" / "price.xlsx"
        if price_path.exists():
            _PRICE_CATALOG = PriceCatalog(price_path)
    return _PRICE_CATALOG

DEFAULT_MATERIALS_CONFIG_PATH = Path(__file__).parent / "materials_config.json"
_materials_config: Optional[Dict] = None


def load_materials_config(path: Path | str = DEFAULT_MATERIALS_CONFIG_PATH) -> Dict:
    """Load user-editable material prices/names from JSON."""
    global _materials_config
    p = Path(path)
    if _materials_config is None or p != DEFAULT_MATERIALS_CONFIG_PATH:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                _materials_config = json.load(f)
        else:
            _materials_config = {"prices": {}}
    return _materials_config


def save_materials_config(config: Dict, path: Path | str = DEFAULT_MATERIALS_CONFIG_PATH) -> Path:
    """Save the user-editable material config to JSON."""
    p = Path(path)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_cell(ws, row, col, value, bold=False, align=None, number_format=None, size=10, wrap=True):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = Font(name=TNR, size=size, bold=bold)
    h = align if align is not None else "general"
    cell.alignment = Alignment(horizontal=h, vertical="center", wrap_text=wrap)
    if number_format:
        cell.number_format = number_format
    return cell


def _header_rows(total_deviz_row: int):
    """Return the common header layout; the only formula that depends on the
    final row count is the small 'Valoarea de deviz' cell."""
    return [
        (1, 1, "Lucrari de hidroizolare acoperisului plat din or. Chișinău (invelitoare în ruloane)\n(denumirea obiectivului)"),
        (2, 1, "DEVIZ LOCAL №01\nLucrari de hidroizolare acoperisului plat din or. Chișinău (invelitoare în ruloane)"),
        (4, 3, "Valoarea de deviz"),
        (4, 5, f"=F{total_deviz_row}"),
        (6, 1, "Întocmit în prețuri curente:"),
        (7, 1, "Nr. crt."),
        (7, 2, "Lucrări și cheltuieli"),
        (7, 3, "U.M."),
        (7, 4, "Cantitate\nconform\ndatelor din\nproiect"),
        (7, 5, "Valoarea de deviz, lei"),
        (8, 5, "Pe unitate de\nmăsură\n__________\nincl. salariu"),
        (8, 6, "      Total _\nincl. salariu"),
        (9, 1, "1"),
        (9, 2, "2"),
        (9, 3, "3"),
        (9, 4, "4"),
        (9, 5, "5"),
        (9, 6, "6"),
        (10, 2, "Manopera"),
        (11, 2, "Capitolul 1. Acoperis"),
    ]


def _fill_header(ws, header_rows, date_value):
    _set_cell(ws, 5, 1, "")
    for row, col, val in header_rows:
        size = 14 if row == 1 else (12 if row == 2 else (11 if row in (7, 8, 9, 10, 11) else 10))
        bold = (row in (1, 2) and col == 1) or row in (7, 8, 9, 10, 11)
        align = "center" if row in (1, 2, 4, 7, 8, 9, 10, 11) else ("left" if row == 6 else None)
        _set_cell(ws, row, col, val, bold=bold, align=align, size=size)
    _set_cell(ws, 6, 3, date_value, align="left", size=10)


def _fill_service_rows(ws, rows):
    for r, (idx, name, unit, qty, price, total) in rows.items():
        _set_cell(ws, r, 1, idx, align="center", bold=True, size=10)
        _set_cell(ws, r, 2, name, bold=True, size=10)
        _set_cell(ws, r, 3, unit, align="center", bold=True, size=10)
        _set_cell(ws, r, 4, qty, align="right", number_format="0.00", bold=True, size=10)
        _set_cell(ws, r, 5, price, align="right", number_format="0.00", bold=True, size=10)
        _set_cell(ws, r, 6, total, align="right", number_format="0.00", bold=True, size=10)


def _fill_material_rows(ws, rows):
    for r, (idx, name, unit, qty, price, total, market) in rows.items():
        _set_cell(ws, r, 1, idx, align="center", bold=True, size=10)
        _set_cell(ws, r, 2, name, size=10)
        _set_cell(ws, r, 3, unit, align="center", bold=True, size=10)
        _set_cell(ws, r, 4, qty, align="right", number_format="0.00", bold=True, size=10)
        _set_cell(ws, r, 5, price, align="right", number_format="0.00", bold=True, size=10)
        _set_cell(ws, r, 6, total, align="right", number_format="0.00", bold=True, size=10)
        if market is not None:
            _set_cell(ws, r, 8, market, align="right", number_format="0.00", bold=True, size=10)


def _fill_totals(ws, totals, constants=None):
    for r, (name, formula) in totals.items():
        if name == "Total deviz":
            _set_cell(ws, r, 4, name, bold=True, size=12, align="center")
        else:
            _set_cell(ws, r, 2, name, bold=True, size=11)
        _set_cell(ws, r, 6, formula, bold=True, align="right", number_format="0.00", size=(12 if name == "Total deviz" else 11))
        if constants and r in constants:
            _set_cell(ws, r, 3, constants[r], align="right", number_format="0.00", bold=True, size=11)


def geotextil_breakdown(plan: RoofPlan, area: float) -> dict:
    vertical = sum(e.length * e.parapet_height for e in plan.edges if e.is_parapet)
    top = sum(e.length * e.parapet_top_width for e in plan.edges if e.is_parapet)
    side = sum(e.length * 0.05 for e in plan.edges if e.is_parapet)
    total = area + vertical + top + side
    return {
        "vertical": round(vertical, 2),
        "top": round(top, 2),
        "side": round(side, 2),
        "total": round(total, 2),
        "qty": float(math.ceil(total / 100.0) * 100.0),
    }


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------

def _bitum_material_name(material: str, layer: str) -> str:
    """Return a display name for a bitumen roll layer.
    material: Elast, Ultra, Flex
    layer: EPP or EKP
    """
    return f"Hydrobase {material} {layer}"


def _pvc_material_name(material: str) -> str:
    if material == "Protan":
        return "Membrana PVC SE 1.5 mm Light Grey PROTAN (44m2)"
    if material == "Flagon":
        return "Membrana PVC Flagon SR 1,2 mm (2,1m x 25m; 52,5m2)"
    return "Membrana PVC Fatrafol 1.5 mm (2,05*16m2)"


def _build_service_rows(quantities: RoofQuantities, num_drains: int, config: RoofConfig):
    """Return (rows_dict, last_service_row, row_map).

    row_map maps line type names to the actual Excel row numbers so material
    formulas can reference the right service quantities.
    """
    rows = {}
    row_map = {}
    r = 12

    rows[r] = (f"=ROW(A{r-11})", "Lucrari de curatire suprafelor", "m2", quantities.s_clear, 20, f"=D{r}*E{r}")
    row_map["cleaning"] = r
    r += 1

    if config.waterproofing_group == "bitum":
        rows[r] = (f"=ROW(A{r-11})", "Lucrari de grunduirea placii (cu praimer)", "m2", quantities.s_primer, 50, f"=D{r}*E{r}")
        row_map["primer"] = r
        r += 1
        if config.thermal_slab_enabled:
            rows[r] = (f"=ROW(A{r-11})", "Lucrari de învelirea membranei bituminoase", "m2", quantities.s_bitum_base_epp, 50, f"=D{r}*E{r}")
            row_map["base_membrane"] = r
            r += 1

    if config.thermal_slab_enabled:
        rows[r] = (
            f"=ROW(A{r-11})",
            f"Lucrari executarea izolarii termice ale placii (h=0,{int(config.thermal_slab_height_cm):02d})",
            "m2",
            quantities.s_thermal_slab_m2,
            60,
            f"=D{r}*E{r}",
        )
        row_map["thermal_slab"] = r
        r += 1

    if config.thermal_parapet_enabled:
        has_parapet = quantities.s_thermal_parapet_edge_m2 > 0
        has_wall = quantities.s_thermal_wall_m2 > 0
        if has_parapet:
            if has_wall:
                label = f"Lucrari executarea izolarii termice ale peretilor parapet (h=0,{int(config.thermal_parapet_width_cm):02d})"
            else:
                label = f"Lucrari executarea izolarii termice ale peretilor (h=0,{int(config.thermal_parapet_width_cm):02d})"
            rows[r] = (f"=ROW(A{r-11})", label, "m2", quantities.s_thermal_parapet_edge_m2, 70, f"=D{r}*E{r}")
            row_map["thermal_parapet"] = r
            r += 1
        if has_wall:
            if has_parapet:
                label = f"Lucrari executarea izolarii termice ale peretilor zid (h=0,{int(config.thermal_parapet_wall_width_cm):02d})"
            else:
                label = f"Lucrari executarea izolarii termice ale peretilor (h=0,{int(config.thermal_parapet_wall_width_cm):02d})"
            rows[r] = (f"=ROW(A{r-11})", label, "m2", quantities.s_thermal_wall_m2, 70, f"=D{r}*E{r}")
            row_map["thermal_wall"] = r
            r += 1

    if config.cementoplast_enabled:
        rows[r] = (f"=ROW(A{r-11})", "Lucrari de turnarea cimentoplastului", "m3", quantities.v_cementoplast_m3, 700, f"=D{r}*E{r}")
        row_map["cementoplast"] = r
        r += 1

    if config.screed_enabled:
        rows[r] = (f"=ROW(A{r-11})", "Lucrari de turnarea sapei semiude", "m2", quantities.s_clear, 90, f"=D{r}*E{r}")
        row_map["screed"] = r
        r += 1

    if config.waterproofing_group == "bitum":
        if config.bitum_layers >= 2:
            rows[r] = (f"=ROW(A{r-11})", "Lucrari de învelirea membranei pe orizontală", "m2", quantities.s_top_epp, 100, f"=D{r}*E{r}")
            row_map["top_membrane_horiz"] = r
            r += 1
        rows[r] = (f"=ROW(A{r-11})", "Lucrari de învelirea membranei pe verticală", "m2", quantities.s_parapet_wrap, 120, f"=D{r}*E{r}")
        row_map["top_membrane_vert"] = r
        r += 1
    else:
        rows[r] = (f"=ROW(A{r-11})", "Lucrari de învelirea membranei polimerice", "m2", quantities.s_pvc_field, 150, f"=D{r}*E{r}")
        row_map["pvc_field"] = r
        r += 1
        rows[r] = (f"=ROW(A{r-11})", "Lucrari de învelirea membranei polimerice", "ml", quantities.s_pvc_parapet, 180, f"=D{r}*E{r}")
        row_map["pvc_parapet"] = r
        r += 1

    rows[r] = (f"=ROW(A{r-11})", "Lucrari de asamblare scurgerilor de evacuare", "buc.", num_drains, 450, f"=D{r}*E{r}")
    row_map["drains"] = r
    r += 1
    rows[r] = (f"=ROW(A{r-11})", "Lucrari de asamblare elementelor de aerisire", "buc.", f"=CEILING((D12/50),1)", 200, f"=D{r}*E{r}")
    row_map["vents"] = r
    r += 1
    rows[r] = (f"=ROW(A{r-11})", "Lucrari de asamblare sinei de fixare", "ml", quantities.l_rail_base, 25, f"=D{r}*E{r}")
    row_map["base_rail"] = r
    r += 1
    rows[r] = (f"=ROW(A{r-11})", "Lucrari de asamblare sinei marginale", "m.l.", quantities.l_rail_top, 25, f"=D{r}*E{r}")
    row_map["top_rail"] = r
    r += 1
    if quantities.l_drip_cap > 0:
        rows[r] = (f"=ROW(A{r-11})", "Lucrari de asamblare picurator", "ml", quantities.l_drip_cap, 70, f"=D{r}*E{r}")
        row_map["drip"] = r
        r += 1

    return rows, r - 1, row_map


def _build_material_rows(quantities: RoofQuantities, num_drains: int, config: RoofConfig,
                         last_service_row: int, row_map: dict):
    """Return a dict row->tuple for the 'Materiale' section.

    Materials start at last_service_row + 4 to leave room for:
      last_service_row + 1 : Total manopera fara TVA
      last_service_row + 2 : Materiale
      last_service_row + 3 : Capitolul 2. Învelitorii
    """
    rows = {}
    r = last_service_row + 4
    material_start = r

    # Service rows that material formulas reference
    cleaning_row = row_map["cleaning"]
    primer_row = row_map.get("primer", cleaning_row)
    base_membrane_row = row_map.get("base_membrane", primer_row)
    cementoplast_row = row_map.get("cementoplast", cleaning_row)
    screed_row = row_map.get("screed", cleaning_row)
    top_rail_row = row_map["top_rail"]
    base_rail_row = row_map["base_rail"]
    vents_row = row_map["vents"]

    def add(name, unit, qty, market_price):
        nonlocal r
        rows[r] = (f"=ROW(A{r-material_start+1})", name, unit, qty, f"=H{r}*1.1", f"=D{r}*E{r}", market_price)
        r += 1

    # --- Bitum specific materials ------------------------------------------------
    if config.waterproofing_group == "bitum":
        add("Praimer bituminos (Oreol 20L)", "cald.", f"=CEILING((D{primer_row}/60),1)", 800)
        add("GPL AUTO, L", "l.", f"=CEILING((D{base_membrane_row}*0.5),1)", 17)

        if config.thermal_slab_enabled:
            base_name = _bitum_material_name(config.bitum_material, "EPP")
            base_epp_formula = f"=CEILING((D{base_membrane_row}*1.1),15)"
            add(base_name, "m²", base_epp_formula, _market_price_for(base_name))

        # Thermal insulation boards
        CELL_BOARD_AREA = 0.6844  # 1.18m x 0.58m
        if config.thermal_slab_enabled:
            slab_row = row_map["thermal_slab"]
            para_row = row_map.get("thermal_parapet")
            wall_row = row_map.get("thermal_wall")

            # thickness_cm -> list of service-row references that need that board
            board_refs: Dict[float, List[int]] = {}
            for h_cm in _thermal_layer_heights(config):
                board_refs.setdefault(h_cm, []).append(slab_row)

            if config.thermal_parapet_enabled:
                if para_row is not None and quantities.s_thermal_parapet_edge_m2 > 0:
                    board_refs.setdefault(config.thermal_parapet_width_cm, []).append(para_row)
                if wall_row is not None and quantities.s_thermal_wall_m2 > 0:
                    board_refs.setdefault(config.thermal_parapet_wall_width_cm, []).append(wall_row)

            thermal_board_rows = []
            for h_cm, refs in sorted(board_refs.items()):
                name = _thermal_board_name(h_cm)
                parts = [f"CEILING((D{ref}/{CELL_BOARD_AREA}),1)" for ref in refs]
                formula = "=" + "+".join(parts)
                thermal_board_rows.append(r)
                add(name, "foi", formula, _market_price_for(name))

            foam_parts = [f"CEILING((D{row}/8),1)" for row in thermal_board_rows]
            foam_formula = "=" + "+".join(foam_parts)
            add("Spuma adeziva pentru polisterol Tehnonicol", "buc.", foam_formula, 120)

        # Mesh
        if config.mesh_enabled:
            add("Plasa sudata VR-1 100*100mm d3", "m²", quantities.s_mesh, 15)

        # Cementoplast materials
        if config.cementoplast_enabled:
            add("Granule maruntite (1m3)", "sac", f"=CEILING((D{cementoplast_row}*1),1)*2", 450)
            add("CEM II B-LL 32.5R/ПЦ 400-Д20 (saci) 1760kg", "sac", f"=CEILING((D{cementoplast_row}*220/40),40)", 108)
            add("Nisip fin spalat", "t", f"=CEILING((D{cementoplast_row}*0.07),1)", 570)

        # Top bitum layers (field + full parapet wrap)
        if config.bitum_layers >= 2:
            name = _bitum_material_name(config.bitum_material, "EPP")
            top_epp_formula = f"=CEILING(((D{row_map['top_membrane_horiz']}+D{row_map['top_membrane_vert']})*1.1),15)"
            add(name, "m²", top_epp_formula, _market_price_for(name))
        name = _bitum_material_name(config.bitum_material, "EKP")
        if config.bitum_layers >= 2:
            top_ekp_formula = f"=CEILING(((D{row_map['top_membrane_horiz']}+D{row_map['top_membrane_vert']})*1.1),10)"
        else:
            top_ekp_formula = f"=CEILING(((D{cleaning_row}+D{row_map['top_membrane_vert']})*1.1),10)"
        add(name, "m²", top_ekp_formula, _market_price_for(name))

    # --- PVC specific materials --------------------------------------------------
    else:
        if config.pvc_geotextil_layers > 0:
            add("Geotextil Termo 300 gr/m²", "m²", quantities.s_geotextil, 18)

        # PVC membrane
        name = _pvc_material_name(config.pvc_material)
        add(name, "m²", quantities.s_pvc_field + quantities.s_pvc_parapet, _market_price_for(name))

        # Thermal insulation boards (PVC roofs can also be insulated)
        if config.thermal_slab_enabled:
            layer_heights = _thermal_layer_heights(config)
            for h_cm in layer_heights:
                board_name = _thermal_board_name(h_cm)
                add(board_name, "foi", f"=CEILING((D{cleaning_row}/0.6844),1)", _market_price_for(board_name))
            add("Spuma adeziva pentru polisterol Tehnonicol", "buc.", f"=CEILING((D{r-1}/8),1)", 120)

    # Common accessories
    add("Șina de fixare din aluminiu TechnoNICOL LITE 2,0 m", "ml", f"=CEILING(((D{base_rail_row})*1),2)+4", 30)
    add("Șina marginală din aluminiu TechnoNICOL LITE, 2,0 m", "ml", f"=CEILING(((D{top_rail_row})*1),2)+4", 33)

    if config.waterproofing_group == "bitum":
        add("Adeziv etansant PU 600ml negru Hyperseal Expert 150 (Bitum)", "buc.", f"=CEILING(((D{r-1})/12),1)", 157)
    else:
        add("Ermetic Tehnonicol PU Logicflex, 600ml white (PVC)", "buc.", f"=CEILING(((D{r-1})/8),1)", 120)

    add("Scurgere laterala PVC D110", "buc.", num_drains, 400)
    add("Aerator PVC", "buc.", f"=D{vents_row}", 190)

    return rows, r - 1


def _thermal_layer_heights(config: RoofConfig) -> List[float]:
    """Return the thickness of each thermal slab layer in cm."""
    total = config.thermal_slab_height_cm
    if config.thermal_slab_layers == 1:
        return [total]
    # Supported split for 2 layers
    if total == 10.0:
        return [5.0, 5.0]
    if total == 15.0:
        return [10.0, 5.0]
    if total == 20.0:
        return [10.0, 10.0]
    half = total / 2.0
    return [half, half]


def _thermal_board_name(thickness_cm: float) -> str:
    if abs(thickness_cm - 10.0) < 0.01:
        return "Technoplex Carbon ECO 1180x580x100-L"
    if abs(thickness_cm - 5.0) < 0.01:
        return "Technoplex Carbon ECO 1180x580x50-L"
    return f"Technoplex Carbon ECO 1180x580x{int(thickness_cm)}-L"


def _default_market_price(name: str) -> float:
    """Fallback catalog prices for well-known materials."""
    prices = {
        "Hydrobase Elast EPP": 122.7,
        "Hydrobase Elast EKP": 126.9,
        "Hydrobase Ultra EPP": 61.8,
        "Hydrobase Ultra EKP": 69.9,
        "Hydrobase Flex EPP": 82.6,
        "Hydrobase Flex EKP": 91.1,
        "Membrana PVC SE 1.5 mm Light Grey PROTAN (44m2)": 150.0,
        "Membrana PVC Flagon SR 1,2 mm (2,1m x 25m; 52,5m2)": 110.0,
        "Membrana PVC Fatrafol 1.5 mm (2,05*16m2)": 144.0,
        "Technoplex Carbon ECO 1180x580x100-L": 126.6,
        "Technoplex Carbon ECO 1180x580x50-L": 62.6,
        "Technoplex Carbon ECO 1180x580x30-L": 58.0,
    }
    return prices.get(name, 0.0)


def _market_price_for(name: str) -> float:
    """Return material price from JSON config, then price.xlsx catalog, then built-in defaults."""
    cfg = load_materials_config()
    if name in cfg.get("prices", {}):
        return cfg["prices"][name]
    catalog = _get_price_catalog()
    if catalog:
        item = catalog.lookup(name)
        if item:
            return item.unit_price
    return _default_market_price(name)


# ---------------------------------------------------------------------------
# Sheet assembly
# ---------------------------------------------------------------------------

def _build_sheet(ws, quantities: RoofQuantities, num_drains: int, config: RoofConfig,
                 is_client: bool, date_str: str):
    service_rows, last_service_row, row_map = _build_service_rows(quantities, num_drains, config)
    material_rows, last_material_row = _build_material_rows(quantities, num_drains, config, last_service_row, row_map)

    # Totals come after the material section
    totals_row_material = last_material_row + 1
    total_row = totals_row_material + 7
    totals = {
        last_service_row + 1: ("Total manopera fara TVA", f"=SUM(F12:F{last_service_row})"),
        totals_row_material: ("Total materiale cu TVA", f"=SUM(F{last_service_row + 4}:F{last_material_row})"),
        totals_row_material + 1: ("Total manopera și materiale", f"=F{totals_row_material}+F{last_service_row + 1}"),
        totals_row_material + 2: ("Cheltuieli de transport", f"=F{totals_row_material}*C{totals_row_material + 2}"),
        totals_row_material + 3: ("Cheltuieli de regie", f"=F{totals_row_material + 1}*C{totals_row_material + 3}"),
        totals_row_material + 4: ("Beneficiu de deviz", f"=F{totals_row_material + 1}*C{totals_row_material + 4}"),
        totals_row_material + 5: ("Total", f"=SUM(F{totals_row_material + 1}:F{totals_row_material + 4})"),
        total_row: ("Total deviz", f"=F{totals_row_material + 5}"),
    }

    header = _header_rows(total_row)
    _fill_header(ws, header, date_str)

    # Section labels between services and materials
    _set_cell(ws, last_service_row + 2, 2, "Materiale", bold=True, size=11, align="left")
    _set_cell(ws, last_service_row + 3, 2, "Capitolul 2. Învelitorii", bold=True, size=11, align="left")
    _set_cell(ws, last_service_row + 3, 8, "Market", bold=True, size=11, align="center")

    # Fill services
    for r, (idx, name, unit, qty, sem_price, total) in service_rows.items():
        price = f"=SEM!E{r}*1.2" if is_client else sem_price
        _set_cell(ws, r, 1, idx, align="center", bold=True, size=10)
        _set_cell(ws, r, 2, name, bold=True, size=10)
        _set_cell(ws, r, 3, unit, align="center", bold=True, size=10)
        _set_cell(ws, r, 4, qty, align="right", number_format="0.00", bold=True, size=10)
        _set_cell(ws, r, 5, price, align="right", number_format="0.00", bold=True, size=10)
        _set_cell(ws, r, 6, f"=D{r}*E{r}", align="right", number_format="0.00", bold=True, size=10)

    # Fill materials
    for r, (idx, name, unit, qty, sem_price, total, market) in material_rows.items():
        price = f"=SEM!E{r}*1.15" if is_client else sem_price
        market_cell = f"=SEM!H{r}" if is_client else market
        _set_cell(ws, r, 1, idx, align="center", bold=True, size=10)
        _set_cell(ws, r, 2, name, size=10)
        _set_cell(ws, r, 3, unit, align="center", bold=True, size=10)
        _set_cell(ws, r, 4, qty, align="right", number_format="0.00", bold=True, size=10)
        _set_cell(ws, r, 5, price, align="right", number_format="0.00", bold=True, size=10)
        _set_cell(ws, r, 6, f"=D{r}*E{r}", align="right", number_format="0.00", bold=True, size=10)
        if market_cell is not None:
            _set_cell(ws, r, 8, market_cell, align="right", number_format="0.00", bold=True, size=10)

    # Totals
    constants = {totals_row_material + 2: 0.05, totals_row_material + 3: 0.02, totals_row_material + 4: 0.04}
    _fill_totals(ws, totals, constants=constants if not is_client else None)

    return {
        "last_service_row": last_service_row,
        "last_material_row": last_material_row,
        "total_row": total_row,
    }


def _apply_styling(ws, last_material_row: int, total_row: int):
    thin = Side(style='thin', color="000000")
    medium = Side(style='medium', color="000000")
    thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    medium_border = Border(left=medium, right=medium, top=medium, bottom=medium)

    # main table A6:F up to the total row
    for row in ws.iter_rows(min_row=6, max_row=total_row, min_col=1, max_col=6):
        for cell in row:
            if cell.font.name != TNR:
                cell.font = Font(name=TNR, size=cell.font.size or 10, bold=cell.font.bold)
            cell.border = thin_border

    # market column around materials
    for row in range(last_material_row - 10, last_material_row + 1):
        cell = ws.cell(row=row, column=8)
        if cell.value is not None:
            if cell.font.name != TNR:
                cell.font = Font(name=TNR, size=cell.font.size or 10, bold=cell.font.bold)
            cell.border = medium_border if row == last_material_row - 10 else thin_border

    dims = {
        "col_widths": {"A": 4.44, "B": 40.66, "C": 6.44, "D": 12.11, "E": 16.66, "F": 12.33, "G": 11.44, "H": 12.33},
        "row_heights": {1: 82.2, 2: 67.2, 8: 55.2},
    }
    for col, w in dims["col_widths"].items():
        ws.column_dimensions[col].width = w
    for row, h in dims["row_heights"].items():
        ws.row_dimensions[row].height = h


def generate_deviz(plan: RoofPlan, quantities: RoofQuantities, output_path: Path | str,
                   num_drains: int = 2, date_str: str = "2026-08-18",
                   config: Optional[RoofConfig] = None) -> Path:
    config = config or RoofConfig()
    wb = Workbook()
    wb.remove(wb.active)

    sem = wb.create_sheet("SEM")
    client = wb.create_sheet("CLIENT")

    sem_info = _build_sheet(sem, quantities, num_drains, config, is_client=False, date_str=date_str)
    _build_sheet(client, quantities, num_drains, config, is_client=True, date_str=date_str)

    # Merges (common)
    merges = [
        "A1:B1", "A2:F2", "A5:F5", "C4:D4", "A6:B6", "C6:D6",
        "A7:A8", "B7:B8", "C7:C8", "D7:D8", "E7:F7",
        f"D{sem_info['total_row']}:E{sem_info['total_row']}",
    ]
    for ws in (sem, client):
        for r in merges:
            try:
                ws.merge_cells(r)
            except Exception:
                pass

    _apply_styling(sem, sem_info["last_material_row"], sem_info["total_row"])
    _apply_styling(client, sem_info["last_material_row"], sem_info["total_row"])

    # Page setup: left 2cm, right/top/bottom/header/footer 0.5cm, fit to 1 page wide
    _CM_IN = 1.0 / 2.54
    margins = PageMargins(
        left=2.0 * _CM_IN,
        right=0.5 * _CM_IN,
        top=0.5 * _CM_IN,
        bottom=0.5 * _CM_IN,
        header=0.5 * _CM_IN,
        footer=0.5 * _CM_IN,
    )
    for ws in (sem, client):
        ws.page_margins = margins
        ws.page_setup.orientation = "portrait"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        ws.print_area = f"A1:F{ws.max_row}"

    wb.save(output_path)
    return Path(output_path)
