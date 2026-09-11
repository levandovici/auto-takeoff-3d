from calculator import RoofCalculator, RoofConfig, RoofInput
from deviz_generator import generate_deviz
from roof_plan import RoofPlan
import tempfile, pathlib

for h in [15.0, 20.0, 25.0]:
    c = RoofConfig(thermal_slab_height_cm=h)
    q = RoofCalculator.calculate(RoofInput(20, 8, 0.4, 0.2), c)
    plan = RoofPlan(points=[(0, 0), (20, 0), (20, 8), (0, 8)])
    p = pathlib.Path(tempfile.gettempdir()) / f"epp_excel_{int(h)}.xlsx"
    generate_deviz(plan, q, p, num_drains=2, config=c)
    from openpyxl import load_workbook
    w = load_workbook(p, data_only=False)
    s = w['SEM']
    for r in range(1, s.max_row + 1):
        name = str(s.cell(r, 2).value)
        if 'grunduirea placii' in name or 'învelirea membranei bituminoase' in name:
            print(h, r, name, s.cell(r, 4).value)
