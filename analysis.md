# Takeoff Auto 3D — Final Resume and Conclusion

This report aggregates the whole `data/cash`, `data/transfer`, and `data/transfer-cash` project archive.

Full per-project detail is in `_projects_resume.md` and `_projects_data.json`; computed statistics are in `_stats.txt`.

---

## 1. Excel Estimate Resume

Across all 41 projects, every one has at least one `DEVIZ LOCAL DE CHELTUIELI` Excel workbook. Each workbook contains multiple quote scenarios:

- **SEM / SEM-1 / SEM-2 / SEM-3** — company/internal cost sheets
- **CLIENT / CLIENT 1 / CLIENT 2** — client-facing quote sheets

The tool extracted the **cleaning area** (row `Lucrari de curățire suprafețelor`) and the **total deviz** from the `Total deviz` row for every sheet it could resolve.

Key numbers by root:

| Root | Projects | Total 1st SEM (lei) | 1st SEM avg (lei) | Avg roof area (m²) |
|------|----------|---------------------|-------------------|--------------------|
| cash | 28 | 4,449,000.91 | 158,892.89 | 104.1 |
| transfer | 8 | 6,991,001.90 | 873,875.24 | 810.0 |
| transfer-cash | 5 | 1,947,863.51 | 389,572.70 | 316.0 |

Notes on the Excel data:

- Some sheets have a **cleaning area = None** when they do not use the standard `Lucrari de curățire suprafețelor` row (e.g., `***REMOVED***` is a `sarpantă` / pitched roof, not a flat roof, and some small jobs use only `hidroizolare`).
- `***REMOVED***` has a very large computed `SEM` total (647,568.59) because the sheet likely aggregates additional structures; cleaning area = 403.08 m².
- Multiple variants per project (V2, SEM-2, SEM-3) reflect different material assemblies or discounts (e.g., Flex vs Ultra, different rail thicknesses, only-screed options).

---

## 2. SketchUp Model Resume

- 36 of 41 projects have an active `.skp` model.
- All inspected `.skp` files are **ZIP-based SketchUp archives** (2013+ format).
- Archive member counts range from **47 to 61** files, sizes between **~200 KB and ~700 KB**.
- **No 3D dimensions or geometry were extracted** because the `.skp` binary content is not human-readable without the SketchUp SDK or a dedicated parser (not available in this environment).
- Active model selection logic successfully excluded files containing `old`, `wrong`, `backup`, or `.skb`, and preferred the plain `Без названия.skp` over numbered/backup copies.

Projects missing an active `.skp` (10 total, mostly cash small jobs where only PDF or photos exist):

- 9 from `data/cash`
- 1 from `data/transfer-cash`

---

## 3. Excel ↔ Model Connection Conclusion

| Project attribute | Correlation |
|-------------------|-------------|
| File name area hint vs. Excel cleaning area | Strong — in most flat-roof projects the two are identical or within a few m² |
| `.skp` presence vs. estimate presence | Strong — 36/41 have both; missing `.skp` is usually a small/photo-only job |
| `.skp` size vs. roof area | Weak — file size reflects model complexity/edges, not area |
| `SEM` vs. `CLIENT` totals | See section 7 |

The main data gap is that **`.skp` geometry is not yet being read back into the calculation engine**. The current workflow therefore depends on manual `L`, `W`, `H_parapet`, `W_parapet_top`, and `N_drains` inputs (which is what `main.py` already supports).

---

## 4. Cash Projects Resume

- **28 projects**
- Area range: **24 – 250 m²**
- Average area: **104.1 m²**
- All 28 have an Excel estimate; 19 have a `.skp` model; 75 photos
- First `SEM` sum: **4,449,000.91 lei**
- First `CLIENT` sum (22 sheets): **2,882,234.30 lei**
- Average `CLIENT / SEM` ratio on matched pairs: **1.39** (client quote can be 0.87× to 9.32× the internal cost depending on the project and variant)

**Cash profile:** small to medium residential/flat roofs in Chișinău and surrounding districts, mostly with both company and client sheets.

---

## 5. Transfer Projects Resume

- **8 projects**
- Area range: **60 – 3,600 m²**
- Average area: **810.0 m²**
- All 8 have both Excel and `.skp`; 38 photos
- First `SEM` sum: **6,991,001.90 lei**
- First `CLIENT` sum (4 sheets): **2,472,523.74 lei**
- Average `CLIENT / SEM` ratio on matched pairs: **1.12**

