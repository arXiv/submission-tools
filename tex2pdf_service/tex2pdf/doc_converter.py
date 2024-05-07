"""
Turn multiple documents into one PDF.
"""
import os
import shutil
import typing

import pikepdf
from PIL import Image, UnidentifiedImageError
from pikepdf import PdfError

from tex2pdf import graphics_exts
from tex2pdf.service_logger import get_logger

def convert_image_to_pdf(image_path: str, pdf_path: str) -> str:
    """Convert an image to a PDF."""
    image = Image.open(image_path)
    try:
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.save(pdf_path, 'PDF', resolution=100.0)
    finally:
        image.close()
        pass
    return pdf_path


def strip_to_basename(path_list: typing.List[str], extent: None | str = None) -> typing.List[str]:
    """Strip the path to the basename."""
    if extent is None:
        return [os.path.basename(path) for path in path_list]
    return [os.path.splitext(os.path.basename(path))[0] + extent for path in path_list]


def combine_documents(doc_list: typing.List[str], out_dir: str, out_filename: str,
                      log_extra: dict|None=None) -> typing.Tuple[str, list, list]:
    """Combine multiple PDFs and maybe some pictures, and images into one PDF.

    Args:
        doc_list (list): List of documents. (can be in any dir)
        out_dir (str): Output directory.
        out_filename (str): Name of output PDF.
        log_extra (dict): Extra logging information.
    """
    output_path = os.path.join(out_dir, out_filename)
    converted_docs: typing.List[str] = []
    failed_docs: typing.List[str] = []
    if len(doc_list) == 1 and doc_list[0].endswith(".pdf"):
        if doc_list[0] != output_path:
            shutil.move(doc_list[0], output_path)
        converted_docs.append(os.path.basename(doc_list[0]))
        return out_filename, converted_docs, failed_docs
    with pikepdf.new() as pdf:
        logger = get_logger()
        for doc_path in doc_list:
            [stem, ext] = os.path.splitext(doc_path)
            # This should exist but be safe.
            if not os.path.exists(doc_path):
                continue
            if ext.lower() == ".pdf":  # This should not need lower() but be safe. Should I assert?
                try:
                    with pikepdf.Pdf.open(doc_path) as pdf_page:
                        pdf.pages.extend(pdf_page.pages)
                    converted_docs.append(doc_path)
                except PdfError:
                    failed_docs.append(doc_path)
                    logger.warning("Cannot open PDF file %s", doc_path, extra=log_extra)
                    pass
            elif ext.lower() in graphics_exts:
                temp_pdf = os.path.join(out_dir, stem + '.pdf')
                try:
                    pdf_filename = convert_image_to_pdf(doc_path, temp_pdf)
                    if pdf_filename and os.path.exists(pdf_filename):
                        converted_docs.append(doc_path)
                        with pikepdf.Pdf.open(pdf_filename) as pdf_page:
                            pdf.pages.extend(pdf_page.pages)
                        pass
                except UnidentifiedImageError:
                    failed_docs.append(doc_path)
                    logger.warning("Unsupported %s", doc_path, extra=log_extra)
                    pass
                except Exception as _exc:
                    failed_docs.append(doc_path)
                    logger.warning("Unknown error %s", doc_path, extra=log_extra,
                                   exc_info=True)
                    pass
                pass
            pass
        pdf.save(output_path)
    return out_filename, strip_to_basename(converted_docs), strip_to_basename(failed_docs)
