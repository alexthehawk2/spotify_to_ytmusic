from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, AsyncGenerator

import httpx
from ytmusicapi import YTMusic

SEARCH_TYPES = ("songs", "videos")
SPOTIFY_PAGE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
PLAYLIST_ADD_BATCH_SIZE = 25
DEFAULT_BROWSER_AUTH_PATH = Path(__file__).resolve().with_name("browser.json")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

@dataclass
class SourceTrack:
    spotify_track_id: str
    spotify_track_uri: str
    name: str
    artists: list[str]
    album: str
    duration_ms: int | None
    explicit: bool
    available_in_spotify_market: bool | None
    spotify_url: str
    track_number: int

    @property
    def primary_artist(self) -> str:
        return self.artists[0] if self.artists else ""

    @property
    def artist_text(self) -> str:
        return ", ".join(self.artists)

def extract_playlist_id(raw_value: str) -> str:
    raw_value = raw_value.strip()
    match = re.search(r"playlist/([a-zA-Z0-9]+)", raw_value)
    if match:
        return match.group(1)
    if "?" in raw_value:
        return raw_value.split("?", 1)[0]
    return raw_value

def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\(feat\..*?\)", "", text)
    text = re.sub(r"\[feat\..*?\]", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def clean_query_component(text: str) -> str:
    return normalize_text(text).replace(" ", " ")

def runtime_browser_auth_path() -> Path | None:
    """
    Priority order:
    1. BROWSER_AUTH_JSON env var (base64 OR raw JSON) — writes to /tmp/browser.azure.json
    2. /secrets/browser-json — Azure volume mount
    3. DEFAULT_BROWSER_AUTH_PATH — browser.json baked into the image at /app/browser.json
    """

    browser_auth_env = os.getenv("BROWSER_AUTH_JSON", "").strip()

    if browser_auth_env:
        try:
            decoded_json = None

            # Try base64 decode first
            try:
                decoded_bytes = base64.b64decode(browser_auth_env)
                decoded_str = decoded_bytes.decode("utf-8")

                # Validate decoded JSON
                json.loads(decoded_str)
                decoded_json = decoded_str
                print("DEBUG: Loaded browser auth from base64 env var")

            except Exception:
                # Fallback: assume raw JSON
                json.loads(browser_auth_env)
                decoded_json = browser_auth_env
                print("DEBUG: Loaded browser auth from raw JSON env var")

            runtime_dir = Path(os.getenv("RUNTIME_AUTH_DIR", "/tmp"))
            runtime_dir.mkdir(parents=True, exist_ok=True)

            runtime_path = runtime_dir / "browser.azure.json"
            runtime_path.write_text(decoded_json, encoding="utf-8")

            print(f"DEBUG: Created runtime auth file at {runtime_path}")
            return runtime_path

        except Exception as e:
            print(f"DEBUG: Failed to process BROWSER_AUTH_JSON env var: {e}")

    # 2. Try Azure volume-mounted secret
    azure_mount_path = Path("/secrets/browser-json")
    if azure_mount_path.exists() and azure_mount_path.stat().st_size > 0:
        print(f"DEBUG: Found Azure-mounted browser auth at {azure_mount_path}")
        return azure_mount_path

    # 3. Try default path (baked into image)
    if DEFAULT_BROWSER_AUTH_PATH.exists():
        print(f"DEBUG: Found default browser auth at {DEFAULT_BROWSER_AUTH_PATH}")
        return DEFAULT_BROWSER_AUTH_PATH

    print("DEBUG: No browser.json found in env, Azure mount, or disk.")
    return None

def slugify_filename(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._")
    return safe or "migration"

async def spotify_session() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={
            "User-Agent": SPOTIFY_PAGE_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=30.0,
        follow_redirects=True
    )

async def fetch_public_playlist_page(client: httpx.AsyncClient, playlist_id: str) -> str:
    url = f"https://open.spotify.com/playlist/{playlist_id}"
    response = await client.get(url)
    response.raise_for_status()
    print(f"Fetched {len(response.text)} bytes from {url}")
    return response.text

def decode_initial_state(html: str) -> dict[str, Any]:
    match = re.search(r'<script id="(?:initialState|initial-state)" type="text/plain">(.*?)</script>', html, re.S)
    if not match:
        raise RuntimeError("Spotify public page did not include the expected initialState payload.")
    
    content = match.group(1).strip()
    try:
        return json.loads(base64.b64decode(content))
    except Exception:
        try:
            return json.loads(content)
        except Exception as exc:
            raise RuntimeError(f"Failed to decode Spotify initialState payload: {exc}") from exc

def text_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""

def dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}

def extract_artists(raw_artists: Any) -> list[str]:
    if isinstance(raw_artists, dict):
        items = raw_artists.get("items") or raw_artists.get("nodes") or []
    elif isinstance(raw_artists, list):
        items = raw_artists
    else:
        return []

    artists: list[str] = []
    for artist in items:
        if not isinstance(artist, dict):
            continue
        name = (
            text_or_empty(artist.get("name"))
            or text_or_empty(artist.get("profile", {}).get("name"))
            or text_or_empty(artist.get("profile", {}).get("title"))
        )
        if name:
            artists.append(name)
    return artists

def extract_track_from_node(node: Any, current_market: str | None = None) -> SourceTrack | None:
    if not isinstance(node, dict):
        return None

    if "itemV2" in node:
        return extract_track_from_node(node.get("itemV2"), current_market=current_market)
    if node.get("__typename") == "TrackResponseWrapper":
        return extract_track_from_node(node.get("data"), current_market=current_market)
    if "data" in node and isinstance(node.get("data"), dict):
        nested = extract_track_from_node(node.get("data"), current_market=current_market)
        if nested:
            return nested

    uri = text_or_empty(node.get("uri"))
    if not uri.startswith("spotify:track:"):
        return None

    name = text_or_empty(node.get("name"))
    if not name:
        return None

    album = text_or_empty(node.get("albumOfTrack", {}).get("name"))
    if not album:
        album = text_or_empty(node.get("album", {}).get("name"))

    duration_ms = None
    duration = node.get("duration")
    if isinstance(duration, dict):
        total_ms = duration.get("totalMilliseconds")
        if isinstance(total_ms, int):
            duration_ms = total_ms
    elif isinstance(node.get("duration_ms"), int):
        duration_ms = node["duration_ms"]

    rating = node.get("contentRating")
    explicit = bool(node.get("explicit"))
    if isinstance(rating, dict):
        explicit = explicit or text_or_empty(rating.get("label")).upper() == "EXPLICIT"

    available_in_spotify_market = None
    available_markets = node.get("availableMarkets")
    if current_market and isinstance(available_markets, dict):
        market_items = available_markets.get("items") or []
        market_codes = {
            text_or_empty(item.get("countryCode")).upper()
            for item in market_items
            if isinstance(item, dict) and item.get("countryCode")
        }
        if market_codes:
            available_in_spotify_market = current_market.upper() in market_codes

    track_id = uri.rsplit(":", 1)[-1]
    return SourceTrack(
        spotify_track_id=track_id,
        spotify_track_uri=uri,
        name=name,
        artists=extract_artists(node.get("artists")),
        album=album,
        duration_ms=duration_ms,
        explicit=explicit,
        available_in_spotify_market=available_in_spotify_market,
        spotify_url=f"https://open.spotify.com/track/{track_id}",
        track_number=int(node.get("trackNumber") or 0),
    )

def extract_tracks_from_items(items: list[Any], current_market: str | None = None) -> list[SourceTrack]:
    tracks: list[SourceTrack] = []
    for item in items:
        track = extract_track_from_node(item, current_market=current_market)
        if track:
            tracks.append(track)
    return tracks

def extract_public_playlist_from_html(
    html: str, playlist_id: str
) -> tuple[dict[str, Any], list[SourceTrack], int, str | None]:
    state = decode_initial_state(html)
    entity_key = f"spotify:playlist:{playlist_id}"
    playlist_entity = state.get("entities", {}).get("items", {}).get(entity_key)
    if not playlist_entity:
        raise RuntimeError("Spotify public page did not expose playlist entity data for this playlist.")

    content = playlist_entity.get("content") or {}
    current_market = text_or_empty(state.get("session", {}).get("country")).upper() or None
    tracks = extract_tracks_from_items(content.get("items") or [], current_market=current_market)
    total_count = int(content.get("totalCount") or len(tracks))

    owner = ""
    owner_v2 = playlist_entity.get("ownerV2")
    if isinstance(owner_v2, dict):
        owner = text_or_empty(owner_v2.get("data", {}).get("name")) or text_or_empty(owner_v2.get("name"))

    playlist = {
        "id": playlist_entity.get("id") or playlist_id,
        "name": text_or_empty(playlist_entity.get("name")) or playlist_id,
        "description": text_or_empty(playlist_entity.get("description")),
        "owner": owner,
        "external_url": f"https://open.spotify.com/playlist/{playlist_id}",
    }
    return playlist, tracks, total_count, current_market

def collect_tracks_from_json_blob(
    blob: Any,
    current_market: str | None,
    tracks: list[SourceTrack],
) -> None:
    if isinstance(blob, dict):
        if "itemV2" in blob:
            track = extract_track_from_node(blob, current_market=current_market)
            if track:
                tracks.append(track)
            return
        for value in blob.values():
            collect_tracks_from_json_blob(value, current_market, tracks)
    elif isinstance(blob, list):
        for value in blob:
            collect_tracks_from_json_blob(value, current_market, tracks)

def extract_track_ids_from_dom(page: Any) -> list[str]:
    hrefs = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/track/"]'))
            .map((a) => a.getAttribute('href') || '')
            .filter(Boolean)"""
    )
    ordered_ids: list[str] = []
    for href in hrefs:
        match = re.search(r"/track/([A-Za-z0-9]+)", href)
        if not match:
            continue
        ordered_ids.append(match.group(1))
    return ordered_ids

async def fetch_remaining_tracks_with_browser(
    playlist_url: str,
    initial_tracks: list[SourceTrack],
    expected_total: int,
    current_market: str | None,
    browser_channel: str,
    headless: bool,
    timeout_seconds: int,
) -> list[SourceTrack]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright is not installed. Install it with `pip install playwright`."
        ) from exc

    track_catalog: dict[str, SourceTrack] = {track.spotify_track_id: track for track in initial_tracks}
    initial_ids = [track.spotify_track_id for track in initial_tracks]
    network_order: list[str] = []
    seen_page_sequences: set[tuple[str, ...]] = set()
    dom_order: list[str] = [track.spotify_track_id for track in initial_tracks]

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=browser_channel, headless=headless)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1200},
            user_agent=SPOTIFY_PAGE_USER_AGENT,
        )
        page = await context.new_page()

        async def on_response(response: Any) -> None:
            if "api-partner.spotify.com/pathfinder" not in response.url:
                return
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            try:
                payload = await response.json()
            except Exception:
                return
            page_tracks: list[SourceTrack] = []
            collect_tracks_from_json_blob(payload, current_market, page_tracks)
            if not page_tracks:
                return
            page_ids = tuple(track.spotify_track_id for track in page_tracks)
            if page_ids in seen_page_sequences:
                return
            seen_page_sequences.add(page_ids)
            if list(page_ids) == initial_ids[: len(page_ids)]:
                for track in page_tracks:
                    track_catalog.setdefault(track.spotify_track_id, track)
                return
            network_order.extend(page_ids)
            for track in page_tracks:
                track_catalog.setdefault(track.spotify_track_id, track)

        page.on("response", on_response)
        await page.goto(playlist_url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(2_000)

        end_time = asyncio.get_event_loop().time() + timeout_seconds
        stagnant_loops = 0
        last_signature = (len(track_catalog), len(dom_order))

        while asyncio.get_event_loop().time() < end_time:
            hrefs = await page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href*="/track/"]'))
                    .map((a) => a.getAttribute('href') || '')
                    .filter(Boolean)"""
            )
            visible_track_ids = []
            for href in hrefs:
                match = re.search(r"/track/([A-Za-z0-9]+)", href)
                if match:
                    visible_track_ids.append(match.group(1))

            if len(visible_track_ids) > len(dom_order):
                dom_order = visible_track_ids

            if len(dom_order) >= expected_total:
                break

            await page.evaluate(
                """() => {
                    const selectors = [
                      'main',
                      '[data-overlayscrollbars-viewport]',
                      '[role="grid"]',
                      '[data-testid="playlist-tracklist"]',
                    ];
                    for (const selector of selectors) {
                      const element = document.querySelector(selector);
                      if (element && typeof element.scrollBy === 'function') {
                        element.scrollBy(0, 5000);
                      }
                    }
                    window.scrollBy(0, 5000);
                    document.documentElement.scrollBy(0, 5000);
                }"""
            )
            await page.mouse.wheel(0, 5000)
            await page.wait_for_timeout(1_200)

            signature = (len(track_catalog), len(dom_order))
            if signature == last_signature:
                stagnant_loops += 1
            else:
                stagnant_loops = 0
                last_signature = signature

            if stagnant_loops >= 8 and len(dom_order) >= expected_total:
                break
            if stagnant_loops >= 16:
                break

        await browser.close()

    preferred_order = initial_ids + network_order
    if len(preferred_order) >= expected_total:
        return [track_catalog[track_id] for track_id in preferred_order[:expected_total] if track_id in track_catalog]
    return [track_catalog[track_id] for track_id in dom_order if track_id in track_catalog]

