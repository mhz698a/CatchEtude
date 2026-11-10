# NTFS MFT scanner

Reusable, Windows-only folder statistics based on the NTFS Master File Table.

## Public API

```python
from pathlib import Path
from ntfs_mft import scan_folder_mft

result = scan_folder_mft(Path(r"E:\\_Internal\\Characters\\Example"))
print(result.file_count)
print(result.total_size)  # Logical file bytes, like os.path.getsize()
print(result.complete)
```

For UI integration, pass `progress_callback(phase, processed, file_count, total_size)`
and `should_stop()`. The library raises typed exceptions from `ntfs_mft.errors`
for unsupported filesystems, unsupported volumes, missing elevation, API access
errors, malformed USN records, unsupported record versions, and cancellation.

## Implementation

1. `win32.py` isolates ctypes structures, volume handles, process-token elevation,
   `FSCTL_ENUM_USN_DATA`, and `OpenFileById`.
2. `scanner.py` validates the volume, enumerates USN V2 records, indexes the
   parent/child relationships in a temporary SQLite database, and traverses only
   the selected folder subtree.
3. File sizes come from `FILE_STANDARD_INFO.EndOfFile` opened by file ID. This is
   the logical size, not allocated disk space.
4. Reparse-point directories are not followed, matching the non-following behavior
   of the traditional recursive scan. `desktop.ini` and `thumbs.db` are excluded.
5. Temporary SQLite data is deleted after the scan. A file that cannot be opened
   by ID is counted as inaccessible; the result is partial and must not be cached.

## Preconditions and scope

- Windows with a local NTFS volume mounted directly to a drive letter.
- The MFT library itself must run in an elevated process. CatchEtude starts a
  short-lived helper with the Windows `runas` verb only after the user selects
  the MFT scan and accepts the UAC prompt; the main UI remains unelevated.
- The target must be a directory on the volume being enumerated.
- Non-NTFS filesystems, network shares, and mounted-volume directory paths are
  rejected rather than silently scanning the wrong volume.
- The current parser accepts USN_RECORD_V2. Unknown record versions are rejected
  instead of being interpreted with incorrect offsets.
- The scan is not a filesystem snapshot. Concurrent changes can make individual
  file IDs unavailable; those are reported as partial results.

The elevated helper communicates with the main app using temporary JSON request,
progress, cancellation and result files under a private per-scan temporary folder.
The MFT results are returned to the unelevated process, which updates the existing
character or Overworld cache using the application's established cache managers.

The traditional scan checks the matching cache entry first. It reuses the cached
file count and total size only while the folder's `mtime_ns` still matches the
stored value; otherwise it falls back to `os.walk`. A complete MFT scan refreshes
the same existing cache format. Partial MFT scans never overwrite cached totals.

The scanner uses the documented Windows MFT enumeration control code rather than
assuming that the on-disk `$MFT` stream is contiguous. It does not create, modify,
or enable the USN change journal.
