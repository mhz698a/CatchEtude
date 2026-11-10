"""Reusable NTFS Master File Table scanning library for CatchEtude."""

from .errors import (
    ElevationCancelledError,
    ElevationLaunchError,
    ElevationRequiredError,
    MFTAccessError,
    MFTEnumerationError,
    MFTError,
    MFTRecordVersionError,
    MFTScanCancelled,
    UnsupportedFilesystemError,
    UnsupportedPlatformError,
    UnsupportedVolumeError,
)
from .scanner import (
    MFTEntry,
    MFTScanResult,
    MFTScanner,
    parse_usn_enum_buffer,
    scan_folder_mft,
)
from .win32 import VolumeInfo, WindowsVolumeApi, get_volume_info, is_process_elevated
from .elevation import ElevatedMFTRunner

__all__ = [
    "ElevationCancelledError",
    "ElevationLaunchError",
    "ElevationRequiredError",
    "ElevatedMFTRunner",
    "MFTAccessError",
    "MFTEntry",
    "MFTEnumerationError",
    "MFTError",
    "MFTRecordVersionError",
    "MFTScanCancelled",
    "MFTScanResult",
    "MFTScanner",
    "UnsupportedFilesystemError",
    "UnsupportedPlatformError",
    "UnsupportedVolumeError",
    "VolumeInfo",
    "WindowsVolumeApi",
    "get_volume_info",
    "is_process_elevated",
    "parse_usn_enum_buffer",
    "scan_folder_mft",
]
