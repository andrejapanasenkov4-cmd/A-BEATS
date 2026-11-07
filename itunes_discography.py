from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
USER_AGENT = "A-BEATS/1.0 (desktop beat publishing helper)"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def find_artist_tracks(artist_name: str, country: str = "US", limit: int = 200) -> list[str]:
    """Return distinct track names for an artist using Apple's public iTunes Search API.

    The caller should show the returned names to the user before publishing. The
    results are catalog metadata, not a rights clearance or permission to use a title.
    """
    artist_name = artist_name.strip()
    if not artist_name:
        raise ValueError("Введите имя артиста.")
    if not re.fullmatch(r"[A-Za-z]{2}", country):
        raise ValueError("Код страны магазина должен состоять из двух букв.")
    limit = max(1, min(int(limit), 200))
    params = urllib.parse.urlencode({
        "term": artist_name,
        "media": "music",
        "entity": "song",
        "attribute": "artistTerm",
        "limit": limit,
        "country": country.upper(),
    })
    request = urllib.request.Request(
        f"{ITUNES_SEARCH_URL}?{params}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Не удалось получить дискографию из каталога Apple: {exc}") from exc

    wanted = _normalize_name(artist_name)
    tracks: list[str] = []
    seen: set[str] = set()
    for entry in payload.get("results", []):
        credited_artist = str(entry.get("artistName", ""))
        credited = _normalize_name(credited_artist)
        if wanted not in credited:
            continue
        title = str(entry.get("trackName", "")).strip()
        key = _normalize_name(title)
        if title and key and key not in seen:
            seen.add(key)
            tracks.append(title)
    if not tracks:
        raise RuntimeError(
            f"В каталоге Apple не нашлись треки артиста «{artist_name}». "
            "Проверьте написание или попробуйте другой регион."
        )
    return tracks
