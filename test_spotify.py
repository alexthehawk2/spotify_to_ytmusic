import asyncio
from migrator import PlaylistMigrator
import json

async def test_extraction():
    # Use a popular public playlist
    playlist_url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM3M" # Today's Top Hits
    
    # We don't need real YT auth just to test extraction
    # But PlaylistMigrator __init__ calls YTMusic(auth=...)
    # I'll pass a dummy string
    try:
        migrator = PlaylistMigrator(
            spotify_playlist_url=playlist_url,
            yt_auth=None,
            limit=5
        )
        print("Migrator initialized")
        
        # Test extraction (first part of run())
        # We can't easily run just part of the generator without it trying to match
        # So we'll just run it and expect matching to fail (which is fine)
        
        async for update in migrator.run():
            print(f"Progress: {update['progress']}%")
            if migrator.status == "matching":
                print(f"Extracted {len(migrator.tracks)} tracks")
                break
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_extraction())
