import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional

from openpyxl import load_workbook

from calculator import RoofQuantities


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


@dataclass
class PriceItem:
    name: str
    unit: str
    unit_price: float
    section: str


@dataclass
class EstimateLine:
    keywords: List[str]
    quantity_fn: Callable[[RoofQuantities], Any]
    price_query: Optional[str] = None
    section: Optional[str] = None
    unit: Optional[str] = None


DEFAULT_LAYOUT = [
    # Manopera / services
    EstimateLine(
        ["curatire", "suprafelor"],
        lambda q: q.s_clear,
        price_query="Lucrari de curatire suprafelor",
        section="service",
        unit="m2",
    ),
    EstimateLine(
        ["grunduirea", "praimer"],
        lambda q: q.s_primer,
        price_query="Lucrari de grunduirea placii (cu praimer)",
        section="service",
        unit="m2",
    ),
    EstimateLine(
        ["izolarii", "termice", "placii"],
        lambda q: q.s_insulation_sqm,
        price_query="Lucrari executarea izolarii termice ale placii",
        section="service",
        unit="m2",
    ),
    EstimateLine(
        ["turnarea", "cimentoplastului"],
        lambda q: q.v_cementoplast_m3,
        price_query="Lucrari de turnarea cimentoplastului",
        section="service",
        unit="m3",
    ),
    EstimateLine(
        ["turnarea", "sapei"],
        lambda q: q.s_clear,
        price_query="Lucrari de turnarea sapei semiude",
        section="service",
        unit="m2",
    ),
    EstimateLine(
        ["asamblare", "sinei"],
        lambda q: q.l_rail_base + q.l_rail_top,
        price_query="Lucrari de asamblare sinei",
        section="service",
        unit="m.l.",
    ),
    # Materiale
    EstimateLine(
        ["praimer", "bituminos"],
        lambda q: math.ceil(q.s_primer / 60.0),
        price_query="Praimer bituminos",
        section="material",
        unit="cald.",
    ),
    EstimateLine(
        ["gpl", "auto"],
        lambda q: math.ceil(q.s_hydrobase_ultra * 0.5),
        price_query="GPL AUTO",
        section="material",
        unit="l.",
    ),
    EstimateLine(
        ["hydrobase", "ultra", "epp"],
        lambda q: q.s_hydrobase_ultra,
        price_query="Hydrobase ULTRA EPP",
        section="material",
        unit="m2",
    ),
    EstimateLine(
        ["hydrobase", "flex", "epp"],
        lambda q: q.s_hydrobase_flex_epp,
        price_query="Hydrobase Flex EPP",
        section="material",
        unit="m2",
    ),
    EstimateLine(
        ["hydrobase", "flex", "ekp"],
        lambda q: q.s_hydrobase_flex_ekp,
        price_query="Hydrobase Flex EKP",
        section="material",
        unit="m2",
    ),
    EstimateLine(
        ["technoplex", "100"],
        lambda q: math.ceil(q.s_clear / 0.6844),
        price_query="Technoplex Carbon ECO 1180x580x100",
        section="material",
        unit="buc",
    ),
    EstimateLine(
        ["technoplex", "50"],
        lambda q: math.ceil(q.s_clear / 0.6844),
        price_query="Technoplex Carbon ECO 1180x580x50",
        section="material",
        unit="buc",
    ),
    EstimateLine(
        ["reika", "aluminieva"],
        lambda q: q.l_rail_base + q.l_rail_top,
        price_query="Технониколь рейка краевая",
        section="material",
        unit="m.l.",
    ),
]


class PriceCatalog:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.items: List[PriceItem] = []
        self._load()

    def _add_item(self, name, unit, price, section):
        if not name or not isinstance(name, str):
            return
        if not isinstance(price, (int, float)):
            return
        if not unit or not isinstance(unit, str):
            unit = ""
        self.items.append(PriceItem(name.strip(), unit.strip(), float(price), section))

    def _load(self):
        wb = load_workbook(self.path, data_only=True)

        if "Materiale" in wb.sheetnames:
            ws = wb["Materiale"]
            for row in ws.iter_rows(values_only=True):
                if not row or len(row) < 4:
                    continue
                name = row[1]
                unit_price = row[2]
                unit = row[3]
                self._add_item(name, unit, unit_price, "material")

        if "Servicii" in wb.sheetnames:
            ws = wb["Servicii"]
            for row in ws.iter_rows(values_only=True):
                if not row or len(row) < 3:
                    continue
                name = row[0]
                unit_price = row[1]
                unit = row[2]
                self._add_item(name, unit, unit_price, "service")

        wb.close()

    def lookup(self, query: str, section: Optional[str] = None) -> Optional[PriceItem]:
        norm_query = _normalize(query)
        best: Optional[PriceItem] = None
        best_score = 0
        for item in self.items:
            if section and item.section != section:
                continue
            norm_name = _normalize(item.name)
            if not norm_name:
                continue
            if norm_query in norm_name or norm_name in norm_query:
                score = len(norm_query) + len(norm_name)
                if score > best_score:
                    best_score = score
                    best = item
        return best


class ExcelEstimateWriter:
    def __init__(self, template_path: Path | str, catalog: Optional[PriceCatalog] = None):
        self.template_path = Path(template_path)
        self.catalog = catalog
        self.wb = load_workbook(self.template_path, data_only=False)

    @staticmethod
    def _find_row(ws, keywords: List[str]) -> Optional[int]:
        norm_keywords = [_normalize(k) for k in keywords if k]
        for row in range(1, ws.max_row + 1):
            cell_value = ws.cell(row=row, column=2).value
            if not cell_value:
                continue
            norm_value = _normalize(str(cell_value))
            if all(k in norm_value for k in norm_keywords):
                return row
        return None

    @staticmethod
    def _is_formula(value: Any) -> bool:
        return isinstance(value, str) and value.startswith("=")

    def write(
        self,
        quantities: RoofQuantities,
        output_path: Path | str,
        sheet: Optional[str] = None,
        lines: Optional[List[EstimateLine]] = None,
        overwrite_formulas: bool = False,
    ) -> dict:
        ws = self.wb[sheet] if sheet else self.wb.active
        lines = lines or DEFAULT_LAYOUT
        matched = 0
        unmatched = []

        for line in lines:
            row = self._find_row(ws, line.keywords)
            if row is None:
                unmatched.append(line.keywords)
                continue
            matched += 1

            d_cell = ws.cell(row=row, column=4)
            d_cell.value = line.quantity_fn(quantities)

            if line.unit:
                c_cell = ws.cell(row=row, column=3)
                if not c_cell.value or not str(c_cell.value).strip():
                    c_cell.value = line.unit

            if self.catalog and line.price_query:
                e_cell = ws.cell(row=row, column=5)
                current = e_cell.value
                if overwrite_formulas or not self._is_formula(current):
                    item = self.catalog.lookup(line.price_query, section=line.section)
                    if item:
                        e_cell.value = item.unit_price
                        if not ws.cell(row=row, column=3).value:
                            ws.cell(row=row, column=3).value = item.unit

        self.wb.save(output_path)
        return {"matched": matched, "unmatched": unmatched, "output": str(output_path)}
