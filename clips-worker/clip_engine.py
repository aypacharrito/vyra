"""Local video processing; API used only for speech transcription and clip selection.

Never sends source video frames to OpenAI. Only extracted compressed audio
and segment timestamps/transcript are submitted. No publishing is performed.
"""
from __future__ import annotations
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from openai import OpenAI

Progress = Callable[[str, int], None]


def command(args: list[str]):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {args[0]}: {result.stderr[-1400:]}")
    return result.stdout


def probe(path: Path) -> dict:
    info = json.loads(command(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)]))
    duration = float(info.get("format", {}).get("duration", 0))
    videos = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    if not videos or duration <= 0:
        raise ValueError("Your file needs a playable video stream and a positive duration.")
    if duration > 5 * 3600:
        raise ValueError("Starter supports up to 5 hours of footage per upload.")
    return {"duration": duration, "width": int(videos[0].get("width", 0)), "height": int(videos[0].get("height", 0))}


def time_ass(seconds: float) -> str:
    total_centis = max(0, round(seconds * 100))
    h, rem = divmod(total_centis, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def safe_text(text: str) -> str:
    # ASS subtitles interpret braces, backslashes and line breaks as syntax.
    return re.sub(r"[\\{}\r\n]", "", text).replace("\u200b", "").strip()


def subtitles_ass(words: list[dict], clip_start: float, clip_end: float, path: Path):
    header = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\nScaledBorderAndShadow: yes\n\n"
              "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
              "Style: Pop,Arial,62,&H00FFFFFF,&H0000FFFF,&H00141414,&H9B000000,-1,0,0,0,100,100,0,0,1,5,1,2,52,52,260,1\n\n"
              "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    relevant = [w for w in words if w["end"] > clip_start and w["start"] < clip_end]
    lines = []
    group: list[dict] = []
    def emit():
        if not group:
            return
        # Highlight the spoken word using the actual transcription timestamps.
        # Escape each word before adding ASS tags; transcript text is never syntax.
        for index, word in enumerate(group):
            begin = max(0.0, word["start"] - clip_start)
            next_start = group[index + 1]["start"] if index + 1 < len(group) else word["end"] + .15
            end = min(clip_end - clip_start, next_start - clip_start)
            caption = " ".join(
                (r"{\c&H00D9F579&}" + safe_text(w["word"]) + r"{\c&H00FFFFFF&}")
                if i == index else safe_text(w["word"])
                for i, w in enumerate(group)
            )
            if caption and end > begin:
                lines.append(f"Dialogue: 0,{time_ass(begin)},{time_ass(end)},Pop,,0,0,0,,{caption}")
    for w in relevant:
        if group and (len(group) >= 5 or w["start"] - group[-1]["end"] > .55 or len(" ".join(x["word"] for x in group)) > 32):
            emit()
            group = []
        group.append(w)
    emit()
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8-sig")


def transcription_chunks(source: Path, scratch: Path, duration: float, client: OpenAI, progress: Progress) -> tuple[list[dict], str]:
    words: list[dict] = []
    seconds_per_chunk = 480
    count = math.ceil(duration / seconds_per_chunk)
    for i in range(count):
        offset = i * seconds_per_chunk
        take = min(seconds_per_chunk, duration - offset)
        audio_path = scratch / f"audio_{i:03d}.mp3"
        command(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{offset:.3f}", "-i", str(source), "-t", f"{take:.3f}", "-vn", "-ac", "1", "-ar", "16000", "-codec:a", "libmp3lame", "-b:a", "48k", str(audio_path)])
        if audio_path.stat().st_size < 1024:
            raise ValueError("No useful audio detected; the first version requires spoken audio.")
        with audio_path.open("rb") as f:
            result = client.audio.transcriptions.create(file=f, model="whisper-1", response_format="verbose_json", timestamp_granularities=["word"])
        for word in (result.words or []):
            w = word.model_dump() if hasattr(word, "model_dump") else dict(word)
            if not w.get("word") or w.get("start") is None or w.get("end") is None:
                continue
            words.append({"start": float(w["start"]) + offset, "end": float(w["end"]) + offset, "word": str(w["word"]).strip()})
        audio_path.unlink(missing_ok=True)
        progress(f"Transcribed segment {i+1}/{count}", int(10 + 43 * (i+1) / count))
    if not words:
        raise ValueError("No spoken words found. This starter detects moments from speech; add vision/highlight detection later.")
    return words, " ".join(w["word"] for w in words)


def groups(words: list[dict]) -> list[dict]:
    """Readable ~9-second spans with accurate absolute timestamps."""
    out = []
    g = []
    def emit():
        if g:
            out.append({"start": round(g[0]["start"], 1), "end": round(g[-1]["end"], 1), "text": " ".join(w["word"] for w in g)[:1000]})
    for w in words:
        if g and (w["start"] - g[0]["start"] >= 9 or len(g) >= 38 or w["start"] - g[-1]["end"] >= 2):
            emit()
            g = []
        g.append(w)
    emit()
    return out


def parse_json(body: str):
    text = body.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise ValueError("The highlight model returned invalid JSON.")
        return json.loads(m.group(0))


def select_candidates(groups_: list[dict], duration: float, num_clips: int, minimum: int, maximum: int, client: OpenAI, model: str, progress: Progress):
    # Batch ~10 minutes to avoid sending an entire 3h transcript in one request.
    batches: list[list[dict]] = []
    b: list[dict] = []
    for g in groups_:
        if b and g["start"] - b[0]["start"] > 650:
            batches.append(b); b = []
        b.append(g)
    if b:
        batches.append(b)
    candidates: list[dict] = []
    for i, batch in enumerate(batches):
        transcript = "\n".join(f'{g["start"]:.1f}–{g["end"]:.1f}s | {g["text"]}' for g in batch)
        prompt = (f"Find up to 5 compelling, self-contained clips from this time-coded transcript. Each must be {minimum} to {maximum} seconds long. "
                  "Prefer tension, surprises, jokes, storytelling, clear learning payoff; ensure understandable opening hook, avoid duplicate premises. "
                  "Do not fabricate quotes or facts. Timestamps MUST be absolute seconds within the supplied range. "
                  'Output ONLY one JSON object with key "clips", containing array of {"start":number,"end":number,"score":integer 1..100,"title":string,"hook":string,"caption":string,"reason":string}. '
                  f"Video duration: {duration:.1f} seconds.\nTRANSCRIPT:\n{transcript}")
        response = client.responses.create(model=model, input=prompt, max_output_tokens=1900)
        decoded = parse_json(response.output_text)
        for c in decoded.get("clips", []):
            if not isinstance(c, dict):
                continue
            try:
                start, end = float(c["start"]), float(c["end"])
                score = min(100, max(0, round(float(c.get("score", 50)))))
            except (ValueError, TypeError, KeyError):
                continue
            if not 0 <= start < end <= duration + 0.5 or not minimum - 2 <= end - start <= maximum + 2:
                continue
            # Ensure model can't hallucinate timestamps from outside this batch.
            if start < batch[0]["start"] - 3 or end > batch[-1]["end"] + 3:
                continue
            candidates.append({"start": round(start, 2), "end": round(end, 2), "score": score, "title": str(c.get("title", "Clip"))[:90],
                               "hook": str(c.get("hook", ""))[:160], "caption": str(c.get("caption", ""))[:400], "reason": str(c.get("reason", ""))[:260]})
        progress(f"Scored highlights {i+1}/{len(batches)}", int(55 + 15 * (i+1) / len(batches)))
    # Greedy score-based selection with overlap prevention.
    picked = []
    for c in sorted(candidates, key=lambda d: d["score"], reverse=True):
        overlap = False
        for prior in picked:
            intersection = max(0, min(prior["end"], c["end"]) - max(prior["start"], c["start"]))
            if intersection / max(1, min(prior["end"] - prior["start"], c["end"] - c["start"])) > 0.25:
                overlap = True
                break
        if not overlap:
            picked.append(c)
            if len(picked) >= num_clips:
                break
    if not picked:
        raise ValueError("No suitable clip candidates found. Try a shorter requested duration or a more conversational video.")
    return picked


def render(source: Path, output: Path, selected: list[dict], words: list[dict], progress: Progress):
    output.mkdir(parents=True, exist_ok=True)
    encoder = os.getenv("VYRA_VIDEO_ENCODER", "libx264")
    if encoder not in {"libx264", "h264_nvenc"}:
        raise ValueError("VYRA_VIDEO_ENCODER must be libx264 or h264_nvenc.")
    done = []
    for i, clip in enumerate(selected, 1):
        captions = output / f"clip_{i:02d}.ass"
        target = output / f"clip_{i:02d}.mp4"
        subtitles_ass(words, clip["start"], clip["end"], captions)
        # force_original_aspect_ratio=increase fills the entire vertical frame; centered crop is a starter limitation.
        # Using a relative subtitle filename with cwd=output prevents escaping issues in Windows absolute paths.
        vf = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,subtitles='" + captions.name + "'"
        args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f'{clip["start"]:.3f}', "-i", str(source),
                "-t", f'{clip["end"]-clip["start"]:.3f}', "-vf", vf, "-c:v", encoder, "-preset", "fast" if encoder == "libx264" else "p4", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-ar", "48000", "-b:a", "128k", "-movflags", "+faststart", str(target)]
        result = subprocess.run(args, cwd=output, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode != 0:
            raise RuntimeError(f"Rendering clip {i} failed. Ensure FFmpeg has libass subtitle support: {result.stderr[-1100:]}")
        done.append({**clip, "file": target.name, "subtitles": captions.name})
        progress(f"Rendered clip {i}/{len(selected)}", int(72 + 27 * i / len(selected)))
    (output / "manifest.json").write_text(json.dumps({"clips": done}, ensure_ascii=False, indent=2), encoding="utf-8")
    return done


def process_video(source: Path, scratch: Path, output: Path, n: int, minimum: int, maximum: int, progress: Progress):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise EnvironmentError("FFmpeg and FFprobe must be installed and on PATH.")
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("Set OPENAI_API_KEY in .env. Never paste it into a public website.")
    progress("Inspecting video", 3)
    metadata = probe(source)
    from openai import OpenAI
    client = OpenAI(timeout=120, max_retries=2)
    scratch.mkdir(parents=True, exist_ok=True)
    words, _ = transcription_chunks(source, scratch, metadata["duration"], client, progress)
    (scratch / "transcript.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    progress("Finding candidate moments", 55)
    selected = select_candidates(groups(words), metadata["duration"], n, minimum, maximum, client, os.getenv("VYRA_HIGHLIGHT_MODEL", "gpt-4o-mini"), progress)
    progress("Editing and captioning", 72)
    clips = render(source, output, selected, words, progress)
    progress("Finished", 100)
    return {"clips": clips, "duration": round(metadata["duration"], 1), "input_size": source.stat().st_size}
