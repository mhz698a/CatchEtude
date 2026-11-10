"""Typed errors raised by the NTFS MFT access layer."""


class MFTError(RuntimeError):
    """Base error for MFT operations."""


class UnsupportedPlatformError(MFTError):
    """Raised when the native Windows MFT API is unavailable."""


class UnsupportedFilesystemError(MFTError):
    """Raised when the selected path is not on an NTFS volume."""

    def __init__(self, filesystem: str):
        self.filesystem = filesystem or "desconocido"
        super().__init__(
            f"El escaneo MFT requiere NTFS. Sistema de archivos detectado: {self.filesystem}."
        )


class UnsupportedVolumeError(MFTError):
    """Raised when a path cannot be mapped to a supported local volume."""


class ElevationRequiredError(MFTError):
    """Raised when the current process token is not elevated."""


class ElevationCancelledError(MFTError):
    """Raised when the user declines or cancels the Windows UAC prompt."""


class ElevationLaunchError(MFTError):
    """Raised when the elevated helper process cannot be started."""


class MFTAccessError(MFTError):
    """Raised when Windows denies access to the volume or its MFT."""


class MFTEnumerationError(MFTError):
    """Raised when the MFT enumeration returns invalid or incomplete data."""


class MFTRecordVersionError(MFTEnumerationError):
    """Raised when Windows returns a USN record version this parser cannot decode."""


class MFTScanCancelled(MFTError):
    """Raised when a running MFT scan is cancelled."""
