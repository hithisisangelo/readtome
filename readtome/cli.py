import argparse
import re
import sys
from pathlib import Path

from . import package, text, tts
from .model import Book, Chapter

_SKIP_TITLES = re.compile(
    r"\s*(table of contents|contents|copyright( page)?|index|cover|title page|half title|"
    r"also by .*|other books by .*|about the publisher|dedication)\s*", re.IGNORECASE)


def load_book(path: Path, toc_level: int | None) -> Book:
    ext = path.suffix.lower()
    if ext == ".epub":
        from .epub_reader import load_epub
        return load_epub(str(path))
    if ext == ".pdf":
        from .pdf_reader import load_pdf
        return load_pdf(str(path), toc_level)
    raise SystemExit(f"Unsupported file type {ext!r}: give me a .pdf or .epub")


def tidy_chapters(book: Book) -> None:
    """Normalize text, name untitled chapters, and make sure each starts by announcing its title."""
    book.chapters = [ch for ch in book.chapters if text.paragraphs(ch.text)]
    for n, ch in enumerate(book.chapters, 1):
        paras = text.paragraphs(ch.text)
        ch.title = " ".join(ch.title.split()) or (paras[0][:60] if paras and len(paras[0]) < 60 else f"Section {n}")
        title = text.normalize_title(ch.title)
        head = text.normalize_title(" ".join(paras[:4]))[:len(title) + 40]
        first = text.normalize_title(paras[0]) if paras else ""
        announced = title in head or (len(first) > 3 and title.startswith(first))
        if paras and not announced:
            paras.insert(0, ch.title + ".")
        ch.text = text.join_paragraphs(paras)


def parse_selection(spec: str, count: int) -> list[int]:
    picked = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        lo, _, hi = part.partition("-")
        lo = int(lo)
        hi = int(hi) if hi else (count if part.endswith("-") else lo)
        picked.extend(range(lo, hi + 1))
    bad = [n for n in picked if not 1 <= n <= count]
    if bad:
        raise SystemExit(f"Chapter numbers out of range (1-{count}): {bad}")
    return sorted(set(picked))


def auto_skip_reason(ch: Chapter, min_chars: int) -> str | None:
    if _SKIP_TITLES.fullmatch(ch.title):
        return "front/back matter"
    if len(ch.text) < 20000 and re.search(r"all rights reserved|\bISBN\b", ch.text, re.IGNORECASE):
        return "copyright page"
    if len(ch.text) < min_chars:
        return f"only {len(ch.text)} characters"
    return None


SAMPLE_TEXT = ("Chapter One. The keeper climbed the stairs every evening at dusk, counting each of "
               "the one hundred and twelve steps. Nobody had asked him to count them. \"Somebody has "
               "to,\" he would say, if anyone ever asked, which they never did.")


def sample_from(chapters: list[Chapter], target: int = 400) -> str:
    """Roughly the first `target` characters of the book's first real chapter, cut at a sentence."""
    paras = text.paragraphs(chapters[0].text) if chapters else []
    sample = ""
    for sent in re.split(r"(?<=[.!?])\s+", " ".join(paras)):
        if sample and len(sample) + len(sent) > target:
            break
        sample = f"{sample} {sent}".strip()
    return sample or SAMPLE_TEXT


