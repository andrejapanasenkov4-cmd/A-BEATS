import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest.mock import patch

from app.core import BeatItem, calculate_publish_times, export_manifest, pair_audio_and_covers, resolve_title
from app.itunes_discography import find_artist_tracks
from app.quota import APP_DAILY_UPLOAD_LIMIT, load_usage, record_attempt, remaining


class CoreTests(unittest.TestCase):
    def test_pairing_ignores_cover_suffix(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "audio"
            covers = root / "covers"
            audio.mkdir()
            covers.mkdir()
            (audio / "Beat 01.wav").write_bytes(b"audio")
            (covers / "Beat 01_cover.jpg").write_bytes(b"image")
            items = pair_audio_and_covers(audio, covers)
            self.assertEqual(len(items), 1)
            self.assertTrue(items[0].cover_path.endswith("Beat 01_cover.jpg"))


    def test_ambiguous_cover_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "audio"
            covers = root / "covers"
            audio.mkdir()
            covers.mkdir()
            (audio / "Beat.wav").write_bytes(b"audio")
            (covers / "Beat.jpg").write_bytes(b"image")
            (covers / "Beat_cover.png").write_bytes(b"image")
            items = pair_audio_and_covers(audio, covers)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].cover_path, "")

    def test_export_manifest_writes_schedule_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.csv"
            scheduled = datetime(2027, 1, 2, 18, 0, tzinfo=ZoneInfo("America/New_York"))
            item = BeatItem(
                audio_path="/beats/Cold Night.wav", video_path="/output/Cold Night.mp4",
                title="KASPER Type Beat", description="Instrumental", tags="type beat, rap",
            )
            export_manifest([item], path, [scheduled], "America/New_York")
            content = path.read_text(encoding="utf-8-sig")
            self.assertIn("Cold Night.mp4", content)
            self.assertIn("KASPER Type Beat", content)
            self.assertIn("2027-01-02 18:00", content)

    def test_title_template(self):
        item = BeatItem(audio_path="/tmp/Cold Night.wav")
        self.assertEqual(
            resolve_title("{artist} Type Beat - {beat_name}", item, "KASPER"),
            "KASPER Type Beat - Cold Night",
        )

    def test_track_title_template(self):
        item = BeatItem(audio_path="/tmp/Cold Night.wav", track_name="SICKO MODE")
        self.assertEqual(
            resolve_title('{artist} Type Beat - "{track_name}"', item, "Travis Scott"),
            'Travis Scott Type Beat - "SICKO MODE"',
        )

    def test_track_title_falls_back_to_filename(self):
        item = BeatItem(audio_path="/tmp/Cold Night.wav")
        self.assertEqual(
            resolve_title('{artist} Type Beat - "{track_name}"', item, "Travis Scott"),
            'Travis Scott Type Beat - "Cold Night"',
        )

    @patch("app.itunes_discography.urllib.request.urlopen")
    def test_apple_catalog_track_lookup_filters_artist_and_duplicates(self, mocked_urlopen):
        payload = {
            "results": [
                {"artistName": "Travis Scott", "trackName": "FE!N"},
                {"artistName": "Travis Scott", "trackName": "FE!N"},
                {"artistName": "Another Artist", "trackName": "Unrelated"},
                {"artistName": "Travis Scott & Playboi Carti", "trackName": "Popular"},
            ]
        }
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        mocked_urlopen.return_value.__enter__.return_value = response
        self.assertEqual(find_artist_tracks("Travis Scott"), ["FE!N", "Popular"])

    def test_scheduling_in_timezone(self):
        start = (datetime.now(ZoneInfo("America/New_York")) + timedelta(days=3)).replace(
            hour=18, minute=0, second=0, microsecond=0
        )
        values = calculate_publish_times(start.strftime("%Y-%m-%d %H:%M"), 24, 3, "America/New_York")
        self.assertEqual(len(values), 3)
        self.assertEqual(values[1].hour, 18)
        self.assertEqual(values[2].date(), values[0].date() + timedelta(days=2))

    def test_nonexistent_dst_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "не существует"):
            calculate_publish_times("2027-03-14 02:30", 24, 1, "America/New_York", allow_past_start=True)

    def test_schedule_crossing_dst_gap_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Публикация №2"):
            calculate_publish_times("2027-03-13 02:30", 24, 2, "America/New_York", allow_past_start=True)

    def test_non_finite_interval_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "конечным"):
            start = (datetime.now(ZoneInfo("America/New_York")) + timedelta(days=3)).replace(hour=18, minute=0)
            calculate_publish_times(start.strftime("%Y-%m-%d %H:%M"), float("inf"), 2, "America/New_York")

    def test_uncertain_upload_state_survives_queue_serialization(self):
        import dataclasses
        item = BeatItem(audio_path="/tmp/beat.wav", uncertain_uploads={"channel123": "2027-01-02T18:00:00-05:00"})
        restored = BeatItem(**dataclasses.asdict(item))
        self.assertEqual(restored.uncertain_uploads["channel123"], "2027-01-02T18:00:00-05:00")

    def test_legacy_upload_record_migrates(self):
        item = BeatItem(audio_path="/tmp/beat.wav", video_id="video123", channel_id="channel123", scheduled_at="2026-11-10T18:00:00-05:00")
        self.assertEqual(item.uploaded_to["channel123"]["video_id"], "video123")

    def test_quota_ledger_records_and_caps_uploads(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "quota.json"
            for _ in range(APP_DAILY_UPLOAD_LIMIT):
                record_attempt(path)
            self.assertEqual(load_usage(path), APP_DAILY_UPLOAD_LIMIT)
            self.assertEqual(remaining(path), 0)


if __name__ == "__main__":
    unittest.main()
