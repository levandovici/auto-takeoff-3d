import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from excel_engine import PriceCatalog


@dataclass
class ClientFolder:
    path: Path
    name: str
    date: Optional[datetime]
    area_hint: Optional[int]
    location: str
    estimate_xlsx: Optional[Path]
    active_skp: Optional[Path]
    photos: List[Path] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "date": self.date.isoformat() if self.date else None,
            "area_hint_m2": self.area_hint,
            "location": self.location,
            "estimate_xlsx": str(self.estimate_xlsx) if self.estimate_xlsx else None,
            "active_skp": str(self.active_skp) if self.active_skp else None,
            "photos": [str(p) for p in self.photos],
        }


def _parse_folder_name(name: str) -> Dict[str, Any]:
    date = None
    area = None
    location = ""

    date_match = re.search(r"(\d{2})\.(\d{2})\.(\d{2,4})", name)
    if date_match:
        d, m, y = date_match.groups()
        y = "20" + y if len(y) == 2 else y
        try:
            date = datetime(int(y), int(m), int(d))
        except ValueError:
            date = None

    area_match = re.search(r"(\d+)\s*m2", name, re.IGNORECASE)
    if area_match:
        area = int(area_match.group(1))

    if " - " in name:
        parts = name.split(" - ", 2)
        if len(parts) > 2:
            location = parts[-1].strip()
        elif area_match:
            location = name.split(" - ", 1)[-1].strip()

    return {"date": date, "area_hint": area, "location": location}


def _find_subfolder(parent: Path, *candidates: str) -> Optional[Path]:
    if not parent.is_dir():
        return None
    for child in parent.iterdir():
        if not child.is_dir():
            continue
        for candidate in candidates:
            if candidate.lower() in child.name.lower():
                return child
    return None


def _is_excluded_skp(name: str) -> bool:
    lowered = name.lower()
    return any(tag in lowered for tag in ["old", "wrong", "backup", ".skb"])


def _pick_active_skp(search_dir: Path) -> Optional[Path]:
    if not search_dir or not search_dir.is_dir():
        return None
    skp_files = [p for p in search_dir.rglob("*.skp") if p.is_file()]
    candidates = [p for p in skp_files if not _is_excluded_skp(p.name)]
    if not candidates:
        return skp_files[0] if skp_files else None
    for p in candidates:
        if "без названия" in p.name.lower() and "2" not in p.name.lower():
            return p
    return candidates[0]


def _find_estimate_xlsx(search_dir: Path) -> Optional[Path]:
    if not search_dir or not search_dir.is_dir():
        return None
    xlsx_files = sorted(p for p in search_dir.rglob("*.xlsx") if p.is_file())
    for p in xlsx_files:
        if "deviz" in p.name.lower():
            return p
    return xlsx_files[0] if xlsx_files else None


def _collect_photos(photos_dir: Path) -> List[Path]:
    if not photos_dir or not photos_dir.is_dir():
        return []
    return [p for p in photos_dir.iterdir() if p.is_file()]


def discover_client_folders(cash_root: Path | str) -> List[ClientFolder]:
    root = Path(cash_root)
    folders: List[ClientFolder] = []
    if not root.is_dir():
        return folders
    for child in root.iterdir():
        if not child.is_dir():
            continue
        parsed = _parse_folder_name(child.name)
        smeta = _find_subfolder(child, "Локальная смета") or child
        drawing = _find_subfolder(child, "Чертеж") or child
        photos = _find_subfolder(child, "Фотографии")
        folders.append(
            ClientFolder(
                path=child,
                name=child.name,
                date=parsed["date"],
                area_hint=parsed["area_hint"],
                location=parsed["location"],
                estimate_xlsx=_find_estimate_xlsx(smeta),
                active_skp=_pick_active_skp(drawing),
                photos=_collect_photos(photos) if photos else _collect_photos(child),
            )
        )
    return sorted(folders, key=lambda f: (f.date or datetime.min, f.name), reverse=True)


def extract_model_attributes(skp_path: Path | str) -> Dict[str, Any]:
    path = Path(skp_path)
    if not path.is_file():
        return {}
    info: Dict[str, Any] = {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "is_zip": False,
    }
    if zipfile.is_zipfile(path):
        info["is_zip"] = True
        try:
            with zipfile.ZipFile(path, "r") as zf:
                info["member_count"] = len(zf.namelist())
                info["members"] = zf.namelist()[:20]
        except Exception:
            pass
    return info


def load_price_catalog(path: Path | str) -> PriceCatalog:
    return PriceCatalog(path)
