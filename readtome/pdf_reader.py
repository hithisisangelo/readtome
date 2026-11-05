"""PDF -> Book. Strips running headers/footers and page numbers, rejoins hyphenated and
page-split paragraphs, and finds chapters from the PDF outline or from headings."""

import re
from collections import Counter
from dataclasses import dataclass

import pymupdf

from .model import Book, Chapter
from .text import normalize_title

_PAGE_NUM = re.compile(r"(page\s*)?([\divxlc]+)(\s*(of|/)\s*\d+)?", re.IGNORECASE)
_CHAPTER_HEAD = re.compile(
    r"(chapter|part|book|prologue|epilogue|introduction|preface|foreword|afterword|conclusion|"
    r"acknowledg\w*|appendix)\b[\w\s.:'’-]{0,60}",
    re.IGNORECASE)
# A broken-up "CH APTER" left dangling at the very end of the previous chapter
_STRAY_CHAPTER = re.compile(r"\s*\bC\s?H\s?A\s?P\s?T\s?E\s?R(\s+\d+)?\s*$")
# Table-of-contents entries: "SOME HEADING . . . . . . 34" or "Heading........ 31"
_TOC_LINE = re.compile(r"(\.\s?){4,}\s*[\divxlc]+\s*$", re.IGNORECASE)
_ENDS_SENTENCE =re.compile(r"[.!?:…\"'”’)\]]$")
# A footnote number glued to the end of a word or sentence: "end of the war.12"
_TRAILING_REF = re.compile(r"(?<=[a-z][.,;:!?\"”’])\d{1,3}(?=\s|$)")


@dataclass
class _Line:
    y0: float
    y1: float
    text: str
    size: float


@dataclass
class _Para:
    page: int
    y: float
    text: str
    size: float


def _page_lines(page) -> list[list[_Line]]:
    """Text lines grouped by block, in reading order."""
    blocks = []
    for b in page.get_text("dict", sort=True)["blocks"]:
        if b.get("type") != 0:
            continue
        lines = []
        for ln in b["lines"]:
            text = "".join(s["text"] for s in ln["spans"]).strip()
            if text:
                size = max(s["size"] for s in ln["spans"])
                lines.append(_Line(ln["bbox"][1], ln["bbox"][3], text, round(size, 1)))
        if lines:
            blocks.append(lines)
    return blocks


