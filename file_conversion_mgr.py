"""
File conversion engine for CatchEtude's PDF Tools plugin.
Supports raster/SVG image conversions, audio-to-MP3 and Word-to-PDF.
"""

import copy
import logging
import subprocess
from pathlib import Path
from typing import Callable, Optional, List, Tuple

from PIL import Image, ImageOps
from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer


CancelCheck = Optional[Callable[[], bool]]
ProgressCallback = Optional[Callable[[int, int], None]]

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _unique_output_path(output_dir: Path, source_path: Path, extension: str) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate = output_dir / f"{source_path.stem}{extension}"
    counter = 1
    while candidate.exists():
        candidate = output_dir / f"{source_path.stem}_{counter:03d}{extension}"
        counter += 1
    return candidate


def _run_batch(
    paths: List[Path],
    output_dir: Path,
    converter: Callable[[Path, Path], Path],
    cancel_check: CancelCheck = None,
    progress_cb: ProgressCallback = None,
) -> Tuple[List[Path], List[str]]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: List[Path] = []
    warnings: List[str] = []
    total = len(paths)

    for index, raw_path in enumerate(paths):
        source = Path(raw_path)
        if cancel_check and cancel_check():
            raise InterruptedError("Operation cancelled")

        try:
            generated.append(converter(source, output_dir))
        except InterruptedError:
            raise
        except Exception as exc:
            logging.exception("Conversion failed for %s", source)
            warnings.append(f"{source.name}: {exc}")
        finally:
            if progress_cb:
                progress_cb(index + 1, total)

    return generated, warnings


def _load_raster_image(source: Path) -> Tuple[Image.Image, dict]:
    with Image.open(source) as opened:
        opened.seek(0)  # Animated images are converted from their first frame.
        image = ImageOps.exif_transpose(opened).copy()
        info = dict(opened.info)
    return image, info