**Transfer profile:** large commercial roofs, including the biggest roof at **3,600 m²** (`***REMOVED***`). Client quotes are only ~12% above company cost, reflecting volume discounting.

---

## 6. Transfer-Cash Projects Resume

- **5 projects**
- Area range: **100 – 1,000 m²**
- Average area: **316.0 m²**
- All 5 have Excel; 4 have `.skp`; only 1 photo
- First `SEM` sum: **1,947,863.51 lei**
- First `CLIENT` sum: **1,619,230.32 lei**
- Average `CLIENT / SEM` ratio: **0.83** (client can be as low as 0.31× or as high as 1.23×)

**Transfer-cash profile:** mixed commercial/residential; more price-sensitive client quotes, sometimes below the internal `SEM` total (likely a different/trimmed assembly).

---

## 7. Basic Algorithm for Flat-Roof Calculation with Price-Driven Materials

The algorithm implemented in `calculator.py` and `excel_engine.py` follows this logic:

1. **Input 3D / manual parameters**
   - `L` — base length
   - `W` — base width
   - `H_parapet`
   - `W_parapet_top`
   - `N_drains`
   - Optionally load from `.skp` in the future

2. **Geometry**
   - `S_clear = L × W`
   - `P = 2 × (L + W)`

3. **Layer quantities**
   - Primer: `S_primer = S_clear + P × 0.30`
   - Base hydro-insulation (Ultra EPP): `S_ultra = S_clear + P × 0.15` (margin — foam thickness not deducted)
   - Rail-1: `L_rail1 = P`
   - Insulation: `V_ins = S_clear × 0.15`, `S_ins = S_clear × 2`
   - Cementoplast slope:
     - `D_main = W / 2`
     - `h_main = ceil(D_main × 0.02 × 10) / 10` (min 0.10 m)
     - `V_main = S_clear × (0.03 + h_main / 2)`
     - `V_counter = (S_clear × 0.15) × (h_counter / 3)`
     - `V_cem = V_main + V_counter`
   - Screed: `V_screed = S_clear × 0.05`
   - Flex EPP/EKP wrap: `S_flex = S_clear + P × (H_parapet + W_parapet_top + 0.05)`
   - Rail-2: `L_rail2 = P`

4. **Price lookup**
   - Load `Materiale` and `Servicii` sheets from `data/price.xlsx`
   - Match each calculated quantity to a price item by normalized keyword (e.g. `Hydrobase Flex EKP`, `Lucrari de turnarea cimentoplastului`)

5. **Sheet target**
   - **SEM sheet** = internal cost: use raw catalog unit prices
   - **CLIENT sheet** = client quote: preserve existing markup formulas or apply a configured markup to unit prices

6. **Write without breaking formulas**
   - Open the template with `data_only=False`
   - Write quantity in column **D** and unit price in column **E**
   - Leave `F = D × E`, `SUM`, VAT/overhead, and `Total deviz` formulas untouched

7. **Material variants**
   - Choose the waterproofing family from the price catalog (`Hydrobase Ultra` vs `Hydrobase Flex` vs PVC membranes) and write the selected material line; unmatched lines are left as-is.

---

## 8. Final Resume and Conclusion

- **41 projects** in total across `cash` (28), `transfer` (8), and `transfer-cash` (5).
- **100% have an estimate Excel**; **88% have an active SketchUp model**.
- The dataset covers a very wide size range: **24 m² to 3,600 m²**, mostly flat thermo/hydro-isolation roofs.
- **Cash** is the high-volume, small-size pipeline (avg 104 m²).
- **Transfer** is the high-value commercial pipeline (avg 810 m²).
- **Transfer-cash** sits in the middle (avg 316 m²) and shows the most price-sensitive client quotes.
- The biggest single project is the **3,600 m² ***REMOVED*** roof** in `transfer`.
- `CLIENT` sheets are typically **company cost + markup**, except in `transfer-cash` where some client quotes are trimmed below `SEM`.
- `.skp` models are present but not yet parsed for geometry; the current code path uses manual dimensions and the `calculator.py` engine.
- The existing `main.py generate` command can now take any roof dimensions and a `DEVIZ` template and produce a populated estimate while preserving all Excel formulas.
