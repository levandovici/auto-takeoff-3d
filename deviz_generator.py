import math
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side

from calculator import RoofQuantities
from roof_plan import RoofPlan

TNR = "Times New Roman"

SEM_HEADER = [
    (1, 1, "Lucrari de hidroizolare acoperisului plat din or. Chișinău (invelitoare în ruloane)\n(denumirea obiectivului)"),
    (2, 1, "DEVIZ LOCAL №01\nLucrari de hidroizolare acoperisului plat din or. Chișinău (invelitoare în ruloane)"),
    (4, 3, "Valoarea de deviz"),
    (4, 5, "=F41"),
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
    (22, 2, "Materiale"),
    (23, 2, "Capitolul 2. Învelitorii"),
    (23, 8, "Market"),
]

SEM_MERGES = [
    "A1:B1", "A2:F2", "A5:F5", "C4:D4", "A6:B6", "C6:D6",
    "A7:A8", "B7:B8", "C7:C8", "D7:D8", "E7:F7",
    "D41:E41",
]

SEM_DIMENSIONS = {
    "col_widths": {"A": 4.44, "B": 40.66, "C": 6.44, "D": 12.11, "E": 16.66, "F": 12.33, "G": 11.44, "H": 12.33},
    "row_heights": {1: 82.2, 2: 67.2, 8: 55.2, 22: 16.2, 23: 16.2, 27: 26.4, 28: 26.4, 30: 16.95, 31: 15.0, 32: 15.0},
}

SEM_SERVICE_ROWS = {
    12: ("=ROW(A1)", "Lucrari de curatire suprafelor", "m2", "__AREA__", 20, "=D12*E12"),
    13: ("=ROW(A2)", "Lucrari de învelirea geotextilului", "m2", "=D12+__GEOTEXTIL_V__+__GEOTEXTIL_T__+__GEOTEXTIL_S__", 15, "=D13*E13"),
    14: ("=ROW(A3)", "Lucrari de învelirea membranei polimerice", "m2", "=D12", 100, "=D14*E14"),
    15: ("=ROW(A4)", "Lucrari de învelirea membranei polimerice", "ml", "__PERIM__", 100, "=D15*E15"),
    16: ("=ROW(A5)", "Lucrari de asamblare scurgerilor de evacuare", "buc.", "__DRAINS__", 450, "=D16*E16"),
    17: ("=ROW(A6)", "Lucrari de asamblare elementelor de aerisire", "buc.", "=CEILING((D12/50),1)", 200, "=D17*E17"),
    18: ("=ROW(A7)", "Lucrari de asamblare sinei de fixare", "ml", "__BASE_RAIL__", 25, "=D18*E18"),
    19: ("=ROW(A8)", "Lucrari de asamblare sinei", "ml", "__TOP_RAIL__", 25, "=D19*E19"),
    20: ("=ROW(A9)", "Lucrari de asamblare picurator", "ml", "__DRIP__", 200, "=D20*E20"),
}

SEM_MATERIAL_ROWS = {
    24: ("=ROW(A1)", "Geotextil Termo 300 gr/m²", "m²", "=CEILING((D13*1.15),100)", "=H24*1.7", "=D24*E24", 17),
    25: ("=ROW(A2)", "Membrana PVC Flagon SR 1,2mm (52,5m2)", "m²", "=CEILING(((D13)*1.2),52.5)", "=H25*1.1", "=D25*E25", 110),
    26: ("=ROW(A3)", "Membrana PVC Flagon S 1,5mm (21m2)", "m²", 2.1, "=H26*1.1", "=D26*E26", 218),
    27: ("=ROW(A4)", "Технониколь рейка прижимная алюминиевая LITE 2,0 м", "m.l.", "=CEILING(((D18)*1),2)+4", "=H27*1.2", "=D27*E27", 30),
    28: ("=ROW(A5)", "Технониколь рейка краевая алюминиевая LITE 2,0 м", "m.l.", "=CEILING(((D19)*1),2)+4", "=H28*1.2", "=D28*E28", 33),
    29: ("=ROW(A6)", "Ermetic Tehnonicol PU Logicflex, 600ml white", "buc.", "=CEILING(((D28)/8),1)", "=H29*1.1", "=D29*E29", 120),
    30: ("=ROW(A7)", "Aerator PVC", "buc.", "=D17", "=H30*2", "=D30*E30", 190),
    31: ("=ROW(A8)", "Scurgere laterala PVC D110", "buc.", "=D16", "=H31*1.5", "=D31*E31", 400),
    32: ("=ROW(A9)", "Tablă metalică (gri antracit)", "buc.", "=CEILING((D20/8),1)", "=H32*1.2", "=D32*E32", 260),
    33: ("=ROW(A10)", "Dibluri pentru termo-hidroizolare", "-", "-", "-", "=D13*50", None),
}

