from dataclasses import dataclass, field


@dataclass
class Chapter:
    title: str
    text: str  # paragraphs separated by blank lines


@dataclass
class Book:
    title: str
    author: str
    chapters: list[Chapter] = field(default_factory=list)
    cover: bytes | None = None
    cover_mime: str | None = None  # "image/jpeg" or "image/png"
