"""
Independent PDF and Image Conversion Engine for CatchEtude.
Engine independiente de conversión y extracción de PDFs e imágenes.
"""

import logging
from pathlib import Path
from typing import Callable, Optional, List, Tuple
import pymupdf as fitz  # PyMuPDF


def resolve_output_pdf_name(target_dir: Path) -> Path:
    """
    Generates unique new_document_000.pdf path inside target_dir to prevent collisions.
    """
    counter = 0
    while True:
        candidate = target_dir / f"new_document_{counter:03d}.pdf"
        if not candidate.exists():
            return candidate
        counter += 1


def _report_progress(progress_cb, current, total, message, indeterminate=False):
    if progress_cb:
        progress_cb(int(current), int(total), str(message), bool(indeterminate))


def resolve_unique_output_path(target_dir: Path, filename: str) -> Path:
    """Avoid overwriting outputs when different input PDFs share the same stem."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = Path(filename)
    candidate = target_dir / name.name
    counter = 1
    while candidate.exists():
        candidate = target_dir / f"{name.stem}_{counter:03d}{name.suffix}"
        counter += 1
    return candidate



def images_to_pdf(
    image_paths: List[Path],
    output_dir: Path,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[..., None]] = None
) -> Path:
    """
    Combines multiple image files into a single PDF file.
    Output: output_dir / new_document_000.pdf (incremented on collision).
    """
    if not image_paths:
        raise ValueError("Selecciona al menos una imagen para crear el PDF.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    total = len(image_paths)
    try:
        for idx, img_path in enumerate(image_paths):
            if cancel_check and cancel_check():
                raise InterruptedError("Operation cancelled")

            _report_progress(progress_cb, idx, total, f"Convirtiendo imagen {idx + 1}/{total}: {Path(img_path).name}", True)
            img_doc = fitz.open(str(img_path))
            try:
                pdf_bytes = img_doc.convert_to_pdf()
            finally:
                img_doc.close()

            img_pdf = fitz.open("pdf", pdf_bytes)
            try:
                doc.insert_pdf(img_pdf)
            finally:
                img_pdf.close()

            _report_progress(progress_cb, idx + 1, total, f"Imagen añadida al PDF: {Path(img_path).name} ({idx + 1}/{total})")

        _report_progress(progress_cb, 0, 1, "Guardando el documento PDF…", True)
        output_path = resolve_output_pdf_name(output_dir)
        doc.save(str(output_path))
        _report_progress(progress_cb, 1, 1, f"PDF generado: {output_path.name}")
        return output_path
    finally:
        doc.close()


def pdf_to_jpeg(
    pdf_paths: List[Path],
    output_dir: Path,
    dpi: int = 150,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[..., None]] = None
) -> List[Path]:
    """
    Renders every page of each PDF into JPEG format.
    Output naming: <pdf_name>_page_{001}.jpeg
    """
    generated_files: List[Path] = []

    # Calculate total pages across all PDFs for progress tracking
    total_pages = 0
    pdf_docs = []
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    open_errors = []
    for file_index, p in enumerate(pdf_paths):
        _report_progress(progress_cb, file_index, max(1, len(pdf_paths)), f"Abriendo PDF {file_index + 1}/{len(pdf_paths)}: {p.name}", True)
        try:
            doc = fitz.open(str(p))
            pdf_docs.append((p, doc))
            total_pages += len(doc)
        except Exception as e:
            logging.error(f"Failed to open PDF {p}: {e}")
            open_errors.append(f"{p.name}: {e}")

    if not pdf_docs:
        raise RuntimeError("No se pudo abrir ningún PDF. " + "; ".join(open_errors))

    processed_pages = 0
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    try:
        for p, doc in pdf_docs:
            stem = p.stem
            for page_idx in range(len(doc)):
                if cancel_check and cancel_check():
                    raise InterruptedError("Operation cancelled")

                page = doc.load_page(page_idx)
                pix = page.get_pixmap(matrix=mat, alpha=False)

                output_name = f"{stem}_page_{page_idx + 1:03d}.jpeg"
                out_path = resolve_unique_output_path(output_dir, output_name)
                pix.save(str(out_path))
                generated_files.append(out_path)

                processed_pages += 1
                _report_progress(
                    progress_cb, processed_pages, total_pages,
                    f"Renderizando {p.name}: página {page_idx + 1}/{len(doc)}",
                )
    finally:
        for _, doc in pdf_docs:
            doc.close()

    return generated_files


def extract_pdf_images(
    pdf_paths: List[Path],
    output_dir: Path,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[..., None]] = None
) -> Tuple[List[Path], List[str]]:
    """
    Extracts original embedded images from PDF files without rendering pages.
    Handles duplicate image references, multi-page image usage, and corrupt images.
    Output naming: <pdf_name>_page_{001}.<ext>
    Returns (extracted_paths, warning_messages).
    """
    extracted_files: List[Path] = []
    warnings: List[str] = []

    pdf_docs = []
    total_pages = 0
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for file_index, p in enumerate(pdf_paths):
        _report_progress(progress_cb, file_index, max(1, len(pdf_paths)), f"Abriendo PDF {file_index + 1}/{len(pdf_paths)} para extraer imágenes: {p.name}", True)
        try:
            doc = fitz.open(str(p))
            pdf_docs.append((p, doc))
            total_pages += len(doc)
        except Exception as e:
            warnings.append(f"No se pudo abrir el PDF {p.name}: {e}")

    processed_pages = 0

    try:
        for p, doc in pdf_docs:
            stem = p.stem
            seen_xrefs = set()
            image_counter = 1

            for page_idx in range(len(doc)):
                if cancel_check and cancel_check():
                    raise InterruptedError("Operation cancelled")

                page = doc.load_page(page_idx)
                image_info_list = page.get_images(full=True)

                for img_info in image_info_list:
                    if cancel_check and cancel_check():
                        raise InterruptedError("Operation cancelled")

                    xref = img_info[0]
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)

                    try:
                        extracted_image = doc.extract_image(xref)
                        if not extracted_image:
                            continue

                        image_bytes = extracted_image.get("image")
                        image_ext = extracted_image.get("ext", "png")

                        if not image_bytes:
                            continue

                        output_name = f"{stem}_page_{image_counter:03d}.{image_ext}"
                        out_path = resolve_unique_output_path(output_dir, output_name)
                        out_path.write_bytes(image_bytes)
                        extracted_files.append(out_path)
                        image_counter += 1

                    except Exception as e:
                        logging.warning(f"Error extracting image xref {xref} from {p.name}: {e}")
                        warnings.append(f"Error al extraer imagen xref {xref} de {p.name}")

                processed_pages += 1
                _report_progress(
                    progress_cb, processed_pages, total_pages,
                    f"Analizando {p.name}: página {page_idx + 1}/{len(doc)} "
                    f"({len(extracted_files)} imagen(es) extraída(s))",
                )

    finally:
        for _, doc in pdf_docs:
            doc.close()

    return extracted_files, warnings


def merge_pdfs(
    pdf_paths: List[Path],
    output_dir: Path,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[..., None]] = None
) -> Path:
    """
    Merges multiple PDF files into one single PDF file.
    Output: output_dir / new_document_000.pdf (incremented on collision).
    """
    if not pdf_paths:
        raise ValueError("Selecciona al menos un PDF para unir.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    merged_doc = fitz.open()
    total = len(pdf_paths)

    try:
        for idx, p in enumerate(pdf_paths):
            if cancel_check and cancel_check():
                raise InterruptedError("Operation cancelled")

            _report_progress(progress_cb, idx, total, f"Abriendo PDF {idx + 1}/{total}: {p.name}", True)
            doc = fitz.open(str(p))
            try:
                merged_doc.insert_pdf(doc)
            finally:
                doc.close()

            _report_progress(progress_cb, idx + 1, total, f"PDF incorporado: {p.name} ({idx + 1}/{total})")

        _report_progress(progress_cb, 0, 1, "Guardando el PDF combinado…", True)
        output_path = resolve_output_pdf_name(output_dir)
        merged_doc.save(str(output_path))
        _report_progress(progress_cb, 1, 1, f"PDF combinado generado: {output_path.name}")
        return output_path
    finally:
        merged_doc.close()
