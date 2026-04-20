"use client";

import { useState, useEffect } from "react";
import { Music, ArrowRight, Loader2, CheckCircle2, AlertCircle, ExternalLink, Settings, Info } from "lucide-react";

const API_BASE = "http://localhost:8000";

export default function Home() {
  const [step, setStep] = useState(1);
  const [spotifyUrl, setSpotifyUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(true);
  
  const [authInfo, setAuthInfo] = useState<any>(null);
  const [ytAuthToken, setYtAuthToken] = useState<any>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startAuth = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/auth/start`, { 
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId || null,
          client_secret: clientSecret || null,
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Authentication failed");
      setAuthInfo(data);
      setStep(2);
    } catch (err: any) {
      setError(err.message || "Failed to start YouTube authentication");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (step === 2 && authInfo?.device_code && !ytAuthToken) {
      interval = setInterval(async () => {
        try {
          const res = await fetch(`${API_BASE}/api/auth/poll/${authInfo.device_code}`, { method: "POST" });
          const data = await res.json();
          if (data.status === "success") {
            setYtAuthToken(data.auth);
            setStep(3);
            clearInterval(interval);
          }
        } catch (err) {
          console.error("Polling error", err);
        }
      }, (authInfo.interval || 5) * 1000);
    }
    return () => clearInterval(interval);
  }, [step, authInfo, ytAuthToken]);

  const startMigration = async () => {
    if (!spotifyUrl) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          spotify_playlist_url: spotifyUrl,
          yt_auth: ytAuthToken,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Failed to start migration");
      }
      setJobId(data.job_id);
      setStep(4);
    } catch (err: any) {
      setError(err.message || "Failed to start migration");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (step === 4 && jobId && jobStatus?.status !== "completed" && jobStatus?.status !== "failed") {
      interval = setInterval(async () => {
        try {
          const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
          const data = await res.json();
          setJobStatus(data);
          if (data.status === "completed" || data.status === "failed") {
            clearInterval(interval);
          }
        } catch (err) {
          console.error("Job polling error", err);
        }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [step, jobId, jobStatus]);

  return (
    <main className="max-w-4xl mx-auto px-4 py-12">
      <header className="text-center mb-12">
        <h1 className="text-4xl font-bold mb-4 flex items-center justify-center gap-3">
          <Music className="text-green-500 w-10 h-10" />
          Spotify to YT Music
        </h1>
        <p className="text-slate-400 text-lg">
          Migrate your playlists seamlessly between platforms.
        </p>
      </header>

      <div className="bg-slate-900 rounded-2xl p-8 shadow-xl border border-slate-800">
        {error && (
          <div className="mb-6 bg-red-500/10 border border-red-500/50 text-red-500 p-4 rounded-lg flex items-center gap-3">
            <AlertCircle />
            <div className="flex-1">
              <p className="font-bold">Error</p>
              <p className="text-sm">{error}</p>
              {error.includes("OAuth client failure") && (
                <p className="mt-2 text-xs opacity-80">
                  Tip: Check your Google Cloud Credentials below. Google has recently disabled many default community client IDs.
                </p>
              )}
            </div>
          </div>
        )}

        {/* Step 1: URL Input */}
        {step === 1 && (
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-medium mb-2">Spotify Playlist URL</label>
              <input
                type="text"
                placeholder="https://open.spotify.com/playlist/..."
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-3 focus:outline-none focus:ring-2 focus:ring-green-500 transition-all text-slate-100"
                value={spotifyUrl}
                onChange={(e) => setSpotifyUrl(e.target.value)}
              />
            </div>

            <div className="border-t border-slate-800 pt-4">
              <button 
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-2 text-slate-400 hover:text-slate-200 text-sm transition-colors mb-4"
              >
                <Settings size={16} />
                {showAdvanced ? "Hide Google Cloud Credentials" : "Show Google Cloud Credentials (Required)"}
              </button>

              {showAdvanced && (
                <div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-300">
                  <div className="bg-blue-500/5 border border-blue-500/30 p-4 rounded-lg flex gap-3 text-sm text-blue-200 mb-2">
                    <Info className="shrink-0" size={20} />
                    <div>
                      <p className="font-semibold mb-1">Why do I need this?</p>
                      <p className="opacity-80">Google has Tightened restrictions. You now need your own "TV and Limited Input Device" client ID from the Google Cloud Console.</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-slate-500 mb-1 uppercase tracking-wider">Client ID</label>
                      <input
                        type="text"
                        placeholder="...apps.googleusercontent.com"
                        className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-green-500 transition-all text-sm text-slate-200"
                        value={clientId}
                        onChange={(e) => setClientId(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-500 mb-1 uppercase tracking-wider">Client Secret</label>
                      <input
                        type="password"
                        placeholder="Your Client Secret"
                        className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-green-500 transition-all text-sm text-slate-200"
                        value={clientSecret}
                        onChange={(e) => setClientSecret(e.target.value)}
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>

            <button
              onClick={startAuth}
              disabled={!spotifyUrl || !clientId || !clientSecret || loading}
              className="w-full bg-green-500 hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed text-slate-950 font-bold py-4 rounded-lg transition-colors flex items-center justify-center gap-2 text-lg"
            >
              {loading ? <Loader2 className="animate-spin" /> : "Connect YouTube Music"}
              <ArrowRight size={20} />
            </button>
          </div>
        )}

        {/* Step 2: Auth Flow */}
        {step === 2 && authInfo && (
          <div className="text-center space-y-6">
            <h2 className="text-2xl font-semibold">Authenticate with Google</h2>
            <div className="bg-slate-950 p-6 rounded-xl border border-slate-800">
              <p className="text-slate-400 mb-4">Visit the link below and enter the code:</p>
              <div className="text-4xl font-mono tracking-widest text-green-400 mb-6 bg-slate-900 p-4 rounded-lg border border-slate-700">
                {authInfo.user_code}
              </div>
              <a
                href={`${authInfo.verification_url}?user_code=${authInfo.user_code}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-green-500 hover:underline text-lg font-medium"
              >
                Open Google Activation <ExternalLink size={18} />
              </a>
            </div>
            <div className="flex items-center justify-center gap-3 text-slate-400">
              <Loader2 className="animate-spin" size={20} />
              Waiting for you to authorize...
            </div>
          </div>
        )}

        {/* Step 3: Review & Start */}
        {step === 3 && (
          <div className="text-center space-y-6">
            <div className="flex justify-center">
              <CheckCircle2 className="text-green-500 w-16 h-16" />
            </div>
            <h2 className="text-2xl font-semibold">Ready to Migrate!</h2>
            <p className="text-slate-400">
              YouTube Music connected. Click below to start the migration of your Spotify playlist.
            </p>
            <button
              onClick={startMigration}
              disabled={loading}
              className="w-full bg-green-500 hover:bg-green-600 disabled:opacity-50 text-slate-950 font-bold py-4 rounded-lg transition-colors text-lg"
            >
              {loading ? "Starting..." : "Start Migration"}
            </button>
          </div>
        )}

        {/* Step 4: Progress */}
        {step === 4 && jobStatus && (
          <div className="space-y-8">
            <div className="flex items-center justify-between">
              <h2 className="text-2xl font-semibold capitalize">{jobStatus.status.replace("_", " ")}...</h2>
              <span className="text-green-500 font-mono text-xl">{Math.round(jobStatus.progress)}%</span>
            </div>
            
            <div className="w-full bg-slate-950 rounded-full h-4 overflow-hidden border border-slate-800">
              <div 
                className="bg-green-500 h-full transition-all duration-500" 
                style={{ width: `${jobStatus.progress}%` }}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
                <div className="text-slate-500 text-sm mb-1">Matched Tracks</div>
                <div className="text-2xl font-bold text-green-400">{jobStatus.matched_count}</div>
              </div>
              <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
                <div className="text-slate-500 text-sm mb-1">Missing Tracks</div>
                <div className="text-2xl font-bold text-red-400">{jobStatus.missing_count}</div>
              </div>
            </div>

            <div className="bg-slate-950 rounded-xl p-4 border border-slate-800 max-h-60 overflow-y-auto font-mono text-xs text-slate-400">
              {jobStatus.logs.slice(-10).map((log: string, i: number) => (
                <div key={i} className="mb-1">{log}</div>
              ))}
            </div>

            {jobStatus.status === "completed" && jobStatus.summary && (
              <div className="pt-4">
                <a
                  href={jobStatus.summary.yt_playlist_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="w-full bg-green-500 hover:bg-green-600 text-slate-950 font-bold py-4 rounded-lg transition-colors flex items-center justify-center gap-2 text-lg"
                >
                  View Playlist on YT Music <ExternalLink size={20} />
                </a>
                <button 
                  onClick={() => setStep(1)}
                  className="w-full mt-4 text-slate-400 hover:text-slate-200 transition-colors"
                >
                  Start New Migration
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <footer className="mt-12 text-center text-slate-500 text-sm">
        Built for Azure Free Tier. Playwright powered.
      </footer>
    </main>
  );
}
