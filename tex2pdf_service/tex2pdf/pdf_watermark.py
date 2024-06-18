"""
Adding the watermark string to the PDF file.
"""
import io
import os
import tempfile

# from tex2pdf.accessor import BaseAccessor
import pathlib
import pikepdf
import reportlab
import reportlab.pdfgen
import reportlab.pdfgen.canvas
import reportlab.lib.pagesizes
import reportlab.lib.units
from reportlab.pdfgen.textobject import PDFTextObject
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.lib.enums import TA_CENTER

# This is how it is done in arxiv-lib/lib/TeX/AutoTeX/StampPDF.pm
#
# q
# ## Push
# 0.5 G 0.5 g
# ## Set fill and stroke gray to 0.5
# BT
# ## Begin text
# /arXivStAmP 20 Tf 0 1 -1 0 32 $yoffset Tm
# ## Set font to Times-Roman, 20, rotate 90 degrees and set coordinates to 32, $yoffset
# ($stampref->[0])Tj
# ## Print the watermark text
# ET
# ## End text
# Q
# ## Pop


def gen_watermark_pdf(watermark: str, in_pdf: pathlib.Path | str, out_pdf: str) -> None:
    """
    Generate a PDF file with the given watermark.

    :param watermark: watermark text
    :param in_pdf: input PDF file - this is unchanged. Only used to get the page size.
    :param out_pdf: output PDF filename.
    """
    page_size = reportlab.lib.pagesizes.letter

    if in_pdf:
        with pikepdf.Pdf.open(in_pdf) as source:
            page = source.pages[0]
            relevant_box = page.get('/CropBox', page.get('/MediaBox'))
            if relevant_box and isinstance(relevant_box, list) and len(relevant_box) >= 4:
                page_size = (relevant_box[2] - relevant_box[0], relevant_box[3] - relevant_box[1])
                pass
            pass
        pass
    canvas = reportlab.pdfgen.canvas.Canvas(out_pdf, pagesize=page_size)
    canvas.setFont('Times-Roman', 20)

    # This method does not support links!
    # canvas.drawString(32, 32, watermark)
    # text = PDFTextObject(canvas)
    # text.setFillGray(0.5)
    # text.setStrokeGray(0.5)
    # text.setFont('Times-Roman', 20)
    # y_offset = 432 - 5 * len(watermark)
    # text.setTextTransform(0, 1, -1, 0, 32, y_offset)
    # text.textLine(watermark)
    # canvas.drawText(text)

    wm_style = ParagraphStyle('watermark_style',
        fontName = "Times-Roman",
        fontSize = 20,
        align=TA_CENTER,
        textColor = "#7f7f7f",
        # leading is the line height, and influences the action box size
        leading=20,
    )
    p = Paragraph(watermark, wm_style)
    # rotate 90deg and shift 32pt to the right
    canvas.transform(0, 1, -1, 0, 32, 0)
    # wrap on huge size so that we have only one line
    p.wrap(7200,7200)
    actual_width = p.getActualLineWidths0()[0]
    p.wrapOn(canvas, page_size[0], page_size[1])
    p.drawOn(canvas, (page_size[1] - actual_width)/2, 0)
    canvas.save()
    pass


def add_watermark_text_to_pdf(watermark: str,
                              in_pdf: pathlib.Path | str,
                              out_pdf: str | io.FileIO) -> None:
    """combines/overlays the watermark PDF with the source PDF"""
    with tempfile.TemporaryDirectory(suffix="watering") as tempdir:
        watermark_pdf = os.path.join(tempdir, "watermark.pdf")
        gen_watermark_pdf(watermark, in_pdf, watermark_pdf)
        overlay = pikepdf.Pdf.open(watermark_pdf)
        source = pikepdf.Pdf.open(in_pdf)
        if source and source.pages:
            source_page = overlay.pages[0]
            destination_page = source.pages[0]
            indirect_annots = overlay.make_indirect(source_page.Annots)
            if '/Annots' in destination_page:
                # TODO needs testing!!!
                destination_page.Annots.append(source.copy_foreign(indirect_annots))
            else:
                destination_page.Annots = source.copy_foreign(indirect_annots)
            destination_page.add_overlay(pikepdf.Page(source_page))  # type: ignore
            if isinstance(out_pdf, io.FileIO):
                source.save(out_pdf)
            else:
                with open(out_pdf, 'wb') as fd:
                    source.save(fd)
