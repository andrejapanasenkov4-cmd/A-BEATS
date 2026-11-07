"""Small real FFmpeg integration test; skipped when FFmpeg is not installed."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.core import BeatItem, render_video


@pytest.mark.parametrize("resolution,expected", [("1920x1080", (1920, 1080)), ("3840x2160", (3840, 2160))])
def test_render_produces_valid_mp4(tmp_path: Path, resolution: str, expected: tuple[int, int]):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe are not installed")

    audio = tmp_path / "short.wav"
    cover = tmp_path / "cover.png"
    Image.new("RGB", (1280, 720), (24, 14, 42)).save(cover)
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "0.6", "-c:a", "pcm_s16le", str(audio), "-y"],
        check=True, capture_output=True,
    )
    item = BeatItem(audio_path=str(audio), cover_path=str(cover))
    output = Path(render_video(item, tmp_path / "rendered", resolution, ffmpeg))
    assert output.is_file() and output.stat().st_size > 0
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(output)],
        check=True, capture_output=True, text=True,
    )
    streams = json.loads(probe.stdout)["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    assert (video["width"], video["height"]) == expected
    assert any(stream["codec_type"] == "audio" for stream in streams)
