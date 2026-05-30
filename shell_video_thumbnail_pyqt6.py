from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Optional
from uuid import UUID

from ctypes import POINTER, byref, c_bool, c_int, c_long, c_void_p, sizeof
from ctypes import wintypes

from PyQt6.QtGui import QImage, QPixmap

HRESULT = c_long
HBITMAP = c_void_p
HDC = c_void_p

COINIT_APARTMENTTHREADED = 0x2

BI_RGB = 0
DIB_RGB_COLORS = 0

SIIGBF_BIGGERSIZEOK = 0x00000001
SIIGBF_MEMORYONLY = 0x00000002
SIIGBF_ICONONLY = 0x00000004
SIIGBF_THUMBNAILONLY = 0x00000008
SIIGBF_INCACHEONLY = 0x00000010
SIIGBF_CROPTOSQUARE = 0x00000020
SIIGBF_WIDETHUMBNAILS = 0x00000040
SIIGBF_ICONBACKGROUND = 0x00000080
SIIGBF_SCALEUP = 0x00000100

WINDOWS_SHELL_THUMBNAIL_EXTS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".avi",
    ".gif",
}

if sys.platform.startswith("win"):
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
else:
    shell32 = None
    ole32 = None
    gdi32 = None


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]

    @classmethod
    def from_uuid(cls, value: str) -> "GUID":
        u = UUID(value)
        data4 = (wintypes.BYTE * 8).from_buffer_copy(u.bytes[8:])
        return cls(u.time_low, u.time_mid, u.time_hi_version, data4)


class SIZE(ctypes.Structure):
    _fields_ = [
        ("cx", wintypes.LONG),
        ("cy", wintypes.LONG),
    ]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", c_void_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", wintypes.BYTE),
        ("rgbGreen", wintypes.BYTE),
        ("rgbRed", wintypes.BYTE),
        ("rgbReserved", wintypes.BYTE),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", RGBQUAD * 1),
    ]


IID_IShellItemImageFactory = GUID.from_uuid("bcc18b79-ba16-442f-80c4-8a59c30c463b")

QueryInterfaceType = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
AddRefType = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)
ReleaseType = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)
GetImageType = ctypes.WINFUNCTYPE(HRESULT, c_void_p, SIZE, wintypes.UINT, POINTER(HBITMAP))


class IShellItemImageFactoryVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", QueryInterfaceType),
        ("AddRef", AddRefType),
        ("Release", ReleaseType),
        ("GetImage", GetImageType),
    ]


class IShellItemImageFactory(ctypes.Structure):
    _fields_ = [("lpVtbl", POINTER(IShellItemImageFactoryVtbl))]


