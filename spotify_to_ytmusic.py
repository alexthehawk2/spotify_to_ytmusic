from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests
from ytmusicapi import YTMusic


SEARCH_TYPES = ("songs", "videos")
SPOTIFY_PAGE_USER_AGENT = "Mozilla/5.0"


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replicate a public Spotify playlist into YouTube Music without Spotify API credentials."
    )
    parser.add_argument("--spotify-playlist", required=True, help="Public Spotify playlist URL or ID")
    parser.add_argument(
        "--yt-auth",
        default="browser.json",
        help="Path to YTMusic auth JSON created by ytmusicapi browser or oauth setup",
    )
    parser.add_argument(
        "--playlist-name",
        help="Target YouTube Music playlist name. Defaults to the Spotify playlist name.",
    )
    parser.add_argument(
        "--playlist-description",
        help="Target YouTube Music playlist description. Defaults to the Spotify playlist description.",
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="Create the YouTube Music playlist as public instead of private.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve matches and write reports without creating the YouTube Music playlist.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Only process the first N Spotify tracks. Useful for validation before migrating the full playlist.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.35,
        help="Delay between YT Music searches in seconds.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for migration reports and exported track list.",
    )
    parser.add_argument(
        "--spotify-browser-channel",
        default="msedge",
        choices=["msedge", "chrome", "chromium"],
        help="Browser channel used for Spotify extraction when the playlist exceeds the initial page payload.",
    )
    parser.add_argument(
        "--spotify-headless",
        action="store_true",
        help="Run the Spotify extraction browser headlessly.",
    )
    parser.add_argument(
        "--spotify-scroll-timeout",
        type=int,
        default=240,
        help="Max seconds to spend scrolling and collecting the full public playlist.",
    )
    parser.add_argument(
        "--min-extraction-rate",
        type=float,
        default=1.0,
        help="Minimum fraction of Spotify tracks that must be extracted before continuing. Use 0.95 for a 95%% gate.",
    )
    return parser.parse_args()


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\s.-]", "_", name).strip()
    return cleaned or "playlist"


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


def spotify_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SPOTIFY_PAGE_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def fetch_public_playlist_page(session: requests.Session, playlist_id: str) -> str:
    response = session.get(f"https://open.spotify.com/playlist/{playlist_id}", timeout=30)
    response.raise_for_status()
    return response.text


def decode_initial_state(html: str) -> dict[str, Any]:
    match = re.search(r'<script id="initialState" type="text/plain">(.*?)</script>', html, re.S)
    if not match:
        raise RuntimeError("Spotify public page did not include the expected initialState payload.")
    try:
        return json.loads(base64.b64decode(match.group(1)))
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


