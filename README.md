# readtome

Turns a **PDF or EPUB** into an audiobook with real chapters, using Microsoft's free
neural voices (via [edge-tts](https://github.com/rany2/edge-tts)). Needs an internet
connection while speaking; no GPU, no account, no API key.

Every run produces two things in `audiobooks/`:

| Output | What it is | Plays on |
|---|---|---|
| `Book Title.m4b` | One file, chapter markers, cover art, tagged as an audiobook | iPhone/iPad (Apple Books), Mac, Android audiobook apps (Smart AudioBook Player, Voice, BookPlayer on iOS), VLC, foobar2000, Plex/Audiobookshelf |
| `Book Title/` | One numbered MP3 per chapter + `playlist.m3u`, with title/track/cover tags | Literally anything: any phone, Windows, car stereos, old MP3 players, smart speakers, USB sticks |

Use `--format m4b` or `--format mp3` if you only want one.

## Setup (once)

Already done in this folder. To set it up somewhere else:

```bash
py -3.12 -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e .
```

(On macOS/Linux use `python3 -m venv .venv` and `.venv/bin/...`.) ffmpeg is bundled
through `imageio-ffmpeg`; a system ffmpeg is used instead if one is on your PATH.

## Use it

Easiest on Windows: **drag a .pdf or .epub onto `readtome.bat`.**

From a terminal:

```bash
.venv/Scripts/readtome "My Book.epub" --list
```

```bash
.venv/Scripts/readtome "My Book.epub"
```

### Choosing your narrator

```bash
.venv/Scripts/readtome "My Book.epub" --try-voices
```

This records the opening of your book in 16 good narrators (US, British, Australian,
Irish; male and female) into `audiobooks/voice-samples/`. Listen, pick one, then
convert with `--voice en-GB-RyanNeural` (or whichever). Variations:
`--try-voices en-GB` (every British voice), `--try-voices "en-US-AvaNeural,en-GB-RyanNeural"`,
or no book at all for a stock passage. Add `--speed 1.2` to hear it at your reading speed.

### Checking chapters

Always run `--list` first. It shows the chapters it found, how long each will be, and
which ones it will skip (contents, copyright, tiny pages). Then:

- `--chapters 1-3` – try a few chapters first to check the voice and the text cleanup
- `--chapters 3-25` – exactly which chapters to include (numbers from `--list`)
- `--speed 1.2` – faster or slower reading
- `--voice en-GB-RyanNeural` – pick another voice; `--list-voices` shows English ones, `--list-voices all` everything
- `--export-text` – also saves the cleaned text of each chapter, so you can see what will be read
- `--lexicon names.txt` – pronunciation fixes, one `word = how to say it` per line
- `--title` / `--author` – fix bad metadata
- `--toc-level 2` – PDFs whose outline has parts at level 1 and chapters at level 2

Speech is cached in `audiobooks/.work/`, so if a run is interrupted (or you fix a
pronunciation), running the same command again only renders what's missing.
Delete `.work` when you're happy with the result.

## Getting it onto your devices

- **iPhone:** AirDrop or Finder/iTunes sync the `.m4b`, or save it to Files and open in Apple Books. BookPlayer (free) also handles it well.
- **Android:** copy the `.m4b` (or the MP3 folder) to the phone and open it in Smart AudioBook Player or Voice. Any music app will play the MP3 folder.
- **Computer:** double-click either; VLC shows the M4B chapters.
- **Car / old player / USB stick:** copy the MP3 folder. Files are numbered so they play in order.
- **Everywhere at once:** drop the files into Audiobookshelf or Plex, or a cloud drive.

If a player refuses `.m4b`, rename it to `.m4a`; it's the same format.

## How it works

1. **Read** – EPUB chapters come from the book's table of contents (including several
   chapters inside one file); footnotes and page-break markers are dropped. PDF chapters
   come from the PDF outline, or from "Chapter X"/large headings if there isn't one;
   running headers, footers and page numbers are removed, and hyphenated words and
   paragraphs split across pages are rejoined.
2. **Chunk** – text is split at paragraph and sentence boundaries into ~2,500-character pieces.
3. **Speak** – pieces are sent to edge-tts, 4 at a time, with retries.
4. **Package** – ffmpeg joins pieces into chapters, then builds the M4B (AAC, 64 kbps
   mono, chapter markers) and the MP3 folder (44.1 kHz, 64 kbps); mutagen writes tags and cover art.

Scanned PDFs (images of pages) have no text to read; OCR them first, e.g. with `ocrmypdf`.

Code: `readtome/epub_reader.py`, `readtome/pdf_reader.py`, `readtome/text.py`,
`readtome/tts.py`, `readtome/package.py`, `readtome/cli.py`.
