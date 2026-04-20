# Spotify to YT Music - Architecture Overview

This project is a full-stack application designed to migrate Spotify playlists to YouTube Music without requiring Spotify API credentials. It operates by extracting playlist data directly from Spotify and using YouTube Music's API to recreate the playlist.

## Architectural Components

### 1. Backend (FastAPI)
- **Framework:** Built with FastAPI, which serves the API endpoints and also hosts the static files for the frontend.
- **Job Management:** Migrations are treated as background jobs. The backend manages an in-memory `jobs` store in `main.py` to track the status of these operations.
- **Authentication:** Implements a 'Limited Input Device' (TV-style) OAuth flow for YouTube Music. This allows users to authenticate via a code on a separate device without needing traditional web-based OAuth redirects.
- **Concurrency:** Leverages `asyncio` and FastAPI's `BackgroundTasks` for non-blocking migration processes, ensuring the server remains responsive.

### 2. Core Logic (`migrator.py`)
- **Spotify Extraction:** Uses a two-tier approach to get tracks from Spotify:
  1. It first attempts to scrape the public HTML of a Spotify playlist.
  2. If the playlist is large or dynamically loaded, it falls back to using **Playwright** to open a headless browser, scroll, and capture dynamically loaded tracks.
- **Matching Engine:** Employs a fuzzy matching algorithm (`search_best_match`). It scores candidate tracks based on title similarity, artist overlap, album name, and track duration to find the best match on YouTube Music.
- **YouTube Integration:** Uses the `ytmusicapi` library to search for tracks and manage playlists on the user's YouTube Music account.

### 3. Frontend (Next.js)
- **Framework:** A modern Next.js application located in the `frontend/` directory.
- **Styling & UI:** Uses Tailwind CSS for styling and Lucide React for icons.
- **Functionality:** Features a step-by-step wizard interface:
  1. Input Spotify URL and Google API Credentials.
  2. YouTube Auth (polling for completion).
  3. Migration Progress tracking.
  4. Completion screen.

### 4. Infrastructure & Deployment
- **Containerization:** The `Dockerfile` uses a multi-stage build process.
  - Stage 1 builds the Next.js frontend.
  - Stage 2 uses a Playwright-ready Python image to run the FastAPI backend and serve the static frontend files.
- **Cloud Ready:** Includes configuration (`app.yaml`) and documentation (`AZURE_DEPLOYMENT.md`, `GOOGLE_AUTH_SETUP.md`) for deployment on cloud platforms like Azure App Service or Google App Engine.

## Key Insights
- **Self-Hosting Focus:** The project is designed to be self-hosted or deployed as a private service. It requires users to provide their own Google Cloud Client ID/Secret.
- **Bypassing Spotify API:** The use of Playwright for scraping Spotify allows the application to bypass the need for Spotify API keys, avoiding restrictive quotas and official app registration processes.
- **Evolution:** The presence of `convert_async.py` and `spotify_to_ytmusic.py` (a CLI version) suggests the project evolved from a synchronous CLI tool into an asynchronous, containerized web service.

## Key Files
- `main.py`: Entry point for the backend, managing HTTP endpoints, background tasks, and OAuth sessions.
- `migrator.py`: Contains the core business logic for migrating playlists, including Spotify scraping and YouTube Music matching.
- `frontend/app/page.tsx`: The primary UI component managing the migration wizard.
- `Dockerfile`: Defines the multi-stage build for the containerized environment.