def try_voices(args, sample: str) -> int:
    voices = tts.resolve_voices(args.try_voices)
    if not voices:
        raise SystemExit(f"No voices match {args.try_voices!r}; see --list-voices all")
    out_dir = Path(args.output) / "voice-samples"
    rate = f"{round((args.speed - 1) * 100):+d}%"
    print(f"Recording a sample in {len(voices)} voice(s):\n  \"{sample[:120]}...\"")
    made = tts.sample_voices(voices, sample, rate, out_dir, args.jobs)
    print(f"\nListen to them in {out_dir.resolve()}")
    for p in made:
        print(f"  {p.name}")
    print('\nThen convert with the one you like, e.g.:  readtome book.epub --voice "' + made[0].stem + '"'
          if made else "No samples were produced.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="readtome",
        description="Turn a PDF or EPUB into a chaptered audiobook (M4B) and/or a folder of MP3s.")
    p.add_argument("book", nargs="?", help="path to a .pdf or .epub")
    p.add_argument("-o", "--output", default="audiobooks", help="output folder (default: ./audiobooks)")
    p.add_argument("-f", "--format", choices=["both", "m4b", "mp3"], default="both",
                   help="m4b = one audiobook file with chapters; mp3 = one file per chapter; default both")
    p.add_argument("-v", "--voice", default=tts.DEFAULT_VOICE, help=f"voice name (default {tts.DEFAULT_VOICE})")
    p.add_argument("-s", "--speed", type=float, default=1.0, help="reading speed, e.g. 1.15 or 0.9")
    p.add_argument("-l", "--list", action="store_true", help="show the detected chapters and stop")
    p.add_argument("-c", "--chapters", help='only these chapters, using numbers from --list, e.g. "1-3,7" or "5-"')
    p.add_argument("--list-voices", nargs="?", const="en", metavar="LANG",
                   help='list voices for a language prefix (default "en"; "all" for every voice)')
    p.add_argument("--try-voices", nargs="?", const="", metavar="VOICES",
                   help="record a short sample in several narrators so you can pick one: no value = a "
                        "shortlist of good narrators, 'en-GB' = every voice for that accent, or a comma "
                        "list of voice names. With a book, the sample is read from the book itself.")
    p.add_argument("--export-text", action="store_true", help="also save each chapter's cleaned text as .txt")
    p.add_argument("--lexicon", help="text file of 'word = how to say it' pronunciation fixes")
    p.add_argument("--title", help="override the book title")
    p.add_argument("--author", help="override the author")
    p.add_argument("--min-chars", type=int, default=300, help="auto-skip chapters shorter than this (default 300)")
    p.add_argument("--keep-all", action="store_true", help="don't auto-skip anything")
    p.add_argument("--toc-level", type=int, help="PDF only: which outline level counts as a chapter")
    p.add_argument("--bitrate", default="64k", help="audio bitrate (default 64k, plenty for speech)")
    p.add_argument("-j", "--jobs", type=int, default=4, help="chunks to synthesize at once (default 4)")
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")  # book titles with odd characters on a Windows console
    args = build_parser().parse_args(argv)
    if args.list_voices:
        tts.list_voices(args.list_voices)
        return 0
    if args.try_voices is not None and not args.book:
        return try_voices(args, SAMPLE_TEXT)
    if not args.book:
        build_parser().print_help()
        return 1

    src = Path(args.book)
    if not src.is_file():
        raise SystemExit(f"File not found: {src}")

    print(f"Reading {src.name} ...")
    book = load_book(src, args.toc_level)
    book.title = args.title or book.title or src.stem
    book.author = args.author or book.author or "Unknown"
    tidy_chapters(book)
    if not book.chapters:
        raise SystemExit("No readable text found in this book.")

    chosen = set(parse_selection(args.chapters, len(book.chapters))) if args.chapters else None
    selected: list[Chapter] = []
    print(f"\n{book.title} by {book.author}: {len(book.chapters)} chapter(s) found\n")
    for n, ch in enumerate(book.chapters, 1):
        reason = None if args.keep_all else auto_skip_reason(ch, args.min_chars)
        keep = (n in chosen) if chosen is not None else reason is None
        mins = len(ch.text.split()) / 155  # rough speaking pace, words per minute
        note = "" if keep else f"  (skipped: {reason or 'not selected'})"
        print(f"  {'*' if keep else ' '} {n:3}. {ch.title[:60]:60} ~{mins:5.1f} min{note}")
        if keep:
            selected.append(ch)
    print()
    if args.try_voices is not None:
        return try_voices(args, sample_from(selected or book.chapters))
    if args.list:
        print("* = will be included. Use --chapters to pick exactly which ones.")
        return 0
    if not selected:
        raise SystemExit("Nothing selected to read.")

    out_root = Path(args.output)
    stem = package.safe_name(book.title)
    work = out_root / ".work" / stem
    cache = work / "chunks"
    cache.mkdir(parents=True, exist_ok=True)

    lexicon = text.load_lexicon(args.lexicon) if args.lexicon else []
    rate = f"{round((args.speed - 1) * 100):+d}%"

    if args.export_text:
        txt_dir = out_root / f"{stem} (text)"
        txt_dir.mkdir(parents=True, exist_ok=True)
        for n, ch in enumerate(selected, 1):
            (txt_dir / f"{n:02d} - {package.safe_name(ch.title, 60)}.txt").write_text(ch.text, encoding="utf-8")
        print(f"Chapter text saved to {txt_dir}")

    plan = []  # (title, [chunk paths])
    jobs = []
    for ch in selected:
        chunks = text.chunk(text.apply_lexicon(ch.text, lexicon))
        paths = [tts.chunk_file(cache, args.voice, rate, c) for c in chunks]
        plan.append((ch.title, paths))
        jobs += list(zip(chunks, paths))

    print(f"Synthesizing {len(selected)} chapter(s) with {args.voice} at speed {args.speed}:")
    tts.synthesize(jobs, args.voice, rate, args.jobs)

    print("Assembling chapters ...")
    chapter_files = []
    for n, (title, paths) in enumerate(plan, 1):
        paths = [p for p in paths if p.exists()]
        if not paths:
            print(f"  warning: chapter {title!r} produced no audio; leaving it out", file=sys.stderr)
            continue
        out = work / f"chapter{n:04d}.mp3"
        package.join_chunks(paths, out)
        chapter_files.append((title, out))

    made = []
    if args.format in ("both", "m4b"):
        print("Building M4B audiobook ...")
        made.append(package.write_m4b(book, chapter_files, out_root / f"{stem}.m4b", args.bitrate))
    if args.format in ("both", "mp3"):
        print("Building MP3 folder ...")
        made.append(package.write_mp3_folder(book, chapter_files, out_root / stem, args.bitrate))

    total = sum(package.duration(p) for _, p in chapter_files)
    print(f"\nDone: {len(chapter_files)} chapters, {total / 3600:.1f} hours.")
    for m in made:
        print(f"  {m.resolve()}")
    print(f"(Rendered speech is cached in {work.resolve()}; delete it once you're happy.)")
    return 0
