from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
import re

from PIL import Image, ImageOps

try:
    from token_store import unprotect, write_token
except ImportError:
    from .token_store import unprotect, write_token

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]


def _truncate_text(value: str, max_chars: int) -> str:
    """YouTube title/description limits are character limits, not UTF-8 byte limits."""
    return value[:max_chars]


def _fit_tags(tags: list[str], max_chars: int = 500) -> list[str]:
    result: list[str] = []
    used = 0
    for raw in tags:
        tag = raw.strip().replace("<", "").replace(">", "")
        if not tag:
            continue
        extra = len(tag) + (1 if result else 0)
        if used + extra > max_chars:
            break
        result.append(tag)
        used += extra
    return result


class YouTubeAPI:
    def __init__(self, app_dir: str | Path):
        self.app_dir = Path(app_dir)
        self.tokens_dir = self.app_dir / "tokens"
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        self.channels_file = self.app_dir / "channels.json"

    def _load_channels(self) -> list[dict]:
        if not self.channels_file.exists():
            return []
        try:
            data = json.loads(self.channels_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def list_channels(self) -> list[dict]:
        return self._load_channels()

    def connect_channel(self, client_secret_path: str, progress: Callable[[str], None] | None = None) -> dict:
        if not Path(client_secret_path).is_file():
            raise FileNotFoundError("Не найден файл OAuth client_secret.json из Google Cloud.")
        if progress:
            progress("Откройте окно Google и разрешите доступ к YouTube.")
        flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
        credentials = flow.run_local_server(port=0, open_browser=True, access_type="offline", prompt="select_account")
        service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        channels = []
        page_token = None
        while True:
            response = service.channels().list(
                part="snippet", mine=True, maxResults=50, pageToken=page_token
            ).execute()
            channels.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        if not channels:
            raise RuntimeError("Google-аккаунт авторизован, но YouTube-канал не найден.")
        saved = [c for c in self._load_channels()]
        by_id = {c.get("id"): c for c in saved if c.get("id")}
        for channel in channels:
            channel_id = channel["id"]
            name = channel.get("snippet", {}).get("title", channel_id)
            token_path = self.tokens_dir / f"{channel_id}.json"
            write_token(token_path, credentials.to_json().encode("utf-8"))
            by_id[channel_id] = {"id": channel_id, "name": name, "token_file": str(token_path)}
        saved = list(by_id.values())
        self.channels_file.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        return next(c for c in saved if c["id"] == channels[0]["id"])

    def remove_channel(self, channel_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", channel_id):
            raise ValueError("Некорректный ID YouTube-канала.")
        channels = [item for item in self._load_channels() if item.get("id") != channel_id]
        temp = self.channels_file.with_suffix(".json.tmp")
        temp.write_text(json.dumps(channels, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.channels_file)
        token_path = self.tokens_dir / f"{channel_id}.json"
        try:
            token_path.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Не удалось удалить локальный токен канала: {exc}") from exc

    def _service_for_channel(self, channel_id: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", channel_id):
            raise ValueError("Некорректный ID YouTube-канала.")
        token_path = self.tokens_dir / f"{channel_id}.json"
        if not token_path.is_file():
            raise FileNotFoundError("Для выбранного канала нет токена. Подключите канал заново.")
        token_data = unprotect(token_path.read_bytes())
        try:
            token_info = json.loads(token_data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Файл OAuth-токена повреждён. Отключите канал и подключите его заново.") from exc
        credentials = Credentials.from_authorized_user_info(token_info, SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            write_token(token_path, credentials.to_json().encode("utf-8"))
        if not credentials.valid:
            raise RuntimeError("Авторизация YouTube истекла. Подключите канал заново.")
        return build("youtube", "v3", credentials=credentials, cache_discovery=False)

    def upload_scheduled_video(
        self,
        channel_id: str,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        publish_at_utc: str,
        thumbnail_path: str = "",
        notify_subscribers: bool = True,
        progress: Callable[[str], None] | None = None,
        on_uploaded: Callable[[str], None] | None = None,
        before_insert: Callable[[], None] | None = None,
    ) -> tuple[str, str]:
        if not Path(video_path).is_file():
            raise FileNotFoundError(f"Не найден подготовленный MP4: {video_path}")
        if not title.strip():
            raise ValueError("Название видео не может быть пустым.")
        if len(title) > 100:
            raise ValueError(f"Название видео длиннее 100 символов ({len(title)}). Сократите шаблон.")
        if len(description) > 5000:
            raise ValueError(f"Описание длиннее 5000 символов ({len(description)}). Сократите шаблон.")
        if Path(video_path).stat().st_size > 256 * 1024 * 1024 * 1024:
            raise ValueError("Размер видео превышает максимальный лимит YouTube 256 ГБ.")
        try:
            publish_dt = datetime.fromisoformat(publish_at_utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Время публикации должно быть ISO 8601 с часовым поясом UTC.") from exc
        if publish_dt.tzinfo is None or publish_dt <= datetime.now(timezone.utc):
            raise ValueError("Время отложенной публикации должно быть в будущем и содержать часовой пояс.")
        service = self._service_for_channel(channel_id)
        body = {
            "snippet": {
                "title": title.replace("<", "").replace(">", "")[:100],
                "description": _truncate_text(description, 5000),
                "tags": _fit_tags(tags),
                "categoryId": "10",
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at_utc,
            },
        }
        media = MediaFileUpload(video_path, chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
        request = service.videos().insert(part="snippet,status", body=body, media_body=media, notifySubscribers=bool(notify_subscribers))
        if before_insert:
            before_insert()
        response = None
        while response is None:
            status, response = request.next_chunk(num_retries=5)
            if status and progress:
                progress(f"Загрузка {title[:48]}: {int(status.progress() * 100)}%")
        video_id = response.get("id")
        if not video_id:
            raise RuntimeError("YouTube завершил загрузку без video ID в ответе. Проверьте YouTube Studio перед повтором.")
        if on_uploaded:
            on_uploaded(video_id)
        thumbnail_note = ""
        if thumbnail_path and Path(thumbnail_path).is_file():
            try:
                with Image.open(thumbnail_path) as source:
                    rgb = source.convert("RGB")
                    fitted = ImageOps.contain(rgb, (1280, 720), method=Image.Resampling.LANCZOS)
                    canvas = Image.new("RGB", (1280, 720), (0, 0, 0))
                    canvas.paste(fitted, ((1280 - fitted.width) // 2, (720 - fitted.height) // 2))
                    with tempfile.TemporaryDirectory(prefix="abeats_thumb_") as temp_dir:
                        jpeg_path = Path(temp_dir) / "thumbnail.jpg"
                        quality = 90
                        while True:
                            canvas.save(jpeg_path, format="JPEG", quality=quality, optimize=True)
                            if jpeg_path.stat().st_size <= 1_900_000 or quality <= 55:
                                break
                            quality -= 5
                        if jpeg_path.stat().st_size > 2_000_000:
                            raise ValueError("Не удалось сжать миниатюру до лимита YouTube 2 МБ.")
                        service.thumbnails().set(
                            videoId=video_id,
                            media_body=MediaFileUpload(str(jpeg_path), mimetype="image/jpeg"),
                        ).execute()
            except Exception as exc:  # upload is already complete; preserve its ID and report thumbnail failure
                thumbnail_note = f"Видео загружено, но обложку YouTube установить не удалось: {exc}"
        return video_id, thumbnail_note
