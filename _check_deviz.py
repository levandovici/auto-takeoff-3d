from openpyxl import load_workbook
from pathlib import Path

wb = load_workbook(r"***REMOVED***\source\auto-takeoff-3d\_test_deviz.xlsx", data_only=False)
lines = []
for sn in wb.sheetnames:
    ws = wb[sn]
    lines.append(f"\n--- {sn} ---")
    for r in range(7, 40):
        vals = [str(ws.cell(r, c).value) for c in range(1, 9)]
        if any(v != "None" for v in vals):
            lines.append(f"R{r}: {' | '.join(vals)}")

Path(r"***REMOVED***\source\auto-takeoff-3d\_check_out.txt").write_text("\n".join(lines), encoding="utf-8")
print("written _check_out.txt")
