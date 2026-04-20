# Bug Report: Migrator Ignores User OAuth Credentials

## Description
Even though the user performs an OAuth login flow (Limited Input Device) and the frontend correctly passes their credentials (`yt_auth`) to the `/api/jobs` endpoint, the `PlaylistMigrator` class never uses them. Instead, it forcefully falls back to using the server's `browser.json` file.

This means that all migrations are currently executed using the YouTube account associated with the server's `browser.json`, rather than the authenticated user's account.

## Technical Details
1. **The Intent:** The API endpoint `create_job` in `main.py` correctly passes `request.yt_auth` to the `PlaylistMigrator` constructor:
   ```python
   migrator = PlaylistMigrator(
       spotify_playlist_url=request.spotify_playlist_url,
       yt_auth=request.yt_auth,
       ...
   )
   ```
2. **The Bug:** Inside `migrator.py`, `PlaylistMigrator.__init__` accepts and stores `self.yt_auth = yt_auth`, but it is completely ignored during the initialization of the `YTMusic` client:
   ```python
   # self.yt_auth is stored but never used
   self.yt_auth = yt_auth

   # It is hardcoded to look for browser.json instead
   browser_auth_path = runtime_browser_auth_path() or DEFAULT_BROWSER_AUTH_PATH
   if browser_auth_path.exists():
       self.ytmusic = YTMusic(str(browser_auth_path))
   ```

## Solution
Modify `PlaylistMigrator.__init__` in `migrator.py` to first check if `self.yt_auth` is provided. If so, initialize `YTMusic` using `self.yt_auth` (converted to a JSON string if it's a dictionary). If `self.yt_auth` is not provided, then fall back to the existing `browser.json` logic.
