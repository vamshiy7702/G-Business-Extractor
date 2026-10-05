"use client";

import { useQuery } from "@tanstack/react-query";
import { getHealth, getSettings } from "@/lib/api";

interface Props {
  source: "osm" | "google";
  onSourceChange: (source: "osm" | "google") => void;
  onStart: () => void;
  onStop: () => void;
  onSettings: () => void;
  onAutoExport: () => void;
  onAutoRestart: () => void;
}

export default function GBusinessToolbar({
  source,
  onSourceChange,
  onStart,
  onStop,
  onSettings,
  onAutoExport,
  onAutoRestart,
}: Props) {
  const settings = useQuery({ queryKey: ["settings"], queryFn: getSettings, staleTime: 30000 });
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, refetchInterval: 15000, retry: false });

  function openWebsite() {
    window.open("https://www.estrattoredati.com/local-business-extractor.html", "_blank", "noopener,noreferrer");
  }

  function openUpdates() {
    window.open("https://www.estrattoredati.com/local-business-extractor.html", "_blank", "noopener,noreferrer");
  }

  function openBuy() {
    window.open("https://www.estrattoredati.com/buy-now.html", "_blank", "noopener,noreferrer");
  }

  const googleConfigured = Boolean(settings.data?.google_api_key_configured);

  return (
    <header className="gb-windowbar">
      <div className="gb-window-title">G-Business Extractor Plus 7.8.0 | B2B Leads Extractor</div>

      <button className="gb-toolbtn gb-start" onClick={onStart} title="Start selected or queued tasks">
        <span className="gb-tool-icon gb-play-icon">▶</span> Start
      </button>
      <button className="gb-toolbtn gb-stop" onClick={onStop} title="Stop selected running tasks">
        <span className="gb-tool-icon gb-stop-icon">●</span> Stop
      </button>
      <button className="gb-toolbtn" onClick={openWebsite} title="Open product website">
        <span className="gb-tool-icon">🌐</span> Go to Website
      </button>
      <button className="gb-toolbtn" onClick={onSettings} title="Open application settings">
        <span className="gb-tool-icon">⚙</span> Settings
      </button>
      <button className="gb-toolbtn" onClick={onAutoExport} title="Toggle automatic export after a completed scan">
        <span className="gb-tool-icon">↳</span> AutoExport
      </button>
      <button className="gb-toolbtn" onClick={onAutoRestart} title="Toggle auto restart preference">
        <span className="gb-tool-icon">↻</span> AutoRestart
      </button>
      <button className="gb-toolbtn" onClick={openUpdates} title="Open the official product page for updates">
        <span className="gb-tool-icon">⟳</span> Get updates
      </button>
      <button className="gb-toolbtn gb-muted" disabled title="License registration is not part of this local implementation">
        <span className="gb-tool-icon">🔑</span> Register
      </button>
      <button className="gb-toolbtn gb-buy" onClick={openBuy} title="Open the official purchase page">
        <span className="gb-tool-icon">🛒</span> Buy Full Version
      </button>

      <div className="gb-source-selector">
        <label htmlFor="source-select">DATA SOURCE:</label>
        <select
          id="source-select"
          value={source}
          onChange={(e) => onSourceChange(e.target.value as "osm" | "google")}
          title={!googleConfigured && source === "google" ? "Google key is not configured on the backend" : undefined}
        >
          <option value="osm">OpenStreetMap (free)</option>
          <option value="google">Google Maps{googleConfigured ? "" : " (needs API key)"}</option>
          <option value="bing" disabled>Bing Maps (legacy)</option>
        </select>
        <span
          className={`gb-health ${health.isSuccess ? "ok" : health.isLoading ? "pending" : "bad"}`}
          title={health.isSuccess ? "FastAPI connected" : health.isLoading ? "Checking API" : "FastAPI unavailable"}
        />
      </div>
    </header>
  );
}
