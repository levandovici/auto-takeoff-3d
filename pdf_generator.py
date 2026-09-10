"""PDF export helper for the client estimate.

The PDF is always produced from an existing Excel estimate, specifically from the
'CLIENT' sheet. It cannot be generated on its own; generate the Excel deviz
first, then call this module to print the client page(s) to PDF.
"""
from pathlib import Path
from typing import Optional

from calculator import RoofConfig, RoofQuantities
from roof_plan import RoofPlan


def _excel_sheet_to_pdf(excel_path: Path, pdf_path: Path, sheet_name: str = "CLIENT") -> Path:
    """Export a single Excel worksheet to PDF using Microsoft Excel COM automation."""
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError(
            "PDF export requires pywin32 and Microsoft Excel installed. "
            "Install pywin32 and try again."
        ) from exc

    excel = win32com.client.Dispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(str(excel_path.resolve()))
        try:
            ws = wb.Worksheets(sheet_name)

            # Page margins: left 2 cm, right/top/bottom/header/footer 0.5 cm
            CM_PER_INCH = 2.54
            ps = ws.PageSetup
            ps.LeftMargin = excel.InchesToPoints(2.0 / CM_PER_INCH)
            ps.RightMargin = excel.InchesToPoints(0.5 / CM_PER_INCH)
            ps.TopMargin = excel.InchesToPoints(0.5 / CM_PER_INCH)
            ps.BottomMargin = excel.InchesToPoints(0.5 / CM_PER_INCH)
            ps.HeaderMargin = excel.InchesToPoints(0.5 / CM_PER_INCH)
            ps.FooterMargin = excel.InchesToPoints(0.5 / CM_PER_INCH)
            ps.Orientation = 1  # xlPortrait
            ps.Zoom = False
            ps.FitToPagesWide = 1
            ps.FitToPagesTall = False
            ps.PrintArea = f"$A:$F"

            ws.ExportAsFixedFormat(
                Type=0,  # xlTypePDF
                Filename=str(pdf_path.resolve()),
                Quality=0,  # xlQualityStandard
                IncludeDocProperties=False,
                IgnorePrintAreas=False,
                OpenAfterPublish=False,
            )
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()
    return pdf_path


def generate_pdf_client(
    plan: RoofPlan,
    quantities: RoofQuantities,
    pdf_path: Path | str,
    *,
    excel_path: Optional[Path | str] = None,
    num_drains: int = 2,
    date_str: str = "2026-08-18",
    config: Optional[RoofConfig] = None,
) -> Path:
    """Generate a client PDF by printing the CLIENT sheet of an Excel estimate.

    The PDF is never built from scratch. ``excel_path`` must point to an existing
    .xlsx file created by ``deviz_generator.generate_deviz``. The resulting PDF
    contains the client page(s) from that workbook (typically 1-2 pages).

    ``plan``, ``quantities``, ``num_drains``, ``date_str`` and ``config`` are
    accepted only to keep the public API aligned with the rest of the generator;
    the actual PDF content comes from the Excel file.
    """
    del plan, quantities, num_drains, date_str, config  # values come from Excel

    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    if excel_path is None:
        raise ValueError(
            "PDF generation requires an Excel source. Generate the Excel estimate first."
        )

    excel_path = Path(excel_path)
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel source not found: {excel_path}")

    return _excel_sheet_to_pdf(excel_path, pdf_path, sheet_name="CLIENT")