SEM_TOTALS = {
    21: ("Total manopera fara TVA", "=SUM(F12:F19)"),
    34: ("Total materiale cu TVA", "=SUM(F24:F33)"),
    35: ("Total manopera și materiale", "=F34+F21"),
    36: ("Cheltuieli de transport", "=F34*C36"),
    37: ("Cheltuieli de regie", "=F35*C37"),
    38: ("Beneficiu de deviz", "=F35*C38"),
    39: ("Total", "=SUM(F35:F38)"),
    41: ("Total deviz", "=F39"),
}

CLIENT_HEADER = [
    (1, 1, "Lucrari de hidroizolare acoperisului plat din or. Chișinău (invelitoare în ruloane)\n(denumirea obiectivului)"),
    (2, 1, "DEVIZ LOCAL №01\nLucrari de hidroizolare acoperisului plat din or. Chișinău (invelitoare în ruloane)"),
    (4, 3, "Valoarea de deviz"),
    (4, 5, "=F37"),
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
    (22, 2, "Materiale"),
    (23, 2, "Capitolul 2. Învelitorii"),
    (23, 8, "Market"),
]

CLIENT_MERGES = [
    "A1:B1", "A2:F2", "A5:F5", "C4:D4", "A6:B6", "C6:D6",
    "A7:A8", "B7:B8", "C7:C8", "D7:D8", "E7:F7",
    "D37:E37",
]

CLIENT_DIMENSIONS = {
    "col_widths": {"A": 4.44, "B": 40.66, "C": 6.44, "D": 12.11, "E": 16.66, "F": 12.33, "G": 11.44, "H": 12.33},
    "row_heights": {1: 82.2, 2: 67.2, 8: 55.2, 22: 16.2, 23: 16.2, 27: 26.4, 28: 26.4, 30: 16.95, 31: 15.0, 32: 15.0},
}

CLIENT_SERVICE_ROWS = {
    12: ("=ROW(A1)", "Lucrari de curatire suprafelor", "m2", "__AREA__", "=SEM!E12*1.2", "=D12*E12"),
    13: ("=ROW(A2)", "Lucrari de învelirea geotextilului", "m2", "=D12+__GEOTEXTIL_V__+__GEOTEXTIL_T__+__GEOTEXTIL_S__", "=SEM!E13*1.2", "=D13*E13"),
    14: ("=ROW(A3)", "Lucrari de învelirea membranei polimerice", "m2", "=D12", "=SEM!E14*1.2", "=D14*E14"),
    15: ("=ROW(A4)", "Lucrari de învelirea membranei polimerice", "ml", "__PERIM__", "=SEM!E15*1.2", "=D15*E15"),
    16: ("=ROW(A5)", "Lucrari de asamblare scurgerilor de evacuare", "buc.", "__DRAINS__", "=SEM!E16*1.2", "=D16*E16"),
    17: ("=ROW(A6)", "Lucrari de asamblare elementelor de aerisire", "buc.", "=CEILING((D12/50),1)", "=SEM!E17*1.2", "=D17*E17"),
    18: ("=ROW(A7)", "Lucrari de asamblare sinei de fixare", "ml", "__BASE_RAIL__", "=SEM!E18*1.2", "=D18*E18"),
    19: ("=ROW(A8)", "Lucrari de asamblare sinei", "ml", "__TOP_RAIL__", "=SEM!E19*1.2", "=D19*E19"),
    20: ("=ROW(A9)", "Lucrari de asamblare picurator", "ml", "__DRIP__", "=SEM!E20*1.2", "=D20*E20"),
}

