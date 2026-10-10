# arxiv-pdf-watermark

Puts the arXiv watermark (the vertical `arXiv:...` stamp in the left margin of
the first page, optionally a link) on a PDF.

```python
from arxiv_pdf_watermark import Watermark, add_watermark_text_to_pdf_bounded

add_watermark_text_to_pdf_bounded(Watermark("arXiv:2601.00001v1  [cs.LG]  1 Jan 2026",
                                            "https://arxiv.org/abs/2601.00001v1"),
                                  "in.pdf", "out.pdf")
```

`add_watermark_text_to_pdf_bounded` runs the stamping in a subprocess and kills
it after `timeout` seconds; `add_watermark_text_to_pdf` runs it in-process.

Used by `tex2pdf-service` (compile-time stamping) and by publish's file-ops
(stamping announced papers).

## Tests

```bash
cd pdf-watermark
poetry install --with=dev
PYTHONPATH=$PWD poetry run pytest tests
```
