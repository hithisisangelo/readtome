"""Text cleanup and chunking shared by the EPUB and PDF readers."""

import re

_LIGATURES = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st", "ﬆ": "st", "­": "", "​": "", "﻿": "",
})
# Superscript digits are almost always footnote references.
_SUPERSCRIPTS = re.compile(r"[¹²³⁰-⁹]+")
_BRACKET_REFS = re.compile(r"\[\d{1,3}\]")
_HAS_WORD = re.compile(r"[^\W_]")
_MISSING_SPACE = re.compile(r"(?<=[a-z][.!?])(?=[A-Z][a-z])")  # "else.I started" -> "else. I started"
_RULES = re.compile(r"_{2,}|-{3,}|={3,}")  # drawn lines like "_____CHAPTER 3_____"
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…][\"'”’)\]])\s+")


def clean(text: str) -> str:
    text = text.translate(_LIGATURES)
    text = _SUPERSCRIPTS.sub("", text)
    text = _RULES.sub(" ", text)
    # U+FFFD is what em dashes turn into in badly converted PDFs
    text = text.replace("�", " — ")
    text = _MISSING_SPACE.sub(" ", text)
    return _BRACKET_REFS.sub("", text)


def paragraphs(text: str) -> list[str]:
    """Split on blank lines, collapse whitespace, drop decoration-only lines like '* * *'."""
    out = []
    for block in re.split(r"\n\s*\n", clean(text)):
        block = " ".join(block.split())
        if _HAS_WORD.search(block):
            out.append(block)
    return out


def join_paragraphs(paras: list[str]) -> str:
    return "\n\n".join(paras)


def _split_long(piece: str, max_chars: int) -> list[str]:
    """Split one oversized sentence at commas/semicolons, then at spaces."""
    out, cur = [], ""
    for part in re.split(r"(?<=[,;:—])\s+|\s+", piece):
        if cur and len(cur) + 1 + len(part) > max_chars:
            out.append(cur)
            cur = part
        else:
            cur = f"{cur} {part}" if cur else part
    if cur:
        out.append(cur)
    return out


def chunk(text: str, max_chars: int = 2500) -> list[str]:
    """Group paragraphs into chunks of at most max_chars, splitting at sentence boundaries."""
    pieces = []
    for para in paragraphs(text):
        if len(para) <= max_chars:
            pieces.append((para, "\n\n"))
            continue
        for sent in _SENTENCE_END.split(para):
            for s in (_split_long(sent, max_chars) if len(sent) > max_chars else [sent]):
                pieces.append((s, " "))
        pieces[-1] = (pieces[-1][0], "\n\n")

    chunks, cur = [], ""
    for piece, sep in pieces:
        if cur and len(cur) + len(piece) + 2 > max_chars:
            chunks.append(cur.strip())
            cur = ""
        cur += piece + sep
    if cur.strip():
        chunks.append(cur.strip())
    return [c for c in chunks if _HAS_WORD.search(c)]


def load_lexicon(path: str) -> list[tuple[re.Pattern, str]]:
    """Read 'word = replacement' lines (# for comments) into case-insensitive substitutions."""
    rules = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if "=" not in line:
                continue
            word, say = (s.strip() for s in line.split("=", 1))
            if word:
                rules.append((re.compile(rf"(?<!\w){re.escape(word)}(?!\w)", re.IGNORECASE), say))
    return rules


def apply_lexicon(text: str, rules) -> str:
    for pattern, say in rules:
        text = pattern.sub(say, text)
    return text


def normalize_title(s: str) -> str:
    return re.sub(r"[^\w]+", " ", s.lower()).strip()
