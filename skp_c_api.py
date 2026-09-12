"""Minimal ctypes bridge to the SketchUp C API for post-processing .skp files.

Used to set the model's UnitsOptions to metric (decimal millimeters) after
OpenSKP has written the geometry. OpenSKP itself only emits the legacy v17
format in inches and does not expose model options, so this post-process step
is required to make SketchUp open the file with millimeter units already
selected.

Requires SketchUp to be installed (the SketchUpAPI.dll is loaded from the
SketchUp installation directory).
"""

import ctypes
import os
import shutil
from pathlib import Path
from typing import Optional


class _SURef(ctypes.Structure):
    """Base for all SketchUp opaque reference types."""
    _fields_ = [("ptr", ctypes.c_void_p)]


class SUModelRef(_SURef):
    pass


class SUOptionsManagerRef(_SURef):
    pass


class SUOptionsProviderRef(_SURef):
    pass


class SUTypedValueRef(_SURef):
    pass


SU_INVALID = type("SU_INVALID", (), {"ptr": None})()

SU_RESULT_NONE = 0
SUModelVersion_SU2021 = 14


def _find_api_dll() -> Optional[Path]:
    """Locate SketchUpAPI.dll in a standard SketchUp installation."""
    env_path = os.environ.get("SKETCHUP_API_DLL")
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return candidate

    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "SketchUp" / "SketchUp 2024" / "SketchUpAPI.dll",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "SketchUp" / "SketchUp 2025" / "SketchUpAPI.dll",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "SketchUp" / "SketchUp 2023" / "SketchUpAPI.dll",
        Path(os.environ.get("ProgramW6432", r"C:\Program Files"))
        / "SketchUp" / "SketchUp 2024" / "SketchUpAPI.dll",
        Path(os.environ.get("ProgramW6432", r"C:\Program Files"))
        / "SketchUp" / "SketchUp 2025" / "SketchUpAPI.dll",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def is_sketchup_api_available() -> bool:
    """Return True if the SketchUp C API DLL can be found on this machine."""
    return _find_api_dll() is not None


class SketchUpAPIError(RuntimeError):
    """Raised when the SketchUp C API returns an error code."""


def _check(result: int, message: str) -> None:
    if result != SU_RESULT_NONE:
        raise SketchUpAPIError(f"{message} (error {result})")


