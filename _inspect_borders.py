from openpyxl import load_workbook
from pathlib import Path

p = Path(r"***REMOVED***\source\auto-takeoff-3d\data\cash\***REMOVED***\DEVIZ LOCAL DE CHELTUIELI LA EXECUTAREA LUCRARILOR DE TERMO-HIDROIZOLARE ACOPERISULUI PLAT ***REMOVED***")
wb = load_workbook(p, data_only=False)
for sn in wb.sheetnames[:1]:
    ws = wb[sn]
    lines = [f"--- {sn} borders ---"]
    for r in range(1, 42):
        row_borders = []
        for c in range(1, 9):
            cell = ws.cell(r, c)
            b = cell.border
            if b.left.style or b.right.style or b.top.style or b.bottom.style:
                styles = []
                if b.left.style: styles.append(f"L:{b.left.style}")
                if b.right.style: styles.append(f"R:{b.right.style}")
                if b.top.style: styles.append(f"T:{b.top.style}")
                if b.bottom.style: styles.append(f"B:{b.bottom.style}")
                row_borders.append(f"{cell.coordinate}({','.join(styles)})")
        if row_borders:
            lines.append(f"R{r}: " + " ".join(row_borders))
    Path(r"***REMOVED***\source\auto-takeoff-3d\_ref_borders.txt").write_text("\n".join(lines), encoding="utf-8")
print("written _ref_borders.txt")
