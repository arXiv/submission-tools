"""
Adding the watermark string to the PDF file.
"""
import io

import pathlib
import pymupdf

def add_watermark_text_to_pdf(watermark: str, wm_link: str | None,
                              in_pdf: pathlib.Path | str,
                              out_pdf: str | io.FileIO) -> None:
    """combines/overlays the watermark PDF with the source PDF"""

    fname = "Times-Roman"
    fsize = 20

    with pymupdf.open(in_pdf) as source:
        page = source[0]
        page_size = page.mediabox_size
        wm_length = pymupdf.get_text_length(watermark, fontname=fname, fontsize=fsize)
        lef = 32 - fsize
        rig = 32
        top = (page_size[1] - wm_length) / 2
        bot = (page_size[1] + wm_length) / 2
        page.insert_text(
            pymupdf.Point(rig, bot),
            watermark,
            fontname=fname,
            fontsize=fsize,
            rotate=90,
            color=(0.5,0.5,0.5),
            overlay=False
        )
        if wm_link:
            page.insert_link({
                'kind': pymupdf.LINK_URI,
                'from': pymupdf.Rect(lef,top,rig,bot),
                'uri': wm_link
            })
        if isinstance(out_pdf, io.FileIO):
            source.save(out_pdf)
        else:
            with open(out_pdf, 'wb') as fd:
                source.save(fd)