def candidate_queries(track: SourceTrack) -> list[str]:
    artist = clean_query_component(track.primary_artist)
    title = clean_query_component(track.name)
    album = clean_query_component(track.album)
    queries = [f"{title} {artist}", f"{artist} {title}"]
    if album:
        queries.append(f"{title} {artist} {album}")
    return list(dict.fromkeys(query for query in queries if query.strip()))

def duration_to_ms(duration: str | None) -> int | None:
    if not duration:
        return None
    parts = duration.split(":")
    if not 1 <= len(parts) <= 3:
        return None
    total = 0
    for part in parts:
        if not part.isdigit():
            return None
        total = total * 60 + int(part)
    return total * 1000

def score_candidate(track: SourceTrack, candidate: dict[str, Any]) -> int:
    score = 0
    source_title = normalize_text(track.name)
    source_artists = [normalize_text(artist) for artist in track.artists]
    source_album = normalize_text(track.album)
    candidate_title = normalize_text(text_or_empty(candidate.get("title")))

    if candidate_title == source_title:
        score += 50
    elif source_title and source_title in candidate_title:
        score += 35

    candidate_artists = [
        normalize_text(artist.get("name", ""))
        for artist in candidate.get("artists", [])
        if isinstance(artist, dict) and artist.get("name")
    ]
    if source_artists and candidate_artists:
        if candidate_artists[0] == source_artists[0]:
            score += 30
        score += sum(1 for artist in candidate_artists if artist in source_artists) * 10

    candidate_album = normalize_text(text_or_empty(dict_or_empty(candidate.get("album")).get("name")))
    if source_album and candidate_album and candidate_album == source_album:
        score += 12

    candidate_duration_ms = duration_to_ms(text_or_empty(candidate.get("duration")))
    if track.duration_ms and candidate_duration_ms:
        diff = abs(track.duration_ms - candidate_duration_ms)
        if diff <= 2_000:
            score += 15
        elif diff <= 5_000:
            score += 8

    result_type = candidate.get("resultType", "")
    if result_type == "song":
        score += 10
    elif result_type == "video":
        score += 4

    return score

