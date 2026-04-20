import asyncio
import uuid
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from migrator import PlaylistMigrator
from ytmusicapi.auth.oauth import OAuthCredentials

app = FastAPI(title="Spotify to YT Music API")

# Configure CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for jobs and auth sessions
jobs: Dict[str, PlaylistMigrator] = {}
auth_sessions: Dict[str, Dict[str, Any]] = {}

# Default Google OAuth Client ID/Secret for YT Music (Android client)
# Users should ideally provide their own via environment variables
DEFAULT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "861556724134-cl8unskiohcnbe0sbqn67987779f7p09.apps.googleusercontent.com")
DEFAULT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "dwu9db6uY686WwhS-S7v5Y9e")

class MigrationRequest(BaseModel):
    spotify_playlist_url: str
    yt_auth: Dict[str, Any]
    playlist_name: Optional[str] = None
    playlist_description: Optional[str] = None
    is_public: bool = False

class AuthStartResponse(BaseModel):
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int

class AuthStartRequest(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None

class AuthPollRequest(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None

@app.post("/api/auth/start", response_model=AuthStartResponse)
async def auth_start(request: AuthStartRequest):
    client_id = request.client_id or DEFAULT_CLIENT_ID
    client_secret = request.client_secret or DEFAULT_CLIENT_SECRET
    
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Client ID and Client Secret are required")
        
    try:
        credentials = OAuthCredentials(client_id, client_secret)
        code = credentials.get_code()
        # code contains: device_code, user_code, verification_url, expires_in, interval
        auth_sessions[code["device_code"]] = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret
        }
        return code
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/poll/{device_code}")
async def auth_poll(device_code: str):
    if device_code not in auth_sessions:
        raise HTTPException(status_code=404, detail="Auth session not found")
    
    session = auth_sessions[device_code]
    credentials = OAuthCredentials(session["client_id"], session["client_secret"])
    try:
        token = credentials.token_from_code(device_code)
        if token and "access_token" in token:
            # Include client credentials in the token dict so they can be reused for refreshing
            token["client_id"] = session["client_id"]
            token["client_secret"] = session["client_secret"]
            return {"status": "success", "auth": token}
        else:
            return {"status": "pending"}
    except Exception as e:
        if "authorization_pending" in str(e):
            return {"status": "pending"}
        return {"status": "pending"}

async def run_migration_task(job_id: str):
    migrator = jobs[job_id]
    try:
        # migrator.run() is an async generator
        async for progress in migrator.run():
            # The migrator updates its own status, progress, and logs
            pass
    except Exception as e:
        migrator.status = "failed"
        migrator.log(f"Unhandled error in background task: {e}")

@app.post("/api/jobs")
async def create_job(request: MigrationRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    migrator = PlaylistMigrator(
        spotify_playlist_url=request.spotify_playlist_url,
        yt_auth=request.yt_auth,
        playlist_name_override=request.playlist_name,
        playlist_description_override=request.playlist_description,
        is_public=request.is_public,
        spotify_headless=True,
    )
    jobs[job_id] = migrator
    background_tasks.add_task(run_migration_task, job_id)
    return {"job_id": job_id}

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    migrator = jobs[job_id]
    return {
        "job_id": job_id,
        "status": migrator.status,
        "progress": migrator.progress,
        "logs": migrator.logs,
        "summary": migrator.summary,
        "matched_count": len(migrator.matched_tracks),
        "missing_count": len(migrator.missing_tracks),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