CLIENT_MATERIAL_ROWS = {
    24: ("=ROW(A1)", "Geotextil Termo 300 gr/m²", "m²", "=CEILING((D13*1.15),100)", "=SEM!H24*1.7*1.02", "=D24*E24", "=SEM!H24"),
    25: ("=ROW(A2)", "Membrana PVC Flagon SR 1,2mm (52,5m2)", "m²", "=CEILING(((D13)*1.2),52.5)", "=SEM!H25*1.1*1.017603", "=D25*E25", "=SEM!H25"),
    26: ("=ROW(A3)", "Membrana PVC Flagon S 1,5mm (21m2)", "m²", 2.1, "=SEM!H26*1.1*1.025", "=D26*E26", "=SEM!H26"),
    27: ("=ROW(A4)", "Технониколь рейка прижимная алюминиевая LITE 2,0 м", "m.l.", "=CEILING(((D18)*1),2)+4", "=SEM!H27*1.2*1.025", "=D27*E27", "=SEM!H27"),
    28: ("=ROW(A5)", "Технониколь рейка краевая алюминиевая LITE 2,0 м", "m.l.", "=CEILING(((D19)*1),2)+4", "=SEM!H28*1.2*1.025", "=D28*E28", "=SEM!H28"),
    29: ("=ROW(A6)", "Ermetic Tehnonicol PU Logicflex, 600ml white", "buc.", "=CEILING(((D28)/8),1)", "=SEM!H29*1.1*1.00034", "=D29*E29", "=SEM!H29"),
    30: ("=ROW(A7)", "Aerator PVC", "buc.", "=D17", "=SEM!H30*2", "=D30*E30", "=SEM!H30"),
    31: ("=ROW(A8)", "Scurgere laterala PVC D110", "buc.", "=D16", "=SEM!H31*1.5", "=D31*E31", "=SEM!H31"),
    32: ("=ROW(A9)", "Tablă metalică (gri antracit)", "buc.", "=CEILING((D20/8),1)", "=SEM!H32*1.2", "=D32*E32", "=SEM!H32"),
    33: ("=ROW(A10)", "Dibluri pentru hidroizolare", "-", "-", "-", "=D13*50", "=SEM!F33"),
}

CLIENT_TOTALS = {
    21: ("Total manopera fara TVA", "=SUM(F12:F19)"),
    34: ("Total materiale cu TVA", "=SUM(F24:F33)"),
    35: ("Total manopera și materiale", "=F34+F21"),
    37: ("Total deviz", "=F35"),
}


def _set_cell(ws, row, col, value, bold=False, align=None, number_format=None, size=10, wrap=True):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = Font(name=TNR, size=size, bold=bold)
    h = align if align is not None else "general"
    cell.alignment = Alignment(horizontal=h, vertical="center", wrap_text=wrap)
    if number_format:
        cell.number_format = number_format
    return cell


def _fill_header(ws, header_rows, date_value):
    _set_cell(ws, 5, 1, "")
    for row, col, val in header_rows:
        size = 14 if row == 1 else (12 if row == 2 else (11 if row in (7, 8, 9, 10, 11, 22, 23) else 10))
        bold = (row in (1, 2) and col == 1) or row in (7, 8, 9, 10, 11, 22, 23)
        align = "center" if row in (1, 2, 4, 7, 8, 9, 10, 11, 22, 23) else ("left" if row == 6 else None)
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


