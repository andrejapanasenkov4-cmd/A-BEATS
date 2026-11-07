from __future__ import annotations

import csv
import math
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma",
    ".aif", ".aiff", ".alac", ".opus", ".ape", ".caf", ".amr", ".3gp",
}
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif",
}


@dataclass
class BeatItem:
    audio_path: str
    cover_path: str = ""
    title: str = ""
    track_name: str = ""
    description: str = ""
    tags: str = ""
    video_path: str = ""
    status: str = "Ожидает"
    video_id: str = ""
    scheduled_at: str = ""
    upload_error: str = ""
    channel_id: str = ""
    uploaded_to: dict[str, dict] = field(default_factory=dict)
    uncertain_uploads: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Migrate queue records created by A-BEATS 1.0.0.
        if self.video_id and self.channel_id and self.channel_id not in self.uploaded_to:
            self.uploaded_to[self.channel_id] = {
                "video_id": self.video_id,
                "scheduled_at": self.scheduled_at,
            }

    @property
    def beat_name(self) -> str:
        return Path(self.audio_path).stem


def _normalize_stem(value: str) -> str:
    value = Path(value).stem.lower()
    value = re.sub(r"(?:[_ .-]+)(cover|artwork|thumbnail|thumb)$", "", value)
    value = re.sub(r"[^a-zа-яё0-9]+", "", value, flags=re.IGNORECASE)
    return value


def _image_match_score(audio_stem: str, image_stem: str) -> float:
    a, b = _normalize_stem(audio_stem), _normalize_stem(image_stem)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return min(len(a), len(b)) / max(len(a), len(b))
    tokens_a = {t for t in re.split(r"[^a-zа-яё0-9]+", Path(audio_stem).stem.lower()) if len(t) > 1}
    tokens_b = {t for t in re.split(r"[^a-zа-яё0-9]+", Path(image_stem).stem.lower()) if len(t) > 1}
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b) if tokens_a and tokens_b else 0.0