def _join_lines(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        if out.endswith("-") and ln[:1].islower():
            out = out[:-1] + ln
        elif out:
            out += " " + ln
        else:
            out = ln
    return out


def _margin_key(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower()).strip()


def _extract_paras(doc) -> list[_Para]:
    pages = [(p.rect.height, _page_lines(p)) for p in doc]

    # Lines in the top/bottom 8% that repeat across many pages are running headers/footers.
    margin_counts = Counter()
    for height, blocks in pages:
        keys = {_margin_key(l.text) for b in blocks for l in b
                if l.y1 < height * 0.08 or l.y0 > height * 0.92}
        margin_counts.update(keys)
    threshold = max(3, len(pages) * 0.2)
    repeated = {k for k, n in margin_counts.items() if n >= threshold}

    paras = []
    for pno, (height, blocks) in enumerate(pages):
        for block in blocks:
            kept = [l for l in block
                    if not ((l.y1 < height * 0.08 or l.y0 > height * 0.92)
                            and (_margin_key(l.text) in repeated or _PAGE_NUM.fullmatch(l.text)))
                    and not _TOC_LINE.search(l.text)]
            # A block that opens with ALL-CAPS heading lines followed by body text:
            # keep the heading as its own paragraph so it gets a pause.
            head = 0
            while head < len(kept) and len(kept[head].text) < 80 and kept[head].text.isupper():
                head += 1
            groups = [kept[:head], kept[head:]] if 0 < head < len(kept) else [kept]
            for g in groups:
                if g:
                    paras.append(_Para(pno, g[0].y0, _join_lines([l.text for l in g]), max(l.size for l in g)))
    return paras


def _body_size(paras: list[_Para]) -> float:
    sizes = Counter()
    for p in paras:
        sizes[p.size] += len(p.text)
    return sizes.most_common(1)[0][0] if sizes else 10.0


def _boundaries_from_toc(doc, paras, toc_level):
    toc = [e for e in doc.get_toc(simple=True) if e[2] >= 1]
    if not toc:
        return []
    level = toc_level
    if level is None:
        level = 1
        if sum(e[0] == 1 for e in toc) < 2 and any(e[0] == 2 for e in toc):
            level = 2
    bounds = []
    for lvl, title, page in toc:
        if lvl != level:
            continue
        pno = page - 1
        want = normalize_title(title)[:40]
        y = 0.0
        for p in paras:
            if p.page == pno and want and normalize_title(p.text).startswith(want):
                y = p.y
                break
        bounds.append((pno, y, title.strip()))
    return bounds


def _boundaries_from_headings(doc, paras):
    body = _body_size(paras)
    heads = []
    for i, p in enumerate(paras):
        height = doc[p.page].rect.height
        short = len(p.text) < 90 and not p.text.endswith(".")
        # Larger than body text, so "CHAPTER 1" lines in the table of contents don't count
        by_name = _CHAPTER_HEAD.fullmatch(p.text) and p.size > body * 1.15
        by_size = p.size >= body * 1.5 and p.y < height * 0.4
        if short and (by_name or by_size):
            prev = heads[-1] if heads else None
            # "Chapter 3" followed directly by "The Long Night" -> one title
            if prev and prev[3] == i - 1 and prev[0] == p.page:
                heads[-1] = (prev[0], prev[1], f"{prev[2]}: {p.text}", i)
            else:
                heads.append((p.page, p.y, p.text, i))
    return [(pg, y, _with_subtitle(paras, i, title)) for pg, y, title, i in heads]


def _with_subtitle(paras, i, title):
    """'CHAPTER 2' followed by body-size ALL-CAPS lines 'THE LURE' / '(AND THE DANGERS)' /
    'OF TRADING' becomes 'CHAPTER 2: THE LURE (AND THE DANGERS) OF TRADING'."""
    if ":" in title or not re.fullmatch(r"(chapter|part|book)\s+\S+", title, re.IGNORECASE):
        return title
    pieces = []
    for p in paras[i + 1:i + 4]:
        if p.page != paras[i].page or len(p.text) > 80 or not p.text.isupper():
            break
        joined_ok = not pieces or pieces[-1][-1:] in ",:" or re.match(r"\(|(OF|AND|OR|THE|IN|TO)\b", p.text)
        if not joined_ok:
            break
        pieces.append(p.text)
        if p.text[-1:] in "?.!":
            break
    if not pieces:
        return title
    sub = re.sub(r"^\d+\s+", "", " ".join(pieces)).rstrip(":,")
    return f"{title}: {sub}"


def _merge_paras(paras: list[_Para]) -> list[str]:
    """Rejoin paragraphs that were split across a page or column break."""
    out: list[str] = []
    for p in paras:
        text = _TRAILING_REF.sub("", p.text)
        if out and not _ENDS_SENTENCE.search(out[-1]) and text[:1].islower():
            out[-1] = _join_lines([out[-1], text])
        else:
            out.append(text)
    return out


def load_pdf(path: str, toc_level: int | None = None) -> Book:
    doc = pymupdf.open(path)
    paras = _extract_paras(doc)
    if sum(len(p.text) for p in paras) < 50 * max(1, min(doc.page_count, 20)):
        raise SystemExit(f"{path} has almost no selectable text; it is probably a scanned book. "
                         "Run OCR on it first (for example with ocrmypdf), then try again.")

    bounds = _boundaries_from_toc(doc, paras, toc_level)
    if len(bounds) < 2:
        bounds = _boundaries_from_headings(doc, paras)
    if len(bounds) < 2:
        step = 10
        bounds = [(pg, 0.0, f"Part {n + 1}") for n, pg in enumerate(range(0, doc.page_count, step))]
    bounds.sort(key=lambda b: (b[0], b[1]))

    groups: list[tuple[str, list[_Para]]] = []
    if (bounds[0][0], bounds[0][1]) > (paras[0].page, paras[0].y):
        groups.append(("Front Matter", []))
    bi = 0
    for p in paras:
        while bi < len(bounds) and (p.page, p.y) >= (bounds[bi][0], bounds[bi][1]):
            groups.append((bounds[bi][2], []))
            bi += 1
        groups[-1][1].append(p)
    chapters = [Chapter(title, _STRAY_CHAPTER.sub("", "\n\n".join(_merge_paras(ps))))
                for title, ps in groups if ps]

    meta = doc.metadata or {}
    cover = None
    try:
        cover = doc[0].get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("jpeg")
    except Exception:
        pass
    return Book(title=(meta.get("title") or "").strip(), author=(meta.get("author") or "").strip(),
                chapters=chapters, cover=cover, cover_mime="image/jpeg" if cover else None)
