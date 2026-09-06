from openpyxl import load_workbook
from pathlib import Path

p = Path(r"***REMOVED***\source\auto-takeoff-3d\data\cash\***REMOVED***\DEVIZ LOCAL DE CHELTUIELI LA EXECUTAREA LUCRARILOR DE TERMO-HIDROIZOLARE ACOPERISULUI PLAT ***REMOVED***")
wb = load_workbook(p, data_only=False)
out = []
for sn in wb.sheetnames[:2]:
    ws = wb[sn]
    out.append(f"\n--- {sn} ---")
    out.append("Merged cells:")
    for r in ws.merged_cells.ranges:
        out.append(str(r))
    out.append("\nColumn widths:")
    for col, dim in ws.column_dimensions.items():
        if dim.width is not None:
            out.append(f"{col}: {dim.width}")
    out.append("\nRow heights:")
    for row, dim in ws.row_dimensions.items():
        if dim.height is not None:
            out.append(f"{row}: {dim.height}")
    out.append("\nSample cell sizes:")
    for r in [1, 2, 4, 7, 8, 9, 10, 11, 12, 21, 22, 23, 34, 35, 41]:
        for c in [1, 2, 3, 4, 5, 6, 7, 8]:
            cell = ws.cell(r, c)
            if cell.value is not None:
                out.append(f"{cell.coordinate}: value={cell.value!r}, font={cell.font.name} {cell.font.size}, align=h={cell.alignment.horizontal} v={cell.alignment.vertical} wrap={cell.alignment.wrap_text}, bold={cell.font.bold}")

Path(r"***REMOVED***\source\auto-takeoff-3d\_ref_dims.txt").write_text("\n".join(out), encoding="utf-8")
print("written _ref_dims.txt")
