"""EPUB -> Book. Chapters come from the table of contents; files it doesn't list are
appended to the chapter before them."""

import posixpath
import re
import warnings
from urllib.parse import unquote

import ebooklib
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from ebooklib import epub

from .model import Book, Chapter

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib")

_BLOCK_TAGS = [
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "tr",
    "section", "article", "header", "footer", "figcaption", "dt", "dd", "table", "hr",
]
_DROP_TAGS = ["script", "style", "nav", "aside", "head", "svg", "math"]
_NOTE_KINDS = ("noteref", "footnote", "endnote", "rearnote", "pagebreak", "doc-noteref",
               "doc-footnote", "doc-endnote", "doc-pagebreak")
_MARK = "\x00CH{}\x00"
_MARK_RE = re.compile(r"\x00CH(\d+)\x00")


def _flatten_toc(toc, out):
    for entry in toc:
        if isinstance(entry, tuple):
            head, children = entry
            if getattr(head, "href", None):
                out.append((head.href, head.title))
            _flatten_toc(children, out)
        elif getattr(entry, "href", None):
            out.append((entry.href, entry.title))


def _toc_by_file(book) -> dict[str, list[tuple[str | None, str]]]:
    """Map each document's path (and basename, as a fallback) to [(fragment, title), ...]."""
    entries = []
    _flatten_toc(book.toc, entries)
    by_file: dict[str, list] = {}
    for href, title in entries:
        path, _, frag = unquote(href).partition("#")
        path = posixpath.normpath(path)
        item = (frag or None, (title or "").strip())
        for key in {path, posixpath.basename(path)}:
            lst = by_file.setdefault(key, [])
            if item not in lst:
                lst.append(item)
    return by_file


def _strip_notes(soup):
    for t in soup(_DROP_TAGS):
        t.decompose()
    for t in soup.find_all(True):
        if t.decomposed:
            continue
        kinds = f"{t.get('epub:type') or ''} {t.get('role') or ''}"
        if any(k in kinds for k in _NOTE_KINDS):
            t.decompose()
    for sup in soup.find_all("sup"):
        if sup.decomposed:
            continue
        if sup.find("a") or re.fullmatch(r"[\d*†‡§\[\]()]{1,6}", sup.get_text(strip=True)):
            sup.decompose()


def _segments(html: bytes, anchors: list[tuple[str | None, str]]):
    """Return (leading_title, heading, [(title, text), ...]) for one XHTML file.

    leading_title is the TOC title pointing at the top of the file (or None); the
    list holds text before the first mid-file anchor, then one entry per anchor."""
    soup = BeautifulSoup(html, "lxml")
    body = soup.body or soup
    heading = body.find(["h1", "h2", "h3"])
    heading = heading.get_text(" ", strip=True) if heading else None

    leading_title = None
    titles = []
    for frag, title in anchors:
        el = soup.find(id=frag) if frag else None
        if el is None or (not titles and el in (body, body.find(True))):
            leading_title = leading_title or title
            continue
        el.insert_before(_MARK.format(len(titles)))
        titles.append(title)

    _strip_notes(soup)
    for br in body.find_all("br"):
        br.replace_with("\n")
    for t in body.find_all(_BLOCK_TAGS):
        t.insert_before("\n\n")
        t.insert_after("\n\n")
    raw = body.get_text()

    parts = _MARK_RE.split(raw)  # [text, idx, text, idx, text...]
    segs = [(None, parts[0])]
    for i in range(1, len(parts), 2):
        segs.append((titles[int(parts[i])], parts[i + 1]))
    return leading_title, heading, segs


def _find_cover(book) -> tuple[bytes | None, str | None]:
    candidates = list(book.get_items_of_type(ebooklib.ITEM_COVER))
    for _, attrs in book.get_metadata("OPF", "cover"):
        item = book.get_item_with_id(attrs.get("content", ""))
        if item is not None:
            candidates.append(item)
    candidates += [i for i in book.get_items_of_type(ebooklib.ITEM_IMAGE) if "cover" in i.get_name().lower()]
    for item in candidates:
        mime = (item.media_type or "").lower()
        if mime in ("image/jpeg", "image/jpg", "image/png"):
            return item.get_content(), "image/png" if mime == "image/png" else "image/jpeg"
    return None, None


def _meta(book, name) -> str:
    values = book.get_metadata("DC", name)
    return values[0][0].strip() if values and values[0][0] else ""


def load_epub(path: str) -> Book:
    book = epub.read_epub(path)
    toc = _toc_by_file(book)
    chapters: list[Chapter] = []

    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT or isinstance(item, epub.EpubNav):
            continue
        name = posixpath.normpath(item.get_name())
        anchors = toc.get(name) or toc.get(posixpath.basename(name)) or []
        leading_title, heading, segs = _segments(item.get_content(), anchors)

        for i, (title, text) in enumerate(segs):
            if i == 0:
                starts_chapter = leading_title is not None or not toc or not chapters
                title = leading_title or (heading if starts_chapter else None)
            else:
                starts_chapter = True
            if starts_chapter:
                chapters.append(Chapter(title or "", text))
            else:
                chapters[-1].text += "\n\n" + text

    cover, mime = _find_cover(book)
    return Book(title=_meta(book, "title"), author=_meta(book, "creator"),
                chapters=chapters, cover=cover, cover_mime=mime)