def pair_audio_and_covers(audio_dir: str | Path, cover_dir: str | Path) -> list[BeatItem]:
    """Recursively find supported media and pair images conservatively by filename."""
    audio_root, cover_root = Path(audio_dir), Path(cover_dir)
    if not audio_root.is_dir():
        raise ValueError("Папка с битами не найдена.")
    if not cover_root.is_dir():
        raise ValueError("Папка с обложками не найдена.")

    cover_files = sorted(
        (p for p in cover_root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda p: str(p).lower(),
    )
    audio_files = sorted(
        (p for p in audio_root.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS),
        key=lambda p: str(p).lower(),
    )
    covers_by_key: dict[str, list[Path]] = {}
    for cover in cover_files:
        covers_by_key.setdefault(_normalize_stem(cover.name), []).append(cover)

    items: list[BeatItem] = []
    for audio in audio_files:
        exact = covers_by_key.get(_normalize_stem(audio.name), [])
        chosen = exact[0] if len(exact) == 1 else None
        if not exact and cover_files:
            scored = sorted(
                ((_image_match_score(audio.stem, cover.stem), cover) for cover in cover_files),
                key=lambda pair: pair[0], reverse=True,
            )
            if scored and scored[0][0] >= 0.60:
                second = scored[1][0] if len(scored) > 1 else 0.0
                if scored[0][0] - second >= 0.15:
                    chosen = scored[0][1]
        items.append(BeatItem(
            audio_path=str(audio), cover_path=str(chosen) if chosen else "", title=audio.stem
        ))
    return items


def resolve_title(template: str, item: BeatItem, artist: str = "") -> str:
    values = {"artist": artist.strip(), "beat_name": item.beat_name, "title": item.beat_name,
              "track_name": item.track_name.strip() or item.beat_name}
    try:
        result = template.format(**values).strip()
    except (KeyError, ValueError):
        result = f"{artist.strip()} Type Beat - {values['track_name']}".strip()
    return result or item.beat_name


def calculate_publish_times(
    start_text: str, interval_hours: float, count: int, timezone_name: str, *, allow_past_start: bool = False
) -> list[datetime]:
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Неизвестный часовой пояс: {timezone_name}") from exc
    try:
        local_start = datetime.strptime(start_text.strip(), "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Дата должна быть в формате YYYY-MM-DD HH:MM, например 2026-11-08 18:00.") from exc
    # Reject nonexistent wall-clock times during the spring DST transition.
    start = local_start.replace(tzinfo=tz, fold=0)
    round_trip = start.astimezone(ZoneInfo("UTC")).astimezone(tz).replace(tzinfo=None)
    if round_trip != local_start:
        raise ValueError("Это местное время не существует из-за перехода на летнее время. Выберите другое время.")
    if not allow_past_start and start <= datetime.now(tz):
        raise ValueError("Время первой публикации должно быть в будущем.")
    if not math.isfinite(interval_hours) or interval_hours <= 0:
        raise ValueError("Интервал должен быть конечным числом больше нуля.")
    result: list[datetime] = []
    for index in range(count):
        scheduled = start + timedelta(hours=interval_hours * index)
        wall_time = scheduled.replace(tzinfo=None)
        round_trip = scheduled.astimezone(ZoneInfo("UTC")).astimezone(tz).replace(tzinfo=None)
        if round_trip != wall_time:
            raise ValueError(
                f"Публикация №{index + 1} попадает на несуществующее местное время из-за перехода на летнее время. "
                "Измените время или интервал."
            )
        result.append(scheduled)
    return result


def render_video(
    item: BeatItem,
    output_dir: str | Path,
    resolution: str = "1920x1080",
    ffmpeg_path: str = "",
    progress: Callable[[str], None] | None = None,
) -> str:
    if not item.cover_path or not Path(item.cover_path).is_file():
        raise ValueError(f"Для «{item.beat_name}» не найдена обложка.")
    if not Path(item.audio_path).is_file():
        raise ValueError(f"Аудиофайл не найден: {item.audio_path}")

    executable = ffmpeg_path.strip() or shutil.which("ffmpeg") or ""
    if not executable or (not Path(executable).exists() and shutil.which(executable) is None):
        raise FileNotFoundError("FFmpeg не найден. Установите FFmpeg или укажите путь к ffmpeg.exe в настройках.")

    width_height = {"1920x1080": (1920, 1080), "3840x2160": (3840, 2160)}
    if resolution not in width_height:
        raise ValueError("Неподдерживаемое разрешение.")
    width, height = width_height[resolution]
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[<>:"/\\|?*]+', "_", item.beat_name).strip(" .") or "beat"
    safe_name = safe_name[:120].rstrip(" .") or "beat"
    # Windows reserves device names even when an extension is present.
    if safe_name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        safe_name = f"_{safe_name}"
    previous_output = Path(item.video_path) if item.video_path else None
    if previous_output and previous_output.is_file() and previous_output.parent.resolve() == out_root.resolve():
        output = previous_output
    else:
        output = out_root / f"{safe_name}.mp4"
        suffix = 2
        while output.exists():
            output = out_root / f"{safe_name}_{suffix}.mp4"
            suffix += 1

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    )
    command = [
        executable, "-hide_banner", "-y", "-loop", "1", "-framerate", "30",
        "-i", item.cover_path, "-i", item.audio_path,
        "-map", "0:v:0", "-map", "1:a:0", "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-tune", "stillimage",
        "-r", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k",
        "-shortest", "-movflags", "+faststart", str(output),
    ]
    if progress:
        progress(f"Рендер: {item.beat_name}")
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = (result.stderr or result.stdout)[-1800:]
        raise RuntimeError(f"FFmpeg завершился с ошибкой для «{item.beat_name}»:\n{tail}")
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"FFmpeg не создал корректный MP4 для «{item.beat_name}».")
    return str(output)


def export_manifest(items: Iterable[BeatItem], path: str | Path, schedules: list[datetime], timezone_name: str) -> None:
    rows = list(items)
    if len(rows) != len(schedules):
        raise ValueError("Количество битов не совпадает с количеством дат публикации.")
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["video_file", "title", "description", "tags", "scheduled_local", "timezone"])
        for item, publish_at in zip(rows, schedules):
            writer.writerow([
                item.video_path, item.title, item.description, item.tags,
                publish_at.strftime("%Y-%m-%d %H:%M %Z"), timezone_name,
            ])
