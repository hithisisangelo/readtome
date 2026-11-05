"""Turn rendered chunks into players-ready files: an M4B audiobook with chapter markers
and cover art, and a folder of tagged, numbered MP3s that plays on anything."""

import re
import shutil
import subprocess
from pathlib import Path

from mutagen.id3 import APIC, ID3, TALB, TCON, TIT2, TPE1, TPE2, TRCK
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from .model import Book


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _ffmpeg(*args):
    subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)


def safe_name(s: str, limit: int = 80) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s).strip().rstrip(".")
    return (s[:limit].rstrip() or "untitled")


def _concat_list(files: list[Path], list_path: Path):
    with open(list_path, "w", encoding="utf-8") as f:
        for p in files:
            path = p.resolve().as_posix().replace("'", r"'\''")
            f.write(f"file '{path}'\n")


def join_chunks(chunks: list[Path], out: Path):
    """Losslessly concatenate one chapter's chunk MP3s."""
    lst = out.with_suffix(".txt")
    _concat_list(chunks, lst)
    _ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out)
    lst.unlink()


def duration(path: Path) -> float:
    return MP3(path).info.length


def write_mp3_folder(book: Book, chapter_files: list[tuple[str, Path]], out_dir: Path, bitrate: str) -> Path:
    """Numbered MP3 per chapter at 44.1 kHz (plays on old car stereos and MP3 players too)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(chapter_files)
    width = max(2, len(str(total)))
    written = []
    for n, (title, src) in enumerate(chapter_files, 1):
        dst = out_dir / f"{n:0{width}d} - {safe_name(title, 60)}.mp3"
        _ffmpeg("-i", src, "-ar", 44100, "-ac", 1, "-c:a", "libmp3lame", "-b:a", bitrate, dst)
        tags = ID3()
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TALB(encoding=3, text=book.title))
        tags.add(TPE1(encoding=3, text=book.author))
        tags.add(TPE2(encoding=3, text=book.author))
        tags.add(TRCK(encoding=3, text=f"{n}/{total}"))
        tags.add(TCON(encoding=3, text="Audiobook"))
        if book.cover:
            tags.add(APIC(encoding=3, mime=book.cover_mime, type=3, desc="Cover", data=book.cover))
        tags.save(dst, v2_version=3)
        written.append(dst.name)
    (out_dir / "playlist.m3u").write_text("\n".join(written) + "\n", encoding="utf-8")
    return out_dir


def _meta_escape(s: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", s)


def write_m4b(book: Book, chapter_files: list[tuple[str, Path]], out_path: Path, bitrate: str) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.with_suffix(".work")
    work.mkdir(exist_ok=True)

    meta = [";FFMETADATA1", f"title={_meta_escape(book.title)}", f"artist={_meta_escape(book.author)}",
            f"album={_meta_escape(book.title)}", "genre=Audiobook"]
    start = 0
    for title, path in chapter_files:
        end = start + round(duration(path) * 1000)
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={_meta_escape(title)}"]
        start = end
    meta_file, list_file = work / "chapters.txt", work / "files.txt"
    meta_file.write_text("\n".join(meta) + "\n", encoding="utf-8")
    _concat_list([p for _, p in chapter_files], list_file)

    tmp = work / "book.m4b"
    _ffmpeg("-f", "concat", "-safe", "0", "-i", list_file, "-i", meta_file,
            "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
            "-c:a", "aac", "-b:a", bitrate, "-ar", 44100, "-ac", 1,
            "-movflags", "+faststart", "-f", "ipod", tmp)

    tags = MP4(tmp)
    tags["\xa9nam"] = [book.title]
    tags["\xa9alb"] = [book.title]
    tags["\xa9ART"] = [book.author]
    tags["aART"] = [book.author]
    tags["\xa9gen"] = ["Audiobook"]
    tags["stik"] = [2]  # media kind: audiobook
    if book.cover:
        fmt = MP4Cover.FORMAT_PNG if book.cover_mime == "image/png" else MP4Cover.FORMAT_JPEG
        tags["covr"] = [MP4Cover(book.cover, imageformat=fmt)]
    tags.save()

    shutil.move(tmp, out_path)
    shutil.rmtree(work, ignore_errors=True)
    return out_path
