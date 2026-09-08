import argparse
import json
import sys
from pathlib import Path

from calculator import RoofCalculator, RoofInput, RoofQuantities
from excel_engine import ExcelEstimateWriter, PriceCatalog
from workspace_inspector import discover_client_folders
import modeler


def _quantities_to_dict(q: RoofQuantities) -> dict:
    return {
        "area_cleaning_m2": q.s_clear,
        "perimeter_m": q.p_perimeter,
        "primer_area_m2": q.s_primer,
        "hydrobase_ultra_m2": q.s_hydrobase_ultra,
        "base_rail_ml": q.l_rail_base,
        "insulation_m3": q.v_insulation_m3,
        "insulation_m2": q.s_insulation_sqm,
        "cementoplast_m3": q.v_cementoplast_m3,
        "screed_m3": q.v_screed_m3,
        "hydrobase_flex_epp_m2": q.s_hydrobase_flex_epp,
        "hydrobase_flex_ekp_m2": q.s_hydrobase_flex_ekp,
        "top_rail_ml": q.l_rail_top,
        "drip_cap_ml": q.l_drip_cap,
    }


def cmd_inspect(args: argparse.Namespace) -> int:
    root = Path(args.cash_root)
    folders = discover_client_folders(root)
    print(json.dumps([f.to_dict() for f in folders], ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    if args.length <= 0 or args.width <= 0 or args.parapet_height <= 0 or args.parapet_top_width <= 0:
        print("error: all dimensions must be positive", file=sys.stderr)
        return 1

    inp = RoofInput(
        length=args.length,
        width=args.width,
        parapet_height=args.parapet_height,
        parapet_top_width=args.parapet_top_width,
        num_drains=args.num_drains,
    )
    quantities = RoofCalculator.calculate(inp)

    catalog = None
    price_path = Path(args.price)
    if price_path.is_file():
        catalog = PriceCatalog(price_path)
    else:
        print(f"warning: price catalog not found at {price_path}", file=sys.stderr)

    template_path = Path(args.template)
    if not template_path.is_file():
        print(f"error: template not found at {template_path}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    writer = ExcelEstimateWriter(template_path, catalog=catalog)
    result = writer.write(
        quantities,
        output_path,
        sheet=args.sheet or None,
        overwrite_formulas=args.overwrite_prices,
    )

    summary = {
        "input": {
            "length": inp.length,
            "width": inp.width,
            "parapet_height": inp.parapet_height,
            "parapet_top_width": inp.parapet_top_width,
            "num_drains": inp.num_drains,
        },
        "quantities": _quantities_to_dict(quantities),
        "excel": result,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auto-takeoff-3d",
        description="Auto Takeoff 3D - flat roof quantity and estimate generator",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="List discovered client folders")
    inspect.add_argument("--cash-root", default="data/cash", help="Cash client root")
    inspect.set_defaults(func=cmd_inspect)

    gen = sub.add_parser("generate", help="Generate DEVIZ estimate from dimensions")
    gen.add_argument("--length", type=float, required=True, help="Base length L (m)")
    gen.add_argument("--width", type=float, required=True, help="Base width W (m)")
    gen.add_argument("--parapet-height", type=float, default=0.40, help="Parapet height (m)")
    gen.add_argument("--parapet-top-width", type=float, default=0.25, help="Parapet top width (m)")
    gen.add_argument("--num-drains", type=int, default=2, help="Number of drain outlets")
    gen.add_argument("--template", required=True, help="Path to DEVIZ .xlsx template")
    gen.add_argument("--output", required=True, help="Output .xlsx path")
    gen.add_argument("--price", default="data/price.xlsx", help="Master price catalog")
    gen.add_argument("--sheet", default=None, help="Target sheet name (default active)")
    gen.add_argument("--overwrite-prices", action="store_true", help="Overwrite price cells even if they are formulas")
    gen.set_defaults(func=cmd_generate)

    mdl = sub.add_parser("modeler", help="Launch the 3D/2D modeler GUI")
    mdl.set_defaults(func=lambda _: modeler.main())

    return parser


def main() -> int:
    # Double-click / file association passes a single .toff file argument
    if len(sys.argv) == 2 and sys.argv[1].lower().endswith(".toff"):
        modeler.main(sys.argv[1])
        return 0
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
