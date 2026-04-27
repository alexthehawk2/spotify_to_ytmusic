# Spotify to YouTube Music Playlist Replica

This repo contains a Python CLI that reads a public Spotify playlist without Spotify API credentials, searches for the closest matches on YouTube Music, and creates a replica playlist there.

It is designed for large playlists like your 600-track case and writes reports for:

- every Spotify track exported
- every track successfully matched to YouTube Music
- every track that could not be matched automatically

## What You Need

1. A public Spotify playlist URL.
2. A YouTube Music auth file so the script can create a playlist in your account.
3. Python 3.12+.
4. A local Chrome or Edge installation for the browser fallback used on large playlists.

## Setup

Install dependencies:

```powershell
python -m venv.venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Create YouTube Music Auth

You can use either method below.

#### Option A: Browser Auth

This is usually the quickest path for personal playlist migration.

```powershell
.venv\Scripts\ytmusicapi.exe browser --file browser.json
```

#### Option B: OAuth

If you prefer OAuth, create Google API credentials and then run:

```powershell
.venv\Scripts\ytmusicapi.exe oauth --file oauth.json
```

Save the resulting file in this repo, or pass a different path with `--yt-auth`.

## Usage

Dry-run first on a subset:

```powershell
python.\spotify_to_ytmusic.py `
  --spotify-playlist "https://open.spotify.com/playlist/YOUR_PLAYLIST_ID" `
  --limit 25 `
  --dry-run
```

Create the full replica playlist:

```powershell
python.\spotify_to_ytmusic.py `
  --spotify-playlist "https://open.spotify.com/playlist/YOUR_PLAYLIST_ID"
```

If you used OAuth auth instead of browser auth:

```powershell
python.\spotify_to_ytmusic.py `
  --spotify-playlist "https://open.spotify.com/playlist/YOUR_PLAYLIST_ID" `
  --yt-auth.\oauth.json
```

If you need Chrome instead of Edge for Spotify extraction:

```powershell
python.\spotify_to_ytmusic.py `
  --spotify-playlist "https://open.spotify.com/playlist/YOUR_PLAYLIST_ID" `
  --spotify-browser-channel chrome
```

If you are willing to proceed when at least 95% of the Spotify playlist is extracted:

```powershell
python.\spotify_to_ytmusic.py `
  --spotify-playlist "https://open.spotify.com/playlist/YOUR_PLAYLIST_ID" `
  --min-extraction-rate 0.95
```

Create it as public and override the name:

```powershell
python.\spotify_to_ytmusic.py `
  --spotify-playlist "https://open.spotify.com/playlist/YOUR_PLAYLIST_ID" `
  --playlist-name "My Spotify Replica" `
  --public
```

## Output

The script writes reports to `output/`:

- `*_spotify_tracks.csv`: every source Spotify track
- `*_matched.csv`: matches chosen for YouTube Music
- `*_missing.csv`: tracks that need manual review
- `*_summary.json`: summary and created playlist ID

## Reliability Strategy

Spotify extraction attempts:

1. Read the playlist metadata and first track page from Spotify's encoded `initialState` payload.
2. If the playlist is larger than that initial payload, open the public playlist in a local browser and collect the remaining tracks while scrolling.
3. Fail with an explicit error if Spotify no longer exposes enough data to safely continue.
4. Optionally allow a partial migration by lowering `--min-extraction-rate` from the default `1.0`.

YouTube Music matching attempts:

1. Search by title + primary artist.
2. Search by artist + title.
3. Search by title + artist + album.
4. Prefer `song` results, but allow `video` results when they score best.

This is intentionally conservative. Some songs will still require manual review because Spotify and YouTube Music catalogs are not identical.

## Recommended Workflow For 600 Tracks

1. Run `--limit 25 --dry-run` to confirm auth and matching quality.
2. Run `--dry-run` on the full playlist and inspect `output\*_missing.csv`.
3. Run the full import once you are satisfied with the matches.

## Limitations

- The playlist must be public on Spotify.
- The script creates a new YouTube Music playlist. It does not update an existing one.
- Matching is best-effort and may choose alternate uploads, live versions, or videos for some songs.
- Private or region-locked catalog differences can still leave some tracks unmatched.

## Deployment

### Build and Push Docker Image

1. Build the Docker image:

```bash
docker build -t spotify-to-ytmusic.
```

2. Push the image to GitHub Container Registry (GHCR):

```bash
docker tag spotify-to-ytmusic ghcr.io/<your-username>/spotify-to-ytmusic:latest
docker push ghcr.io/<your-username>/spotify-to-ytmusic:latest
```

### Create a New Revision on Azure

1. Create a new revision on Azure using the Azure CLI:

```bash
az webapp deployment source config-local-git --name <your-app-name> --resource-group <your-resource-group>
git remote add azure <azure-git-url>
git push azure main