def _write_ico(image: Image.Image, output_path: Path) -> Path:
    rgba = image.convert("RGBA")
    rgba.thumbnail((256, 256), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    offset = ((256 - rgba.width) // 2, (256 - rgba.height) // 2)
    canvas.alpha_composite(rgba, offset)
    canvas.save(output_path, format="ICO", sizes=ICO_SIZES)
    return output_path


def _convert_raster_to_ico(source: Path, output_dir: Path) -> Path:
    image, _ = _load_raster_image(source)
    try:
        output = _unique_output_path(output_dir, source, ".ico")
        return _write_ico(image, output)
    finally:
        image.close()


def _convert_raster_to_png(source: Path, output_dir: Path) -> Path:
    image, info = _load_raster_image(source)
    try:
        output = _unique_output_path(output_dir, source, ".png")
        if image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16"):
            image = image.convert("RGBA" if "transparency" in info else "RGB")
        save_options = {}
        if info.get("icc_profile"):
            save_options["icc_profile"] = info["icc_profile"]
        image.save(output, format="PNG", **save_options)
        return output
    finally:
        image.close()


def _convert_raster_to_jpg(source: Path, output_dir: Path) -> Path:
    image, info = _load_raster_image(source)
    try:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        try:
            background.paste(rgba, mask=rgba.getchannel("A"))
            output = _unique_output_path(output_dir, source, ".jpg")
            save_options = {"quality": 95, "optimize": True, "progressive": True}
            if info.get("icc_profile"):
                save_options["icc_profile"] = info["icc_profile"]
            exif = image.getexif()
            if exif:
                save_options["exif"] = exif.tobytes()
            background.save(output, format="JPEG", **save_options)
            return output
        finally:
            rgba.close()
            background.close()
    finally:
        image.close()


def _svg_to_image(source: Path, max_dimension: Optional[int] = None) -> QImage:
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise ValueError("El archivo SVG no es válido o no se pudo interpretar.")

    size = renderer.defaultSize()
    if size.width() <= 0 or size.height() <= 0:
        view_box = renderer.viewBoxF()
        size = QSize(round(view_box.width()), round(view_box.height()))

    width = max(1, size.width())
    height = max(1, size.height())
    if max_dimension:
        scale = min(max_dimension / max(width, height), 1.0)
        width = max(1, round(width * scale))
        height = max(1, round(height * scale))
    else:
        scale = min(4096 / max(width, height), 1.0)
        width = max(1, round(width * scale))
        height = max(1, round(height * scale))

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        renderer.render(painter, QRectF(0, 0, width, height))
    finally:
        painter.end()
    return image


def _convert_svg_to_png(source: Path, output_dir: Path) -> Path:
    image = _svg_to_image(source)
    try:
        output = _unique_output_path(output_dir, source, ".png")
        if not image.save(str(output), "PNG"):
            raise OSError(f"No se pudo escribir el PNG: {output}")
        return output
    finally:
        image = QImage()


def _convert_svg_to_ico(source: Path, output_dir: Path) -> Path:
    rendered = _svg_to_image(source, max_dimension=1024)
    try:
        buffer = rendered.bits()
        buffer.setsize(rendered.sizeInBytes())
        raster = Image.frombuffer(
            "RGBA",
            (rendered.width(), rendered.height()),
            bytes(buffer),
            "raw",
            "BGRA",
            0,
            1,
        ).copy()
        try:
            output = _unique_output_path(output_dir, source, ".ico")
            return _write_ico(raster, output)
        finally:
            raster.close()
    finally:
        rendered = QImage()


def images_to_ico(
    paths: List[Path], output_dir: Path,
    cancel_check: CancelCheck = None, progress_cb: ProgressCallback = None
):
    return _run_batch(paths, output_dir, _convert_raster_to_ico, cancel_check, progress_cb)


def images_to_png(
    paths: List[Path], output_dir: Path,
    cancel_check: CancelCheck = None, progress_cb: ProgressCallback = None
):
    return _run_batch(paths, output_dir, _convert_raster_to_png, cancel_check, progress_cb)


def images_to_jpg(
    paths: List[Path], output_dir: Path,
    cancel_check: CancelCheck = None, progress_cb: ProgressCallback = None
):
    return _run_batch(paths, output_dir, _convert_raster_to_jpg, cancel_check, progress_cb)


def svgs_to_png(
    paths: List[Path], output_dir: Path,
    cancel_check: CancelCheck = None, progress_cb: ProgressCallback = None
):
    return _run_batch(paths, output_dir, _convert_svg_to_png, cancel_check, progress_cb)


def svgs_to_ico(
    paths: List[Path], output_dir: Path,
    cancel_check: CancelCheck = None, progress_cb: ProgressCallback = None
):
    return _run_batch(paths, output_dir, _convert_svg_to_ico, cancel_check, progress_cb)


def _id3_text_values(value) -> List[str]:
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = [value]

    result = []
    for item in values:
        if item is None:
            continue
        if isinstance(item, bytes):
            try:
                text = item.decode("utf-8")
            except UnicodeDecodeError:
                text = item.decode("latin-1", errors="replace")
        else:
            text = str(item)
        if text:
            result.append(text)
    return result


def _copy_audio_tags(source_path: Path, output_path: Path) -> None:
    """Copy ID3 frames verbatim and map other Mutagen tags, including custom keys, to ID3."""
    from mutagen import File as MutagenFile
    from mutagen.id3 import (
        ID3, APIC, COMM, TALB, TBPM, TCOM, TCON, TIT2, TPE1, TPE2, TPOS, TRCK,
        TDRC, TPUB, TXXX,
    )

    source_audio = MutagenFile(str(source_path), easy=False)
    source_tags = getattr(source_audio, "tags", None) if source_audio else None

    # An MP3 file may contain a valid ID3 header even when the audio parser
    # cannot identify a frame in a short or damaged sample.
    if source_tags is None and source_path.suffix.lower() == ".mp3":
        try:
            source_tags = ID3(str(source_path))
        except Exception:
            source_tags = None

    if not source_tags:
        return

    target_tags = ID3()
    if isinstance(source_tags, ID3):
        for frame in source_tags.values():
            target_tags.add(copy.deepcopy(frame))
    else:
        standard_frames = {
            "title": TIT2, "©nam": TIT2,
            "artist": TPE1, "©art": TPE1,
            "albumartist": TPE2, "album artist": TPE2, "aart": TPE2,
            "album": TALB, "©alb": TALB,
            "composer": TCOM, "©wrt": TCOM,
            "genre": TCON, "©gen": TCON,
            "date": TDRC, "year": TDRC, "©day": TDRC,
            "track": TRCK, "tracknumber": TRCK, "trkn": TRCK,
            "disc": TPOS, "discnumber": TPOS, "disk": TPOS,
            "bpm": TBPM, "tempo": TBPM,
            "publisher": TPUB, "label": TPUB,
        }
        for raw_key, raw_value in source_tags.items():
            key = str(raw_key)
            normalised = key.lower()
            values = _id3_text_values(raw_value)

            if normalised in {"covr", "metadata_block_picture"}:
                covers = raw_value if isinstance(raw_value, (list, tuple)) else [raw_value]
                for index, cover in enumerate(covers):
                    cover_bytes = bytes(cover) if isinstance(cover, (bytes, bytearray, memoryview)) else None
                    if not cover_bytes:
                        continue
                    mime = "image/png" if cover_bytes.startswith(b"\x89PNG") else "image/jpeg"
                    target_tags.add(APIC(
                        encoding=3, mime=mime, type=3, desc=f"Cover {index + 1}", data=cover_bytes
                    ))
                continue

            if normalised in {"comment", "description", "©cmt"}:
                if values:
                    target_tags.add(COMM(encoding=3, lang="eng", desc="", text=values))
                continue

            frame_class = standard_frames.get(normalised)
            if frame_class and values:
                target_tags.add(frame_class(encoding=3, text=values))
                continue

            # Preserve vendor/custom fields as user-defined ID3 text frames.
            custom_name = key.rsplit(":", 1)[-1].strip() or key
            if values:
                target_tags.add(TXXX(encoding=3, desc=custom_name, text=values))

        for picture_index, picture in enumerate(getattr(source_audio, "pictures", []) or []):
            data = getattr(picture, "data", None)
            if data:
                target_tags.add(APIC(
                    encoding=3,
                    mime=getattr(picture, "mime", "image/jpeg"),
                    type=3,
                    desc=f"Cover {picture_index + 1}",
                    data=data,
                ))

    if target_tags:
        target_tags.save(str(output_path), v2_version=3)


def _convert_audio_to_mp3(source: Path, output_dir: Path) -> Path:
    import imageio_ffmpeg

    output = _unique_output_path(output_dir, source, ".mp3")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(source),
        "-map", "0:a:0",
        "-vn",
        "-codec:a", "libmp3lame",
        "-q:a", "2",
        "-map_metadata", "-1",
        "-id3v2_version", "3",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        output.unlink(missing_ok=True)
        details = (result.stderr or result.stdout or "FFmpeg terminó con error.").strip()
        raise RuntimeError(details[-1600:])

    try:
        _copy_audio_tags(source, output)
    except Exception as exc:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"El audio se convirtió, pero no se pudieron preservar sus etiquetas: {exc}") from exc
    return output


def audios_to_mp3(
    paths: List[Path], output_dir: Path,
    cancel_check: CancelCheck = None, progress_cb: ProgressCallback = None
):
    return _run_batch(paths, output_dir, _convert_audio_to_mp3, cancel_check, progress_cb)


def words_to_pdf(
    paths: List[Path], output_dir: Path,
    cancel_check: CancelCheck = None, progress_cb: ProgressCallback = None
):
    """Use the installed Microsoft Word COM automation server to export Word files as PDF."""
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("La conversión de Word a PDF requiere Microsoft Word y pywin32.") from exc

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: List[Path] = []
    warnings: List[str] = []
    word = None
    total = len(paths)

    pythoncom.CoInitialize()
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0

        for index, raw_path in enumerate(paths):
            source = Path(raw_path)
            if cancel_check and cancel_check():
                raise InterruptedError("Operation cancelled")

            document = None
            try:
                output = _unique_output_path(output_dir, source, ".pdf")
                document = word.Documents.Open(
                    FileName=str(source.resolve()),
                    ConfirmConversions=False,
                    ReadOnly=True,
                    AddToRecentFiles=False,
                    Visible=False,
                )
                document.SaveAs2(str(output), FileFormat=17)
                generated.append(output)
            except Exception as exc:
                logging.exception("Word to PDF conversion failed for %s", source)
                warnings.append(f"{source.name}: {exc}")
            finally:
                if document is not None:
                    try:
                        document.Close(SaveChanges=0)
                    except Exception:
                        logging.warning("Could not close Word document %s", source, exc_info=True)
                if progress_cb:
                    progress_cb(index + 1, total)
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                logging.warning("Could not close Microsoft Word", exc_info=True)
        pythoncom.CoUninitialize()

    return generated, warnings


def run_file_conversion(
    task_type: str,
    paths: List[Path],
    output_dir: Path,
    cancel_check: CancelCheck = None,
    progress_cb: ProgressCallback = None,
) -> Tuple[List[Path], List[str]]:
    """Dispatch a plugin task to the correct converter."""
    converters = {
        "images_to_ico": images_to_ico,
        "images_to_png": images_to_png,
        "images_to_jpg": images_to_jpg,
        "svg_to_png": svgs_to_png,
        "svg_to_ico": svgs_to_ico,
        "audio_to_mp3": audios_to_mp3,
        "word_to_pdf": words_to_pdf,
    }
    converter = converters.get(task_type)
    if converter is None:
        raise ValueError(f"Unsupported file conversion task: {task_type}")
    return converter(paths, output_dir, cancel_check=cancel_check, progress_cb=progress_cb)
