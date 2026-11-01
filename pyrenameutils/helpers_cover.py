from pathlib import Path
import mimetypes

from mutagen.id3 import ID3, ID3NoHeaderError, APIC
from mutagen.mp4 import MP4, MP4Cover


def read_cover_art(path: str):
    lower = path.lower()

    if lower.endswith('.mp3'):
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            return None

        for frame in tags.getall('APIC'):
            if getattr(frame, "data", None):
                return frame.data
        return None

    if lower.endswith(('.mp4', '.m4a', '.m4v')):
        audio = MP4(path)
        if audio.tags and 'covr' in audio.tags and audio.tags['covr']:
            return bytes(audio.tags['covr'][0])
        return None

    return None


def write_cover_art_data(path: str, img_bytes: bytes, mime: str = "image/jpeg"):
    lower = path.lower()
    mime = mime or "image/jpeg"

    if lower.endswith('.mp3'):
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()

        tags.delall('APIC')
        tags.add(APIC(encoding=3, mime=mime, type=3, desc='Cover', data=img_bytes))
        tags.save(path)
        return

    if lower.endswith(('.mp4', '.m4a', '.m4v')):
        audio = MP4(path)
        if audio.tags is None:
            audio.add_tags()

        fmt = MP4Cover.FORMAT_PNG if "png" in mime.lower() else MP4Cover.FORMAT_JPEG
        audio.tags['covr'] = [MP4Cover(img_bytes, imageformat=fmt)]
        audio.save()
        return

    raise RuntimeError("Formato no soportado para carátula")


def write_cover_art(path: str, image_path: str):
    img_bytes = Path(image_path).read_bytes()
    mime, _ = mimetypes.guess_type(image_path)
    write_cover_art_data(path, img_bytes, mime or "image/jpeg")


def export_cover_art(path: str, output_path: str):
    data = read_cover_art(path)
    if not data:
        raise RuntimeError("No hay carátula para exportar")
    Path(output_path).write_bytes(data)