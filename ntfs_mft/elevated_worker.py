"""Private command-line entry point executed only in the UAC-elevated child."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from pathlib import Path

from .errors import MFTScanCancelled
from .scanner import scan_folder_mft


def _atomic_write_json(path: Path, payload: dict) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def execute_request(request_path: Path) -> int:
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    folder_path = Path(request["folder_path"])
    progress_path = Path(request["progress_path"])
    result_path = Path(request["result_path"])
    cancel_path = Path(request["cancel_path"])
    progress_sequence = 0

    def report(phase, processed, file_count, total_size):
        nonlocal progress_sequence
        progress_sequence += 1
        _atomic_write_json(
            progress_path,
            {
                "sequence": progress_sequence,
                "phase": phase,
                "processed": processed,
                "file_count": file_count,
                "total_size": total_size,
            },
        )

    try:
        result = scan_folder_mft(
            folder_path,
            progress_callback=report,
            should_stop=cancel_path.exists,
        )
        _atomic_write_json(
            result_path,
            {
                "ok": True,
                "file_count": result.file_count,
                "total_size": result.total_size,
                "root_entry_count": result.root_entry_count,
                "inaccessible_count": result.inaccessible_count,
                "records_scanned": result.records_scanned,
            },
        )
        return 0
    except MFTScanCancelled as exc:
        _atomic_write_json(
            result_path, {"ok": False, "cancelled": True, "error": str(exc)}
        )
        return 2
    except Exception as exc:
        logging.exception("Elevated MFT helper failed for %s", folder_path)
        _atomic_write_json(
            result_path,
            {
                "ok": False,
                "cancelled": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            },
        )
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CatchEtude elevated MFT helper")
    parser.add_argument("--request", required=True)
    args = parser.parse_args(argv)
    return execute_request(Path(args.request))


if __name__ == "__main__":
    sys.exit(main())
