import sys

with open('migrator.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace imports
content = content.replace('from typing import Any, Callable, Generator', 'from typing import Any, Callable, AsyncGenerator')
content = content.replace('import requests', 'import httpx')

# Update spotify_session
old_session = """def spotify_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SPOTIFY_PAGE_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session"""

new_session = """async def spotify_session() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={
            "User-Agent": SPOTIFY_PAGE_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=30.0,
        follow_redirects=True
    )"""
content = content.replace(old_session, new_session)

# Update fetch_public_playlist_page
old_fetch = """def fetch_public_playlist_page(session: requests.Session, playlist_id: str) -> str:
    url = f"https://open.spotify.com/playlist/{playlist_id}"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    # Log the length and a bit of the content for debugging
    print(f"Fetched {len(response.text)} bytes from {url}")
    return response.text"""

new_fetch = """async def fetch_public_playlist_page(client: httpx.AsyncClient, playlist_id: str) -> str:
    url = f"https://open.spotify.com/playlist/{playlist_id}"
    response = await client.get(url)
    response.raise_for_status()
    # Log the length and a bit of the content for debugging
    print(f"Fetched {len(response.text)} bytes from {url}")
    return response.text"""
content = content.replace(old_fetch, new_fetch)

# Update fetch_remaining_tracks_with_browser
old_browser = """def fetch_remaining_tracks_with_browser(
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
            "playwright is not installed. Install it with `pip install playwright`."
        ) from exc

    track_catalog: dict[str, SourceTrack] = {track.spotify_track_id: track for track in initial_tracks}
    initial_ids = [track.spotify_track_id for track in initial_tracks]
    network_order: list[str] = []
    seen_page_sequences: set[tuple[str, ...]] = set()
    dom_order: list[str] = [track.spotify_track_id for track in initial_tracks]

    with sync_playwright() as p:
        # Note: In Azure, we likely need to use 'chromium' and may not have other channels installed.
        # But we'll respect the parameter.
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
                \"\"\"() => {
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
                }\"\"\"
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

        browser.close()"""

new_browser = """async def fetch_remaining_tracks_with_browser(
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
                \"\"\"() => Array.from(document.querySelectorAll('a[href*="/track/"]'))
                    .map((a) => a.getAttribute('href') || '')
                    .filter(Boolean)\"\"\"
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
                \"\"\"() => {
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
                }\"\"\"
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

        await browser.close()"""
content = content.replace(old_browser, new_browser)

# Update PlaylistMigrator.run
old_run = """    def run(self) -> Generator[dict[str, Any], None, dict[str, Any]]:
        self.status = "extracting"
        self.log(f"Fetching Spotify playlist: {self.playlist_id}")
        
        playlist_meta = None
        tracks = []
        total_count = 0
        current_market = None

        try:
            session = spotify_session()
            html = fetch_public_playlist_page(session, self.playlist_id)
            if len(html) > 10000: # Simple heuristic for "real" page
                playlist_meta, tracks, total_count, current_market = extract_public_playlist_from_html(html, self.playlist_id)
            else:
                self.log("Initial request returned minimal data. Using browser extraction...")
        except Exception as exc:
            self.log(f"Initial request failed: {exc}. Using browser extraction...")

        if not tracks or total_count > len(tracks):
            self.log(f"Extraction partial or failed ({len(tracks)}/{total_count}). Starting browser extraction...")
            try:
                # If we don't even have metadata, we need to handle that in fetch_remaining_tracks_with_browser
                # Or just ensure it works.
                tracks = fetch_remaining_tracks_with_browser(
                    playlist_url=f"https://open.spotify.com/playlist/{self.playlist_id}",
                    initial_tracks=tracks,
                    expected_total=total_count or 100, # Fallback if we don't know total
                    current_market=current_market,
                    browser_channel=self.spotify_browser_channel,
                    headless=self.spotify_headless,
                    timeout_seconds=self.spotify_scroll_timeout,
                )
                
                # If we still don't have metadata (name), try to get it from tracks
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
            video_id, match, score = search_best_match(self.ytmusic, track, self.delay)
            
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
        playlist_description = self.playlist_description_override or (playlist_meta.get("description") or "")
        privacy_status = "PUBLIC" if self.is_public else "PRIVATE"

        self.log(f"Creating YouTube Music playlist: {playlist_name}")
        try:
            yt_playlist_id = self.ytmusic.create_playlist(
                title=playlist_name,
                description=playlist_description,
                privacy_status=privacy_status,
                video_ids=video_ids,
            )
        except Exception as exc:
            self.status = "failed"
            self.log(f"Failed to create YT Music playlist: {exc}")
            raise"""

new_run = """    async def run(self) -> AsyncGenerator[dict[str, Any], None]:
        self.status = "extracting"
        self.log(f"Fetching Spotify playlist: {self.playlist_id}")
        
        playlist_meta = None
        tracks = []
        total_count = 0
        current_market = None

        try:
            async with await spotify_session() as client:
                html = await fetch_public_playlist_page(client, self.playlist_id)
                if len(html) > 10000: # Simple heuristic for "real" page
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
            video_id, match, score = await asyncio.to_thread(search_best_match, self.ytmusic, track, self.delay)
            
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
        playlist_description = self.playlist_description_override or (playlist_meta.get("description") or "")
        privacy_status = "PUBLIC" if self.is_public else "PRIVATE"

        self.log(f"Creating YouTube Music playlist: {playlist_name}")
        try:
            yt_playlist_id = await asyncio.to_thread(
                self.ytmusic.create_playlist,
                title=playlist_name,
                description=playlist_description,
                privacy_status=privacy_status,
                video_ids=video_ids,
            )
        except Exception as exc:
            self.status = "failed"
            self.log(f"Failed to create YT Music playlist: {exc}")
            raise"""
content = content.replace(old_run, new_run)

with open('migrator.py', 'w', encoding='utf-8') as f:
    f.write(content)
