# 🎵 Spotify to YouTube Music Playlist Replica
*The bridge for your music library migration.*

---

## **The Problem**
You've spent years curating the perfect 600-track playlist on Spotify, but you're ready to switch to YouTube Music. Rebuilding that library manually is a weekend-ruining task.

## **The Solution**
This high-performance Python CLI automates the migration with a focus on **reliability, transparency, and ease of use.** Unlike other tools, it doesn't require a Spotify Developer account or complex API keys to read your music.

---

## **✨ Key Features**

*   **Zero-Config Spotify Extraction:** Just point it at a public Spotify URL. It intelligently scrapes the playlist metadata and uses a browser-scrolling fallback for massive playlists that exceed standard API limits.
*   **Intelligent Song Matching:** Uses a multi-stage search strategy (Title + Artist, Artist + Title, Album inclusions) to find the highest-quality match on YouTube Music.
*   **Dry-Run Mode:** Test your migration before committing. See exactly what matches will be made without creating a single playlist.
*   **Audit-Ready Reporting:** Every migration generates a comprehensive suite of reports in the `output/` folder:
    *   `*_spotify_tracks.csv`: Your original library.
    *   `*_matched.csv`: Exactly what was found on YT Music.
    *   `*_missing.csv`: The "manual review" list for tracks that couldn't be found automatically.
    *   `*_summary.json`: A high-level success report.

---

## **🚀 The Workflow**

1.  **Authenticate:** One command to link your YouTube Music account via browser or OAuth.
2.  **Preview:** Run with `--limit 25 --dry-run` to verify matching quality.
3.  **Migrate:** Run the full script and watch your library appear on YouTube Music in minutes.

## **🛠️ Technical Specs**
*   **Language:** Python 3.12+
*   **Powerhouses:** `ytmusicapi` for the heavy lifting, `playwright` for smart browser extraction.
*   **Flexible:** Supports both Edge and Chrome browser channels for extraction.

---

**Ready to move?** 
Your music shouldn't be locked in. Give it a spin with:
```powershell
python .\spotify_to_ytmusic.py --spotify-playlist "[YOUR_URL]" --dry-run
```