def fetch_remaining_tracks_with_browser(
    playlist_url: str,
    initial_tracks: list[SourceTrack],
    expected_total: int,
    current_market: str | None,
    browser_channel: str,
    headless: bool,
    timeout_seconds: int,
) -> list[SourceTrack]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright is not installed. Install it with `.venv\\Scripts\\python -m pip install playwright`."
        ) from exc

    track_catalog: dict[str, SourceTrack] = {track.spotify_track_id: track for track in initial_tracks}
    initial_ids = [track.spotify_track_id for track in initial_tracks]
    network_order: list[str] = []
    seen_page_sequences: set[tuple[str, ...]] = set()
    dom_order: list[str] = [track.spotify_track_id for track in initial_tracks]

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=browser_channel, headless=headless)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            user_agent=SPOTIFY_PAGE_USER_AGENT,
        )
        page = context.new_page()

        def on_response(response: Any) -> None:
            if "api-partner.spotify.com/pathfinder" not in response.url:
                return
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            try:
                payload = response.json()
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
        page.goto(playlist_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2_000)

        end_time = time.time() + timeout_seconds
        stagnant_loops = 0
        last_signature = (len(track_catalog), len(dom_order))

        while time.time() < end_time:
            visible_track_ids = extract_track_ids_from_dom(page)
            if len(visible_track_ids) > len(dom_order):
                dom_order = visible_track_ids

            if len(dom_order) >= expected_total:
                break

            page.evaluate(
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
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(1_200)

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

        browser.close()

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
            results = ytmusic.search(query, filter=search_type, limit=5)
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


def write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def source_track_row(track: SourceTrack) -> dict[str, Any]:
    row = asdict(track)
    row["artists"] = track.artist_text
    return row


def main() -> int:
    args = parse_args()
    if not 0 < args.min_extraction_rate <= 1:
        print("--min-extraction-rate must be between 0 and 1.", file=sys.stderr)
        return 1

    root_dir = Path.cwd()
    output_dir = root_dir / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    yt_auth_path = Path(args.yt_auth)
    if not yt_auth_path.is_absolute():
        yt_auth_path = root_dir / yt_auth_path
    if not yt_auth_path.exists():
        print(
            f"YouTube Music auth file not found at {yt_auth_path}. "
            "Create it with `.venv\\Scripts\\ytmusicapi.exe browser --file browser.json` "
            "or `.venv\\Scripts\\ytmusicapi.exe oauth --file oauth.json` first.",
            file=sys.stderr,
        )
        return 1

    playlist_id = extract_playlist_id(args.spotify_playlist)
    playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"

    try:
        html = fetch_public_playlist_page(spotify_session(), playlist_id)
        playlist, tracks, total_count, current_market = extract_public_playlist_from_html(html, playlist_id)
    except Exception as exc:
        print(f"Failed to load public Spotify playlist: {exc}", file=sys.stderr)
        return 1

    if total_count > len(tracks):
        try:
            tracks = fetch_remaining_tracks_with_browser(
                playlist_url=playlist_url,
                initial_tracks=tracks,
                expected_total=total_count,
                current_market=current_market,
                browser_channel=args.spotify_browser_channel,
                headless=args.spotify_headless,
                timeout_seconds=args.spotify_scroll_timeout,
            )
        except Exception as exc:
            print(
                "The public playlist loaded only partially from Spotify's initial page payload "
                f"({len(tracks)}/{total_count}) and browser fallback failed: {exc}",
                file=sys.stderr,
            )
            return 1

    extraction_rate = (len(tracks) / total_count) if total_count else 0.0
    if not args.limit and extraction_rate < args.min_extraction_rate:
        print(
            "Spotify extraction was incomplete after browser fallback: "
            f"got {len(tracks)} of {total_count} tracks "
            f"({extraction_rate:.2%}, required {args.min_extraction_rate:.2%}). "
            "Refusing to continue because that is below the configured minimum extraction rate. "
            "Retry with a longer `--spotify-scroll-timeout`, switch browser channel, "
            "or lower `--min-extraction-rate` if you accept a partial migration.",
            file=sys.stderr,
        )
        return 1

    if args.limit:
        tracks = tracks[: args.limit]

    if not tracks:
        print("No Spotify tracks found to migrate.", file=sys.stderr)
        return 1

    unavailable_in_market_count = sum(track.available_in_spotify_market is False for track in tracks)

    playlist_name = args.playlist_name or playlist["name"]
    playlist_description = args.playlist_description or (playlist.get("description") or "")
    safe_name = sanitize_filename(playlist_name)

    exported_tracks: list[dict[str, Any]] = []
    matched_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    video_ids: list[str] = []

    ytmusic = YTMusic(str(yt_auth_path))

    for index, track in enumerate(tracks, start=1):
        print(f"[{index}/{len(tracks)}] Resolving {track.name} - {track.artist_text}")
        video_id, match, score = search_best_match(ytmusic, track, args.delay)
        base_row = source_track_row(track)
        exported_tracks.append(base_row)

        if video_id and match:
            video_ids.append(video_id)
            matched_rows.append(
                {
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
                }
            )
        else:
            missing_rows.append({**base_row, "score": score})

    common_headers = [
        "spotify_track_id",
        "spotify_track_uri",
        "name",
        "artists",
        "album",
        "duration_ms",
        "explicit",
        "available_in_spotify_market",
        "spotify_url",
        "track_number",
    ]
    write_csv(output_dir / f"{safe_name}_spotify_tracks.csv", common_headers, exported_tracks)
    write_csv(
        output_dir / f"{safe_name}_matched.csv",
        common_headers + ["yt_video_id", "yt_title", "yt_artists", "yt_album", "score", "result_type"],
        matched_rows,
    )
    write_csv(output_dir / f"{safe_name}_missing.csv", common_headers + ["score"], missing_rows)

    summary = {
        "spotify_playlist_id": playlist["id"],
        "spotify_playlist_name": playlist["name"],
        "spotify_track_count": len(tracks),
        "spotify_track_count_expected": total_count,
        "spotify_extraction_rate": round(extraction_rate, 6),
        "spotify_min_extraction_rate_required": args.min_extraction_rate,
        "spotify_market": current_market,
        "spotify_unavailable_in_market_count": unavailable_in_market_count,
        "spotify_unexpected_missing_count": max(total_count - len(tracks), 0),
        "matched_count": len(matched_rows),
        "missing_count": len(missing_rows),
        "dry_run": args.dry_run,
        "spotify_extraction_mode": "public_page_plus_browser_fallback" if total_count > 30 else "public_page",
    }

    if args.dry_run:
        summary_path = output_dir / f"{safe_name}_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0

    privacy_status = "PUBLIC" if args.public else "PRIVATE"
    try:
        yt_playlist_id = ytmusic.create_playlist(
            title=playlist_name,
            description=playlist_description,
            privacy_status=privacy_status,
            video_ids=video_ids,
        )
    except Exception as exc:
        print(f"Failed to create YouTube Music playlist: {exc}", file=sys.stderr)
        return 1

    summary["yt_playlist_id"] = yt_playlist_id
    summary["privacy_status"] = privacy_status
    summary_path = output_dir / f"{safe_name}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
