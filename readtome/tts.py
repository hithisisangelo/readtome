"""Speech synthesis with Microsoft's free neural voices via edge-tts.

Each chunk is cached under a hash of (voice, rate, text), so an interrupted run picks up
where it stopped and re-running after a text fix only re-renders what changed."""

import asyncio
import hashlib
import os
import random
import sys
from pathlib import Path

import edge_tts
from edge_tts.exceptions import NoAudioReceived

DEFAULT_VOICE = "en-US-AndrewNeural"


def chunk_file(cache_dir: Path, voice: str, rate: str, text: str) -> Path:
    digest = hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()
    return cache_dir / f"{digest}.mp3"


async def _synth(text, voice, rate, out: Path, sem, retries=6) -> bool:
    async with sem:
        tmp = out.with_suffix(".part")
        for attempt in range(retries):
            try:
                await edge_tts.Communicate(text, voice, rate=rate).save(str(tmp))
                if tmp.stat().st_size == 0:
                    raise NoAudioReceived("empty audio")
                os.replace(tmp, out)
                return True
            except NoAudioReceived:
                if attempt == retries - 1:
                    print(f"\n  warning: no audio for chunk starting {text[:60]!r}; skipped", file=sys.stderr)
                    return False
            except Exception:
                if attempt == retries - 1:
                    raise
            await asyncio.sleep(min(30, 2 ** attempt) + random.random())
        return False


async def _synth_all(jobs, voice, rate, concurrency):
    sem = asyncio.Semaphore(concurrency)
    total, done = len(jobs), 0

    async def run(text, out):
        nonlocal done
        ok = await _synth(text, voice, rate, out, sem)
        done += 1
        print(f"\r  speaking chunk {done}/{total}", end="", flush=True)
        return ok

    results = await asyncio.gather(*(run(t, p) for t, p in jobs))
    if total:
        print()
    return results


def synthesize(jobs: list[tuple[str, Path]], voice: str, rate: str, concurrency: int = 4):
    """Render every (text, path) job whose path doesn't exist yet."""
    todo = [(t, p) for t, p in jobs if not p.exists()]
    cached = len(jobs) - len(todo)
    if cached:
        print(f"  {cached} chunk(s) already rendered, reusing them")
    asyncio.run(_synth_all(todo, voice, rate, concurrency))


def _voices(lang: str) -> list[dict]:
    lang = lang.lower()
    voices = asyncio.run(edge_tts.list_voices())
    return [v for v in sorted(voices, key=lambda v: v["ShortName"])
            if lang == "all" or v["Locale"].lower().startswith(lang)]


def list_voices(lang: str = "en"):
    for v in _voices(lang):
        print(f"{v['ShortName']:40} {v['Gender']:7} {v['Locale']}")


# Voices that hold up well over hours of narration.
NARRATORS = [
    "en-US-AndrewNeural", "en-US-BrianNeural", "en-US-ChristopherNeural", "en-US-GuyNeural",
    "en-US-AvaNeural", "en-US-EmmaNeural", "en-US-AriaNeural", "en-US-JennyNeural",
    "en-GB-RyanNeural", "en-GB-ThomasNeural", "en-GB-SoniaNeural", "en-GB-LibbyNeural",
    "en-AU-WilliamMultilingualNeural", "en-AU-NatashaNeural", "en-IE-ConnorNeural", "en-IE-EmilyNeural",
]


def resolve_voices(spec: str) -> list[str]:
    """'' -> the NARRATORS shortlist; 'en-GB' -> every voice for that locale; else a comma list."""
    if not spec:
        return NARRATORS
    if "Neural" in spec:
        return [v.strip() for v in spec.split(",") if v.strip()]
    return [v["ShortName"] for v in _voices(spec)]


def sample_voices(voices: list[str], text: str, rate: str, out_dir: Path, concurrency: int = 4) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    paths = [out_dir / f"{v}.mp3" for v in voices]
    for p in paths:
        p.unlink(missing_ok=True)

    async def run():
        return await asyncio.gather(*(_synth(text, v, rate, p, sem) for v, p in zip(voices, paths)))

    asyncio.run(run())
    return [p for p in paths if p.exists()]