if sys.platform.startswith("win"):
    shell32.SHCreateItemFromParsingName.argtypes = [
        wintypes.LPCWSTR,
        c_void_p,
        POINTER(GUID),
        POINTER(c_void_p),
    ]
    shell32.SHCreateItemFromParsingName.restype = HRESULT

    ole32.CoInitializeEx.argtypes = [c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = HRESULT
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None

    gdi32.CreateCompatibleDC.argtypes = [HDC]
    gdi32.CreateCompatibleDC.restype = HDC
    gdi32.DeleteDC.argtypes = [HDC]
    gdi32.DeleteDC.restype = c_bool

    gdi32.GetObjectW.argtypes = [c_void_p, c_int, c_void_p]
    gdi32.GetObjectW.restype = c_int

    gdi32.GetDIBits.argtypes = [
        HDC,
        HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        c_void_p,
        POINTER(BITMAPINFO),
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = c_int

    gdi32.DeleteObject.argtypes = [c_void_p]
    gdi32.DeleteObject.restype = c_bool


def _hr_failed(hr: int) -> bool:
    return hr < 0


def _check_hresult(hr: int, context: str) -> None:
    if _hr_failed(hr):
        raise OSError(f"{context} failed (HRESULT=0x{hr & 0xFFFFFFFF:08X})")


class COMApartment:
    def __init__(self, coinit_flag: int = COINIT_APARTMENTTHREADED) -> None:
        self._coinit_flag = coinit_flag
        self._initialized = False

    def __enter__(self) -> "COMApartment":
        if not sys.platform.startswith("win"):
            return self
        hr = int(ole32.CoInitializeEx(None, self._coinit_flag))
        _check_hresult(hr, "CoInitializeEx")
        self._initialized = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._initialized:
            ole32.CoUninitialize()
            self._initialized = False


def should_use_shell_thumbnail(path_or_suffix: str | Path) -> bool:
    suffix = path_or_suffix.lower() if isinstance(path_or_suffix, str) else Path(path_or_suffix).suffix.lower()
    return sys.platform.startswith("win") and suffix in WINDOWS_SHELL_THUMBNAIL_EXTS


def _hbitmap_to_qimage(hbitmap: HBITMAP) -> QImage:
    if not hbitmap:
        raise ValueError("HBITMAP inválido")

    hdc = gdi32.CreateCompatibleDC(None)
    if not hdc:
        raise OSError("CreateCompatibleDC failed")

    try:
        bm = BITMAP()
        got = gdi32.GetObjectW(hbitmap, sizeof(BITMAP), byref(bm))
        if got == 0:
            raise OSError("GetObjectW failed")

        width = int(bm.bmWidth)
        height = abs(int(bm.bmHeight))
        if width <= 0 or height <= 0:
            raise ValueError("Dimensiones inválidas en HBITMAP")

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bmi.bmiHeader.biSizeImage = width * height * 4

        probe = gdi32.GetDIBits(hdc, hbitmap, 0, height, None, byref(bmi), DIB_RGB_COLORS)
        if probe == 0:
            raise OSError("GetDIBits (probe) failed")

        raw = ctypes.create_string_buffer(width * height * 4)
        scan = gdi32.GetDIBits(hdc, hbitmap, 0, height, raw, byref(bmi), DIB_RGB_COLORS)
        if scan == 0:
            raise OSError("GetDIBits (copy) failed")

        image = QImage(bytes(raw), width, height, width * 4, QImage.Format.Format_ARGB32).copy()
        if image.isNull():
            raise OSError("QImage creation failed")

        return image
    finally:
        gdi32.DeleteDC(hdc)


def _shell_item_image_factory_for_path(path: str):
    item_ptr = c_void_p()
    hr = int(
        shell32.SHCreateItemFromParsingName(
            path,
            None,
            byref(IID_IShellItemImageFactory),
            byref(item_ptr),
        )
    )
    _check_hresult(hr, "SHCreateItemFromParsingName")

    if not item_ptr:
        raise OSError("SHCreateItemFromParsingName returned null pointer")

    return ctypes.cast(item_ptr, POINTER(IShellItemImageFactory))


def get_shell_thumbnail_image(path: str, size: int = 256) -> Optional[QImage]:
    if not sys.platform.startswith("win"):
        return None

    path = str(Path(path))
    if not Path(path).exists():
        return None

    factory = None
    hbitmap = HBITMAP()

    try:
        with COMApartment():
            factory = _shell_item_image_factory_for_path(path)

            flags_candidates = (
                SIIGBF_THUMBNAILONLY | SIIGBF_SCALEUP,
                0,
            )

            for flags in flags_candidates:
                hbitmap = HBITMAP()
                hr = int(
                    factory.contents.lpVtbl.contents.GetImage(
                        factory,
                        SIZE(size, size),
                        flags,
                        byref(hbitmap),
                    )
                )
                if not _hr_failed(hr) and hbitmap:
                    return _hbitmap_to_qimage(hbitmap)

        return None
    finally:
        if hbitmap:
            gdi32.DeleteObject(hbitmap)
        if factory:
            factory.contents.lpVtbl.contents.Release(factory)


def get_shell_thumbnail_pixmap(path: str, size: int = 256) -> Optional[QPixmap]:
    image = get_shell_thumbnail_image(path, size)
    if image is None or image.isNull():
        return None
    return QPixmap.fromImage(image)