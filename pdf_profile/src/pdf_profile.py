import fitz  # PyMuPDF
import typing
from collections import OrderedDict
from hashlib import sha1 as hash_func


def image_digest(image: bytes) -> str:
    hash_obj = hash_func()
    hash_obj.update(image)
    return hash_obj.hexdigest()


class PageProfile:
    text_digest: str
    image_digests: typing.List[typing.Tuple[typing.Any]]

    def __init__(self, page: fitz.Page):
        self.digest(page)
        pass

    def digest(self, page: fitz.Page) -> None:
        text = page.get_text()
        for encoding in ["iso-8859-1", "utf-8"]:
            try:
                text_bytes = text.encode(encoding)
            except UnicodeEncodeError:
                continue
            break
        hash_obj = hash_func()
        hash_obj.update(text_bytes)
        self.text_digest = hash_obj.hexdigest()

        # https://pymupdf.readthedocs.io/en/latest/document.html#Document.get_page_images
        # returns
        # (xref, smask, width, height, bpc, colorspace, alt. colorspace, name, filter, referencer)
        # Only thing I can use here is witgh/height
        self.image_digests = [image[2:4] for image in page.get_images()]
        pass

    def as_ordict(self) -> OrderedDict:
        page = OrderedDict()
        page['text_digest'] = self.text_digest
        page['image_digests'] = self.image_digests
        return page


    def as_dict(self) -> dict:
        return dict(self.as_ordict())

class PdfProfile:
    """Profiles PDF files, extracting the text length, counting the images in each page."""

    image_count: int
    text: str
    pages: typing.List[PageProfile]

    def __init__(self):
        self.pages = []
        self.image_count = 0

    def profile_pdf(self, pdf_path: str) -> OrderedDict:
        """Takes a look at each page of PDF file"""
        # Extract text
        doc = fitz.open(pdf_path)

        for page in doc:
            page_prof = PageProfile(page)
            self.image_count += len(page_prof.image_digests)
            self.pages.append(page_prof)
            pass
        return self.as_dict()

    def as_dict(self) -> dict:
        "make dicf from self"
        me = dict(self.as_ordict())
        for index in range(len(me["pages"])):
            me["pages"][index] = dict(me["pages"][index])
        return me

    def as_ordict(self) -> OrderedDict:
        "make dicf from self"
        me = OrderedDict()
        me["n_pages"] = len(self.pages)
        me["image_count"] = self.image_count
        me["pages"] = [page.as_ordict() for page in self.pages]
        return me

    def __dict__(self) -> dict:
        return self.as_dict()