def search_best_match(
    ytmusic: YTMusic, track: SourceTrack, delay_seconds: float
) -> tuple[str | None, dict[str, Any] | None, int]:
    best_candidate: dict[str, Any] | None = None
    best_score = -1

    for query in candidate_queries(track):
        for search_type in SEARCH_TYPES:
            try:
                results = ytmusic.search(query, filter=search_type, limit=5)
            except Exception:
                results = ytmusic.search(query, limit=5)
            for candidate in results:
                if not isinstance(candidate, dict):
                    continue
                try:
                    score = score_candidate(track, candidate)
                except Exception:
                    continue
                if score > best_score:
                    best_candidate = candidate
                    best_score = score
            time.sleep(delay_seconds)
            if best_score >= 95:
                break
        if best_score >= 95:
            break

    if not best_candidate:
        return None, None, best_score
    return best_candidate.get("videoId"), best_candidate, best_score

class PlaylistMigrator:
    def __init__(
        self,
        spotify_playlist_url: str,
        yt_auth: str | dict[str, Any],
        playlist_name_override: str | None = None,
        playlist_description_override: str | None = None,
        is_public: bool = False,
        limit: int | None = None,
        delay: float = 0.35,
        min_extraction_rate: float = 1.0,
        spotify_browser_channel: str = "chromium",
        spotify_headless: bool = True,
        spotify_scroll_timeout: int = 240,
    ):
        self.spotify_playlist_url = spotify_playlist_url
        self.yt_auth = yt_auth
        self.playlist_name_override = playlist_name_override
        self.playlist_description_override = playlist_description_override
        self.is_public = is_public
        self.limit = limit
        self.delay = delay
        self.min_extraction_rate = min_extraction_rate
        self.spotify_browser_channel = spotify_browser_channel
        self.spotify_headless = spotify_headless
        self.spotify_scroll_timeout = spotify_scroll_timeout

        self.tracks = []
        self.matched_tracks = []
        self.missing_tracks = []
        self.summary = {}
        self.status = "idle"
        self.progress = 0.0
        self.logs = []

        self.playlist_id = extract_playlist_id(spotify_playlist_url)

        if self.yt_auth:
            self.log("Using provided yt_auth (OAuth or custom).")
            try:
                if isinstance(self.yt_auth, dict):
                    yt_auth_copy = self.yt_auth.copy()
                    client_id = yt_auth_copy.pop("client_id", None)
                    client_secret = yt_auth_copy.pop("client_secret", None)
                    
                    # ytmusicapi RefreshingToken expects specific keys. Filter out unexpected ones like refresh_token_expires_in
                    allowed_keys = {"access_token", "refresh_token", "scope", "token_type", "expires_in", "expires_at"}
                    filtered_auth = {k: v for k, v in yt_auth_copy.items() if k in allowed_keys}
                    
                    if client_id and client_secret:
                        from ytmusicapi.auth.oauth.credentials import OAuthCredentials
                        oauth_credentials = OAuthCredentials(
                            client_id=client_id,
                            client_secret=client_secret
                        )
                        auth_data = json.dumps(filtered_auth)
                        self.ytmusic = YTMusic(auth_data, oauth_credentials=oauth_credentials)
                    else:
                        auth_data = json.dumps(filtered_auth)
                        self.ytmusic = YTMusic(auth_data)
                else:
                    self.ytmusic = YTMusic(self.yt_auth)
                self.log("YTMusic initialized successfully with provided yt_auth.")
            except Exception as e:
                self.log(f"ERROR: Failed to initialize YTMusic with provided yt_auth: {e}")
                raise RuntimeError(f"yt_auth provided but failed to load: {e}") from e
        else:
            # Resolve browser auth path using priority chain:
            # 1. BROWSER_AUTH_JSON env var
            # 2. /secrets/browser-json (Azure volume mount)
            # 3. /app/browser.json (baked into Docker image)
            browser_auth_path = runtime_browser_auth_path() or DEFAULT_BROWSER_AUTH_PATH
    
            if browser_auth_path.exists():
                self.log(f"Using browser auth from: {browser_auth_path}")
                self.log(f"File size: {browser_auth_path.stat().st_size} bytes")
                try:
                    self.ytmusic = YTMusic(str(browser_auth_path))
                    self.log("YTMusic initialized successfully with browser auth.")
                except Exception as e:
                    self.log(f"ERROR: Failed to initialize YTMusic with {browser_auth_path}: {e}")
                    self.log(f"File contents preview: {browser_auth_path.read_text(encoding='utf-8')[:300]}")
                    raise RuntimeError(f"browser.json found but failed to load: {e}") from e
            else:
                self.log(f"ERROR: No browser.json found at {browser_auth_path}")
                self.log(
                    f"Files in /secrets: {list(Path('/secrets').iterdir()) if Path('/secrets').exists() else 'directory missing'}"
                )
                self.log(
                    f"Files in /app: {[f.name for f in Path('/app').iterdir() if f.suffix == '.json']}"
                )
                raise RuntimeError(
                    "No browser.json found. Ensure it is either baked into the Docker image, "
                    "mounted via Azure secret volume, or provided via BROWSER_AUTH_JSON env var."
                )

        try:
            self.search_ytmusic = YTMusic()
        except Exception:
            self.search_ytmusic = self.ytmusic

    def log(self, message: str):
        print(message)
        self.logs.append(message)

    async def add_tracks_to_playlist(
        self, playlist_id: str, video_ids: list[str]
    ) -> tuple[list[str], list[str]]:
        added_video_ids: list[str] = []
        failed_video_ids: list[str] = []

        for start in range(0, len(video_ids), PLAYLIST_ADD_BATCH_SIZE):
            batch = video_ids[start : start + PLAYLIST_ADD_BATCH_SIZE]
            try:
                await asyncio.to_thread(
                    self.ytmusic.add_playlist_items,
                    playlist_id,
                    batch,
                )
                added_video_ids.extend(batch)
                continue
            except Exception as exc:
                self.log(
                    f"Batch add failed for tracks {start + 1}-{start + len(batch)}: {exc}. Retrying one by one..."
                )

            for video_id in batch:
                try:
                    await asyncio.to_thread(
                        self.ytmusic.add_playlist_items,
                        playlist_id,
                        [video_id],
                    )
                    added_video_ids.append(video_id)
                except Exception as exc:
                    failed_video_ids.append(video_id)
                    self.log(f"Failed to add video {video_id}: {exc}")

        return added_video_ids, failed_video_ids

    async def run(self) -> AsyncGenerator[dict[str, Any], None]:
        self.status = "extracting"
        self.log(f"Fetching Spotify playlist: {self.playlist_id}")
        
        playlist_meta = None
        tracks = []
        total_count = 0
        current_market = None

        try:
            async with await spotify_session() as client:
                html = await fetch_public_playlist_page(client, self.playlist_id)
                if len(html) > 10000:
                    playlist_meta, tracks, total_count, current_market = extract_public_playlist_from_html(html, self.playlist_id)
                else:
                    self.log("Initial request returned minimal data. Using browser extraction...")
        except Exception as exc:
            self.log(f"Initial request failed: {exc}. Using browser extraction...")

        if not tracks or total_count > len(tracks):
            self.log(f"Extraction partial or failed ({len(tracks)}/{total_count}). Starting browser extraction...")
            try:
                tracks = await fetch_remaining_tracks_with_browser(
                    playlist_url=f"https://open.spotify.com/playlist/{self.playlist_id}",
                    initial_tracks=tracks,
                    expected_total=total_count or 100,
                    current_market=current_market,
                    browser_channel=self.spotify_browser_channel,
                    headless=self.spotify_headless,
                    timeout_seconds=self.spotify_scroll_timeout,
                )
                
                if not playlist_meta:
                    playlist_meta = {
                        "id": self.playlist_id,
                        "name": f"Migrated Playlist {self.playlist_id}",
                        "description": "Migrated from Spotify",
                        "owner": "Unknown",
                        "external_url": f"https://open.spotify.com/playlist/{self.playlist_id}",
                    }
                
                if total_count == 0:
                    total_count = len(tracks)

            except Exception as exc:
                self.log(f"Browser extraction failed: {exc}")
                if not tracks:
                    self.status = "failed"
                    raise

        extraction_rate = (len(tracks) / total_count) if total_count else 0.0
        if not self.limit and extraction_rate < self.min_extraction_rate:
            self.status = "failed"
            error_msg = f"Extraction rate {extraction_rate:.2%} below minimum {self.min_extraction_rate:.2%}"
            self.log(error_msg)
            raise RuntimeError(error_msg)

        if self.limit:
            tracks = tracks[: self.limit]
        
        self.tracks = tracks
        self.log(f"Extracted {len(self.tracks)} tracks.")

        self.status = "matching"
        video_ids = []
        for index, track in enumerate(self.tracks, start=1):
            self.log(f"[{index}/{len(self.tracks)}] Resolving {track.name} - {track.artist_text}")
            try:
                video_id, match, score = await asyncio.to_thread(
                    search_best_match,
                    self.search_ytmusic,
                    track,
                    self.delay,
                )
            except Exception as exc:
                self.log(f"Search failed for {track.name} - {track.artist_text}: {exc}")
                raise
            
            base_row = asdict(track)
            base_row["artists"] = track.artist_text
            
            if video_id and match:
                video_ids.append(video_id)
                self.matched_tracks.append({
                    **base_row,
                    "yt_video_id": video_id,
                    "yt_title": text_or_empty(match.get("title")),
                    "yt_artists": ", ".join(
                        artist.get("name", "")
                        for artist in match.get("artists", [])
                        if isinstance(artist, dict) and artist.get("name")
                    ),
                    "yt_album": text_or_empty(dict_or_empty(match.get("album")).get("name")),
                    "score": score,
                    "result_type": text_or_empty(match.get("resultType")),
                })
            else:
                self.missing_tracks.append({**base_row, "score": score})
            
            self.progress = (index / len(self.tracks)) * 100
            yield {"index": index, "total": len(self.tracks), "progress": self.progress}

        self.status = "creating_playlist"
        playlist_name = self.playlist_name_override or playlist_meta["name"]
        
        # YouTube Music API sometimes rejects empty descriptions with HTTP 400 when using OAuth.
        playlist_description = self.playlist_description_override or playlist_meta.get("description")
        if not playlist_description or not str(playlist_description).strip():
            playlist_description = "Migrated from Spotify"
            
        privacy_status = "PUBLIC" if self.is_public else "PRIVATE"

        self.log(f"Creating YouTube Music playlist: {playlist_name} (Privacy: {privacy_status})")
        try:
            yt_playlist_id = await asyncio.to_thread(
                self.ytmusic.create_playlist,
                title=playlist_name,
                description=playlist_description,
                privacy_status=privacy_status,
            )
        except Exception as exc:
            self.status = "failed"
            self.log(f"Failed to create YT Music playlist: {exc}")
            if hasattr(exc, "response") and exc.response is not None:
                try:
                    error_json = exc.response.json()
                    self.log(f"Detailed API Error: {json.dumps(error_json, indent=2)}")
                except Exception:
                    self.log(f"Raw API Error Content: {exc.response.text}")
            raise

        self.log(f"Created playlist {yt_playlist_id}. Adding {len(video_ids)} tracks...")
        added_video_ids, failed_video_ids = await self.add_tracks_to_playlist(
            yt_playlist_id,
            video_ids,
        )
        if failed_video_ids:
            self.log(f"Added {len(added_video_ids)} tracks. Failed to add {len(failed_video_ids)} tracks.")
        else:
            self.log(f"Added all {len(added_video_ids)} tracks to the playlist.")

        self.summary = {
            "spotify_playlist_id": playlist_meta["id"],
            "spotify_playlist_name": playlist_meta["name"],
            "spotify_track_count": len(self.tracks),
            "matched_count": len(self.matched_tracks),
            "missing_count": len(self.missing_tracks),
            "added_to_playlist_count": len(added_video_ids),
            "failed_to_add_count": len(failed_video_ids),
            "yt_playlist_id": yt_playlist_id,
            "yt_playlist_url": f"https://music.youtube.com/playlist?list={yt_playlist_id}",
        }
        self.status = "completed"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        summary_filename = slugify_filename(f"{playlist_meta['name']}_{self.playlist_id}_summary") + ".json"
        summary_path = OUTPUT_DIR / summary_filename
        summary_path.write_text(json.dumps(self.summary, indent=2), encoding="utf-8")
        self.log(f"Wrote summary to {summary_path}")
        self.log("Migration completed successfully.")