class _SketchUpAPI:
    """Lazy-loaded ctypes wrapper around SketchUpAPI.dll."""

    _instance: Optional["_SketchUpAPI"] = None

    def __new__(cls) -> "_SketchUpAPI":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        dll_path = _find_api_dll()
        if dll_path is None:
            raise SketchUpAPIError(
                "SketchUpAPI.dll not found. Install SketchUp or set "
                "SKETCHUP_API_DLL to the full path to SketchUpAPI.dll."
            )

        # Load the DLL from its own directory so dependencies resolve.
        os.add_dll_directory(str(dll_path.parent))
        self.dll = ctypes.CDLL(str(dll_path))

        # --- Core lifecycle ---
        self.SUInitialize = self.dll.SUInitialize
        self.SUInitialize.argtypes = []
        self.SUInitialize.restype = None

        self.SUTerminate = self.dll.SUTerminate
        self.SUTerminate.argtypes = []
        self.SUTerminate.restype = None

        # --- Model load/save ---
        self.SUModelCreateFromFileWithStatus = self.dll.SUModelCreateFromFileWithStatus
        self.SUModelCreateFromFileWithStatus.argtypes = [
            ctypes.POINTER(SUModelRef),
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_int),
        ]
        self.SUModelCreateFromFileWithStatus.restype = ctypes.c_int

        self.SUModelSaveToFile = self.dll.SUModelSaveToFile
        self.SUModelSaveToFile.argtypes = [SUModelRef, ctypes.c_char_p]
        self.SUModelSaveToFile.restype = ctypes.c_int

        self.SUModelSaveToFileWithVersion = self.dll.SUModelSaveToFileWithVersion
        self.SUModelSaveToFileWithVersion.argtypes = [
            SUModelRef,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        self.SUModelSaveToFileWithVersion.restype = ctypes.c_int

        self.SUModelRelease = self.dll.SUModelRelease
        self.SUModelRelease.argtypes = [ctypes.POINTER(SUModelRef)]
        self.SUModelRelease.restype = ctypes.c_int

        # --- Options manager ---
        self.SUModelGetOptionsManager = self.dll.SUModelGetOptionsManager
        self.SUModelGetOptionsManager.argtypes = [
            SUModelRef,
            ctypes.POINTER(SUOptionsManagerRef),
        ]
        self.SUModelGetOptionsManager.restype = ctypes.c_int

        self.SUOptionsManagerGetOptionsProviderByName = (
            self.dll.SUOptionsManagerGetOptionsProviderByName
        )
        self.SUOptionsManagerGetOptionsProviderByName.argtypes = [
            SUOptionsManagerRef,
            ctypes.c_char_p,
            ctypes.POINTER(SUOptionsProviderRef),
        ]
        self.SUOptionsManagerGetOptionsProviderByName.restype = ctypes.c_int

        self.SUOptionsProviderSetValue = self.dll.SUOptionsProviderSetValue
        self.SUOptionsProviderSetValue.argtypes = [
            SUOptionsProviderRef,
            ctypes.c_char_p,
            SUTypedValueRef,
        ]
        self.SUOptionsProviderSetValue.restype = ctypes.c_int

        # --- Typed values ---
        self.SUTypedValueCreate = self.dll.SUTypedValueCreate
        self.SUTypedValueCreate.argtypes = [ctypes.POINTER(SUTypedValueRef)]
        self.SUTypedValueCreate.restype = ctypes.c_int

        self.SUTypedValueSetInt32 = self.dll.SUTypedValueSetInt32
        self.SUTypedValueSetInt32.argtypes = [SUTypedValueRef, ctypes.c_int32]
        self.SUTypedValueSetInt32.restype = ctypes.c_int

        self.SUTypedValueGetInt32 = self.dll.SUTypedValueGetInt32
        self.SUTypedValueGetInt32.argtypes = [
            SUTypedValueRef,
            ctypes.POINTER(ctypes.c_int32),
        ]
        self.SUTypedValueGetInt32.restype = ctypes.c_int

        self.SUOptionsProviderGetValue = self.dll.SUOptionsProviderGetValue
        self.SUOptionsProviderGetValue.argtypes = [
            SUOptionsProviderRef,
            ctypes.c_char_p,
            ctypes.POINTER(SUTypedValueRef),
        ]
        self.SUOptionsProviderGetValue.restype = ctypes.c_int

        self.SUTypedValueRelease = self.dll.SUTypedValueRelease
        self.SUTypedValueRelease.argtypes = [ctypes.POINTER(SUTypedValueRef)]
        self.SUTypedValueRelease.restype = ctypes.c_int


# Track whether the API has been initialized in this process.
_api_initialized = False


def _ensure_api() -> _SketchUpAPI:
    global _api_initialized
    api = _SketchUpAPI()
    if not _api_initialized:
        api.SUInitialize()
        _api_initialized = True
    return api


def _release_typed_value(api: _SketchUpAPI, value: SUTypedValueRef) -> None:
    if value.ptr is not None:
        api.SUTypedValueRelease(ctypes.byref(value))


def _set_option(
    api: _SketchUpAPI,
    provider: SUOptionsProviderRef,
    key: str,
    value: int,
) -> None:
    typed = SUTypedValueRef()
    typed.ptr = None
    try:
        _check(api.SUTypedValueCreate(ctypes.byref(typed)), "SUTypedValueCreate")
        _check(
            api.SUTypedValueSetInt32(typed, ctypes.c_int32(value)),
            f"SUTypedValueSetInt32({key})",
        )
        _check(
            api.SUOptionsProviderSetValue(provider, key.encode("utf-8"), typed),
            f"SUOptionsProviderSetValue({key})",
        )
    finally:
        _release_typed_value(api, typed)


def set_skp_metric_units(
    path: str,
    *,
    length_format: int = 0,  # Decimal
    length_unit: int = 2,    # Millimeters
    length_precision: int = 0,
    area_unit: int = 4,      # Square meters
    area_precision: int = 0,
    volume_unit: int = 4,    # Cubic meters
    volume_precision: int = 0,
) -> None:
    """Rewrite ``path`` so SketchUp opens it with metric units.

    The file is loaded, its UnitsOptions are updated (length in millimeters,
    area in square meters, volume in cubic meters), and it is saved back to
    the same path. SketchUp must be installed on this machine.
    """
    api = _ensure_api()

    model = SUModelRef()
    model.ptr = None
    status = ctypes.c_int(0)

    try:
        _check(
            api.SUModelCreateFromFileWithStatus(
                ctypes.byref(model),
                os.fsencode(path),
                ctypes.byref(status),
            ),
            f"Failed to load .skp file: {path}",
        )

        options_manager = SUOptionsManagerRef()
        _check(
            api.SUModelGetOptionsManager(model, ctypes.byref(options_manager)),
            "SUModelGetOptionsManager",
        )

        provider = SUOptionsProviderRef()
        _check(
            api.SUOptionsManagerGetOptionsProviderByName(
                options_manager,
                b"UnitsOptions",
                ctypes.byref(provider),
            ),
            "SUOptionsManagerGetOptionsProviderByName(UnitsOptions)",
        )

        _set_option(api, provider, "LengthFormat", length_format)
        _set_option(api, provider, "LengthUnit", length_unit)
        _set_option(api, provider, "LengthPrecision", length_precision)
        _set_option(api, provider, "AreaUnit", area_unit)
        _set_option(api, provider, "AreaPrecision", area_precision)
        _set_option(api, provider, "VolumeUnit", volume_unit)
        _set_option(api, provider, "VolumePrecision", volume_precision)

        # Save in-place using the current SDK format (SU2021+ versionless).
        _check(
            api.SUModelSaveToFile(model, os.fsencode(path)),
            f"Failed to save .skp file: {path}",
        )
    finally:
        if model.ptr is not None:
            api.SUModelRelease(ctypes.byref(model))


def _get_option_int32(
    api: _SketchUpAPI,
    provider: SUOptionsProviderRef,
    key: str,
) -> int:
    typed = SUTypedValueRef()
    typed.ptr = None
    try:
        _check(api.SUTypedValueCreate(ctypes.byref(typed)), "SUTypedValueCreate")
        _check(
            api.SUOptionsProviderGetValue(provider, key.encode("utf-8"), ctypes.byref(typed)),
            f"SUOptionsProviderGetValue({key})",
        )
        value = ctypes.c_int32(0)
        _check(
            api.SUTypedValueGetInt32(typed, ctypes.byref(value)),
            f"SUTypedValueGetInt32({key})",
        )
        return value.value
    finally:
        _release_typed_value(api, typed)


def get_skp_units(path: str) -> dict:
    """Read the UnitsOptions from ``path`` using the SketchUp C API."""
    api = _ensure_api()

    model = SUModelRef()
    model.ptr = None
    status = ctypes.c_int(0)

    try:
        _check(
            api.SUModelCreateFromFileWithStatus(
                ctypes.byref(model),
                os.fsencode(path),
                ctypes.byref(status),
            ),
            f"Failed to load .skp file: {path}",
        )

        options_manager = SUOptionsManagerRef()
        _check(
            api.SUModelGetOptionsManager(model, ctypes.byref(options_manager)),
            "SUModelGetOptionsManager",
        )

        provider = SUOptionsProviderRef()
        _check(
            api.SUOptionsManagerGetOptionsProviderByName(
                options_manager,
                b"UnitsOptions",
                ctypes.byref(provider),
            ),
            "SUOptionsManagerGetOptionsProviderByName(UnitsOptions)",
        )

        keys = [
            "LengthFormat",
            "LengthUnit",
            "LengthPrecision",
            "AreaUnit",
            "AreaPrecision",
            "VolumeUnit",
            "VolumePrecision",
        ]
        return {key: _get_option_int32(api, provider, key) for key in keys}
    finally:
        if model.ptr is not None:
            api.SUModelRelease(ctypes.byref(model))


def terminate_api() -> None:
    """Release the SketchUp C API. Safe to call multiple times."""
    global _api_initialized
    if _api_initialized:
        api = _SketchUpAPI()
        api.SUTerminate()
        _api_initialized = False
