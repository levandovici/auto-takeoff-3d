from openpyxl import load_workbook
from pathlib import Path
import io

p = Path(r"***REMOVED***\source\auto-takeoff-3d\data\cash\***REMOVED***\DEVIZ LOCAL DE CHELTUIELI LA EXECUTAREA LUCRARILOR DE TERMO-HIDROIZOLARE ACOPERISULUI PLAT ***REMOVED***")
wb = load_workbook(p, data_only=False)
out = []
out.append(f"Sheets: {wb.sheetnames}")
for sn in wb.sheetnames[:2]:
    ws = wb[sn]
    out.append(f"\n--- {sn} ---")
    for r in range(1, min(80, ws.max_row + 1)):
        row = []
        for c in range(1, min(16, ws.max_column + 1)):
            v = ws.cell(r, c).value
            if v is not None:
                row.append(f"[{c}] {v}")
        if row:
            out.append(f"R{r}: {' | '.join(row)}")

Path(r"***REMOVED***\source\auto-takeoff-3d\_inspect_out.txt").write_text("\n".join(out), encoding="utf-8")
print("written to _inspect_out.txt")