def _replace_placeholders(rows, area, perimeter, drains, base_rail, top_rail, drip, geotextil_v, geotextil_t, geotextil_s):
    ph_values = {
        "__AREA__": area,
        "__PERIM__": perimeter,
        "__DRAINS__": drains,
        "__BASE_RAIL__": base_rail,
        "__TOP_RAIL__": top_rail,
        "__DRIP__": drip,
        "__GEOTEXTIL_V__": geotextil_v,
        "__GEOTEXTIL_T__": geotextil_t,
        "__GEOTEXTIL_S__": geotextil_s,
    }
    def repl(v):
        if v in ph_values:
            return ph_values[v]
        if isinstance(v, str):
            for ph, val in ph_values.items():
                v = v.replace(ph, str(val))
        return v
    return {k: tuple(repl(x) for x in vals) for k, vals in rows.items()}


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


def generate_deviz(plan: RoofPlan, quantities: RoofQuantities, output_path: Path | str, num_drains: int = 2, date_str: str = "2026-08-18") -> Path:
    wb = Workbook()
    wb.remove(wb.active)

    sem = wb.create_sheet("SEM")
    client = wb.create_sheet("CLIENT")

    area = round(quantities.s_clear, 2)
    perimeter = round(quantities.p_perimeter, 2)
    base_rail = round(quantities.l_rail_base, 2)
    top_rail = round(quantities.l_rail_top, 2)
    drip = round(quantities.l_drip_cap, 2)

    gt = geotextil_breakdown(plan, area)

    _fill_header(sem, SEM_HEADER, date_str)
    _fill_service_rows(sem, _replace_placeholders(SEM_SERVICE_ROWS, area, perimeter, num_drains, base_rail, top_rail, drip, gt["vertical"], gt["top"], gt["side"]))
    _fill_material_rows(sem, _replace_placeholders(SEM_MATERIAL_ROWS, area, perimeter, num_drains, base_rail, top_rail, drip, gt["vertical"], gt["top"], gt["side"]))
    _fill_totals(sem, SEM_TOTALS, constants={36: 0.05, 37: 0.02, 38: 0.04})

    _fill_header(client, CLIENT_HEADER, date_str)
    _fill_service_rows(client, _replace_placeholders(CLIENT_SERVICE_ROWS, area, perimeter, num_drains, base_rail, top_rail, drip, gt["vertical"], gt["top"], gt["side"]))
    _fill_material_rows(client, _replace_placeholders(CLIENT_MATERIAL_ROWS, area, perimeter, num_drains, base_rail, top_rail, drip, gt["vertical"], gt["top"], gt["side"]))
    _fill_totals(client, CLIENT_TOTALS)

    for r in SEM_MERGES:
        try:
            sem.merge_cells(r)
        except Exception:
            pass
    for r in CLIENT_MERGES:
        try:
            client.merge_cells(r)
        except Exception:
            pass

    thin = Side(style='thin', color="000000")
    medium = Side(style='medium', color="000000")
    thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    medium_border = Border(left=medium, right=medium, top=medium, bottom=medium)

    for ws in (sem, client):
        # main table A6:F39
        for row in ws.iter_rows(min_row=6, max_row=39, min_col=1, max_col=6):
            for cell in row:
                if cell.font.name != TNR:
                    cell.font = Font(name=TNR, size=cell.font.size or 10, bold=cell.font.bold)
                cell.border = thin_border
        # market column H23:H33, H23 medium
        for row in range(23, 34):
            cell = ws.cell(row=row, column=8)
            if cell.font.name != TNR:
                cell.font = Font(name=TNR, size=cell.font.size or 10, bold=cell.font.bold)
            cell.border = medium_border if row == 23 else thin_border

    for ws, dims in ((sem, SEM_DIMENSIONS), (client, CLIENT_DIMENSIONS)):
        for col, w in dims["col_widths"].items():
            ws.column_dimensions[col].width = w
        for row, h in dims["row_heights"].items():
            ws.row_dimensions[row].height = h

    wb.save(output_path)
    return Path(output_path)
