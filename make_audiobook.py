#!/usr/bin/env python3
"""Build an audiobook (full MP3 + chapters) from a section of README.md.

Uses the free neural Russian voice of Microsoft Edge TTS (ru-RU-SvetlanaNeural).
Code blocks and tables are skipped; markdown is cleaned for speech.

Run from the project root:
    python3 make_audiobook.py --part intro
    python3 make_audiobook.py --part part0
    ...
    python3 make_audiobook.py --start 91 --end 399 --title "..." --name Custom

Requires: python3, ffmpeg, internet (for edge-tts). edge-tts is installed
automatically into .venv-tts next to this script if not found.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "README.md"
OUT_DIR = BASE / "audiobook"
WORK_ROOT = OUT_DIR / ".work"
VENV_DIR = BASE / ".venv-tts"
DEFAULT_VOICE = "ru-RU-SvetlanaNeural"
DEFAULT_RATE = "+8%"

PRESETS = {
    "intro": (
        91, 399,
        "Книга. Harness Engineering. Введение. Полный курс на русском.",
        "Harness_Engineering_Введение",
    ),
    "part0": (
        403, 715,
        "Книга. Harness Engineering. Часть 0. Теоретическая база.",
        "Harness_Engineering_Часть_0",
    ),
    "part1": (
        717, 971,
        "Книга. Harness Engineering. Часть 1. Фундамент.",
        "Harness_Engineering_Часть_1",
    ),
    "part2": (
        973, 1131,
        "Книга. Harness Engineering. Часть 2. Состояние и время.",
        "Harness_Engineering_Часть_2",
    ),
    "part3": (
        1133, 1310,
        "Книга. Harness Engineering. Часть 3. Скоуп и дисциплина.",
        "Harness_Engineering_Часть_3",
    ),
    "part4": (
        1312, 1549,
        "Книга. Harness Engineering. Часть 4. Верификация.",
        "Harness_Engineering_Часть_4",
    ),
    "part5": (
        1551, 1758,
        "Книга. Harness Engineering. Часть 5. Эксплуатация.",
        "Harness_Engineering_Часть_5",
    ),
    "part6": (
        1760, 2130,
        "Книга. Harness Engineering. Часть 6. Автономия.",
        "Harness_Engineering_Часть_6",
    ),
}


def find_edge_tts():
    env = os.environ.get("EDGE_TTS")
    if env and Path(env).is_file():
        return str(env)
    found = shutil.which("edge-tts")
    if found:
        return found
    venv_bin = VENV_DIR / "bin" / "edge-tts"
    if venv_bin.is_file():
        return str(venv_bin)
    print("edge-tts not found, creating venv at .venv-tts ...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    pip = VENV_DIR / "bin" / "pip"
    subprocess.run([str(pip), "install", "-q", "edge-tts"], check=True)
    return str(venv_bin)


def clean_line(line, skip_h1):
    s = line.rstrip()
    m = re.match(r"^(#{1,4})\s+(.*)$", s)
    if m:
        level = len(m.group(1))
        title = m.group(2).strip().replace("`", "")
        title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", title)
        title = title.replace("*", "").replace("_", "")
        title = re.sub(r"[ \t]+", " ", title).strip()
        if level == 1 and skip_h1:
            return None
        label = {1: "Книга", 2: "Глава", 3: "Раздел", 4: "Подраздел"}.get(level, "Раздел")
        return f"{label}. {title}"
    if re.match(r"^\s*-{3,}\s*$", s):
        return None
    if s.lstrip().startswith("|"):
        return None
    s = s.replace("`", "")
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = s.replace("**", "").replace("__", "")
    s = s.replace("*", "")
    s = re.sub(r"(?<=\w)_(?=\w)", " ", s)
    s = s.replace("_", "")
    s = re.sub(r"\s*→\s*", " затем ", s)
    s = re.sub(r"^\s*[-*]\s+", "", s)
    s = re.sub(r"^\s*(\d+)\.\s+", r"\1. ", s)
    s = re.sub(r"[ \t]+", " ", s)
    out = []
    for ch in s:
        if ord(ch) < 0x20:
            continue
        out.append(ch)
    s = "".join(out).strip()
    return s if s else None


def extract(start, end, custom_title):
    with open(SRC, encoding="utf-8") as f:
        raw = f.read().splitlines()
    lines = raw[start - 1:end]
    out_lines = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.lstrip().startswith("|"):
            continue
        cl = clean_line(line, skip_h1=bool(custom_title))
        if cl is not None:
            out_lines.append(cl)
    collapsed = []
    for l in out_lines:
        if l == "" and collapsed and collapsed[-1] == "":
            continue
        collapsed.append(l)
    if custom_title:
        full = (custom_title + "\n\n" + "\n".join(collapsed)).strip()
    else:
        full = "\n".join(collapsed).strip()
    return full, collapsed


def split_chapters(collapsed):
    chapters = []
    current = []
    for l in collapsed:
        if l.startswith("Глава. "):
            if current:
                chapters.append(current)
            current = [l]
        else:
            current.append(l)
    if current:
        chapters.append(current)
    return chapters


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr)
        sys.exit(1)
    return r


def run_tts(tts, voice, rate, txt, out, timeout=240, retries=2):
    cmd = [tts, "--voice", voice, "--rate", rate, "--file", str(txt),
           "--write-media", str(out)]
    for attempt in range(1, retries + 2):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and out.is_file() and out.stat().st_size > 0:
                return
            print(f"  attempt {attempt}: edge-tts exit={r.returncode}", flush=True)
        except subprocess.TimeoutExpired:
            print(f"  attempt {attempt}: edge-tts timed out", flush=True)
        out.unlink(missing_ok=True)
    sys.exit(f"edge-tts failed for {txt}")


def split_tts_chunks(text, limit=2000):
    lines = [l for l in text.split("\n") if l.strip()]
    chunks = []
    cur, cur_len = [], 0
    for line in lines:
        if len(line) > limit:
            if cur:
                chunks.append("\n".join(cur))
                cur, cur_len = [], 0
            buf = ""
            for part in re.split(r"(?<=[.!?])\s+", line):
                if buf and len(buf) + len(part) + 1 > limit:
                    chunks.append(buf)
                    buf = part
                else:
                    buf = f"{buf} {part}" if buf else part
            if buf:
                chunks.append(buf)
        elif cur_len + len(line) + 1 > limit:
            chunks.append("\n".join(cur))
            cur, cur_len = [line], len(line)
        else:
            cur.append(line)
            cur_len += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def slug_name(t):
    t = t.strip()
    if t.startswith("Harness Engineering."):
        t = "Вступление"
    t = re.sub(r"[«»\"]", "", t)
    t = re.sub(r"\W+", "_", t)
    return t.strip("_")


def part_label(base_name):
    label = re.sub(r"^Harness_Engineering_", "", base_name)
    return label.replace("_", "")


def build(start, end, custom_title, base_name, voice, rate, tts):
    section_dir = WORK_ROOT / base_name
    for sub in ("chapters", "tts", "wavs"):
        (section_dir / sub).mkdir(parents=True, exist_ok=True)

    full, collapsed = extract(start, end, custom_title)
    (section_dir / "full.txt").write_text(full, encoding="utf-8")
    chapters = split_chapters(collapsed)
    print(f"chars: {len(full)}, chapters: {len(chapters)}")

    for i, ch in enumerate(chapters, 1):
        (section_dir / "chapters" / f"ch_{i:02d}.txt").write_text(
            "\n".join(ch).strip(), encoding="utf-8")

    durations = []
    for i in range(1, len(chapters) + 1):
        chapter_text = (section_dir / "chapters" / f"ch_{i:02d}.txt").read_text(
            encoding="utf-8")
        chunks = split_tts_chunks(chapter_text)
        chunk_wavs = []
        for ci, ctext in enumerate(chunks):
            ctxt = section_dir / "chapters" / f"ch_{i:02d}_p{ci:02d}.txt"
            cm3 = section_dir / "tts" / f"ch_{i:02d}_p{ci:02d}.mp3"
            cwv = section_dir / "wavs" / f"ch_{i:02d}_p{ci:02d}.wav"
            ctxt.write_text(ctext, encoding="utf-8")
            run_tts(tts, voice, rate, ctxt, cm3)
            run(["ffmpeg", "-y", "-i", str(cm3), "-ar", "44100", "-ac", "2", str(cwv)])
            chunk_wavs.append(cwv)
            print(f"  ch_{i:02d} part {ci + 1}/{len(chunks)}: {len(ctext)} chars", flush=True)
        ch_wav = section_dir / "wavs" / f"ch_{i:02d}.wav"
        if len(chunk_wavs) == 1:
            shutil.copy(chunk_wavs[0], ch_wav)
        else:
            concat_list = section_dir / f"ch_{i:02d}.concat.txt"
            concat_list.write_text(
                "".join(f"file 'wavs/{w.name}'\n" for w in chunk_wavs), encoding="utf-8")
            run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(concat_list), "-ar", "44100", "-ac", "2", str(ch_wav)])
        r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(ch_wav)])
        durations.append(float(r.stdout.strip()))
        print(f"  ch_{i:02d}: {durations[-1]:.2f} s", flush=True)

    (section_dir / "concat.txt").write_text(
        "".join(f"file 'wavs/ch_{i:02d}.wav'\n" for i in range(1, len(chapters) + 1)),
        encoding="utf-8")

    chapter_names = []
    for i, ch in enumerate(chapters, 1):
        if i == 1 and custom_title and not ch[0].startswith("Глава. "):
            title = custom_title.replace("Книга. ", "", 1)
        else:
            title = ch[0].replace("Глава. ", "").strip()
        chapter_names.append(slug_name(title))

    total = sum(durations)
    full_mp3 = section_dir / "full.mp3"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i",
         str(section_dir / "concat.txt"), "-c:a", "libmp3lame", "-b:a", "192k",
         "-ar", "44100", str(full_mp3)])

    OUT_DIR.mkdir(exist_ok=True)
    chapters_dir = OUT_DIR / "chapters"
    chapters_dir.mkdir(exist_ok=True)
    shutil.copy(full_mp3, OUT_DIR / f"{base_name}.mp3")
    label = part_label(base_name)
    for i in range(1, len(chapters) + 1):
        ch_mp3 = section_dir / "tts" / f"ch_{i:02d}_chapter.mp3"
        run(["ffmpeg", "-y", "-i", str(section_dir / "wavs" / f"ch_{i:02d}.wav"),
             "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100", str(ch_mp3)])
        shutil.copy(ch_mp3, chapters_dir / f"{label}_{chapter_names[i - 1]}.mp3")
    print(f"total: {total:.1f} s -> {OUT_DIR}/{base_name}.mp3")


def main():
    ap = argparse.ArgumentParser(description="Build an audiobook from README.md")
    ap.add_argument("--part", choices=sorted(PRESETS),
                    help="named section (intro, part0..part6)")
    ap.add_argument("--start", type=int, help="first line of section (1-based)")
    ap.add_argument("--end", type=int, help="last line of section (1-based)")
    ap.add_argument("--title", help="opening line spoken before the section")
    ap.add_argument("--name", help="output file base name, e.g. Harness_Engineering_Часть_1")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--rate", default=DEFAULT_RATE)
    args = ap.parse_args()

    if args.part:
        start, end, title, name = PRESETS[args.part]
    elif args.start and args.end:
        start, end = args.start, args.end
        title = args.title or ""
        name = args.name or f"section_{start:03d}"
    else:
        ap.error("specify --part or --start/--end")

    build(start, end, title, name, args.voice, args.rate, find_edge_tts())


if __name__ == "__main__":
    main()
