import fitz  # PyMuPDF
import typing
from collections import OrderedDict
from hashlib import sha1 as hash_func
from rapidfuzz.distance.Levenshtein import distance as levenshtein_distance


def similarity(text_1: str, text_2: str) -> float:
    n_chars = max(len(text_1), len(text_2))
    if n_chars == 0:
        return 1.0
    return 1.0 - (float(levenshtein_distance(text_1, text_2)) / n_chars)

def image_digest(image: bytes) -> str:
    hash_obj = hash_func()
    hash_obj.update(image)
    return hash_obj.hexdigest()


class PageProfile:
    text: str
    text_digest: str
    image_digests: typing.List[typing.List[int]]

    def __init__(self, page: fitz.Page):
        self.digest(page)
        pass

    def digest(self, page: fitz.Page) -> None:
        text = page.get_text()
        self.text = text
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
        self.image_digests = [list(image[2:4]) for image in page.get_images()]
        pass

    def as_ordict(self) -> OrderedDict:
        page: OrderedDict[str, typing.Any] = OrderedDict()
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

    def __init__(self) -> None:
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
        return self.as_ordict()

    def as_dict(self) -> dict:
        "make dicf from self"
        me = dict(self.as_ordict())
        for index in range(len(me["pages"])):
            me["pages"][index] = dict(me["pages"][index])
        return me

    def as_ordict(self) -> OrderedDict:
        "make dicf from self"
        me: OrderedDict[str, typing.Any] = OrderedDict()
        me["n_pages"] = len(self.pages)
        me["image_count"] = self.image_count
        me["pages"] = [page.as_ordict() for page in self.pages]
        return me

    def __dict__(self) -> dict:
        return self.as_dict()


class PdfTextSimilarity:
    """See the similarity of two pdf files"""

    pages: typing.List[PageProfile]

    def __init__(self, prof_a: PdfProfile, prof_b: PdfProfile) -> None:
        self.prof_a = prof_a
        self.prof_b = prof_b

    def compare_texts(self):
        """Takes a look at each page of PDF file"""
        self.similarities = [similarity(page_a.text, page_b.text) for page_a, page_b in zip(self.prof_a.pages, self.prof_b.pages)]
        return sum(self.similarities) / len(self.similarities) if self.similarities else 0
