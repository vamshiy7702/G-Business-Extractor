"use client";

import { useEffect, useState } from "react";
import { getDiagnostics, getSettings } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";

export interface GBSettings {
  language: string;
  columns: Record<string, boolean>;
  extractEmails: boolean;
  resultsPerTile: number;
  maxPlaces: number;
  threads: number;
  autoExport: boolean;
  autoRestart: boolean;
  format: "csv" | "xlsx";
  separator: "," | ";";
  encoding: "UTF-8";
}

const COLUMNS = [
  "Category", "Real Category", "Business Name", "Full Address", "City", "State", "Postal Code",
  "Country", "Phone", "Email", "Website", "Latitude", "Longitude", "Map Link", "Details Link",
];

const DEFAULT_COLUMNS = Object.fromEntries(COLUMNS.map((c) => [c, true]));

interface Props {
  open: boolean;
  source: "osm" | "google";
  value: GBSettings;
  onChange: (value: GBSettings) => void;
  onClose: () => void;
}

export default function GBSettingsModal({ open, source, value, onChange, onClose }: Props) {
  const q = useQuery({ queryKey: ["settings"], queryFn: getSettings, enabled: open, staleTime: 30000 });
  const [tab, setTab] = useState<"data" | "connection">("data");
  const [draft, setDraft] = useState<GBSettings>(value);
  const diag = useQuery({ queryKey: ["diagnostics"], queryFn: getDiagnostics, enabled: false, retry: false });

  useEffect(() => {
    if (!open) {
      setTab("data");
      return;
    }
    setDraft({ ...value, columns: { ...DEFAULT_COLUMNS, ...value.columns } });
  }, [open, value]);

  if (!open) return null;

  function update<K extends keyof GBSettings>(key: K, next: GBSettings[K]) {
    setDraft((prev) => ({ ...prev, [key]: next }));
  }

  function close(save: boolean) {
    if (save) onChange(draft);
    onClose();
  }

  const settings = q.data;

  return (
    <div className="gb-modal-backdrop" onMouseDown={() => close(false)}>
      <div className="gb-settings-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="gb-modal-title">Settings</div>
        <div className="gb-tabs">
          <button className={tab === "data" ? "active" : ""} onClick={() => setTab("data")}>Data</button>
          <button className={tab === "connection" ? "active" : ""} onClick={() => setTab("connection")}>Connection</button>
        </div>

        {tab === "data" ? (
          <div className="gb-settings-body">
            <div className="gb-row gb-inline-row">
              <label>Interface language</label>
              <select value={draft.language} onChange={(e) => update("language", e.target.value)}>
                <option>English</option>
                <option>Italian</option>
                <option>Spanish</option>
              </select>
            </div>

            <div className="gb-settings-grid">
              <div>
                <div className="gb-section-caption">Columns to Export</div>
                <div className="gb-checkgrid">
                  {COLUMNS.map((column) => (
                    <label key={column}>
                      <input
                        type="checkbox"
                        checked={draft.columns[column]}
                        onChange={(e) => update("columns", { ...draft.columns, [column]: e.target.checked })}
                      /> {column}
                    </label>
                  ))}
                </div>
              </div>
              <div className="gb-settings-side">
                <label className="gb-checkline"><input type="checkbox" checked={draft.extractEmails} onChange={(e) => update("extractEmails", e.target.checked)} /> Extract email from website (slower app)</label>
                <div className="gb-field-row"><span>Number of results for each zip code</span><input type="number" min={1} max={1000} value={draft.resultsPerTile} onChange={(e) => update("resultsPerTile", Math.max(1, Math.min(1000, Number(e.target.value) || 1)))} /></div>
                <div className="gb-field-row"><span>Max results for each task</span><input type="number" min={1} max={5000} value={draft.maxPlaces ?? 500} onChange={(e) => update("maxPlaces", Math.max(1, Math.min(5000, Number(e.target.value) || 1)))} /></div>
                <div className="gb-field-row"><span>Threads</span><input type="number" min={1} max={10} value={draft.threads} onChange={(e) => update("threads", Math.max(1, Math.min(10, Number(e.target.value) || 1)))} /></div>
                <div className="gb-button-row"><button className="gb-settings-action" onClick={() => update("autoExport", !draft.autoExport)}>Auto Export Folder</button><span className={draft.autoExport ? "gb-toggle-on" : "gb-toggle-off"}>{draft.autoExport ? "ON" : "OFF"}</span></div>
                <label className="gb-checkline"><input type="checkbox" checked={draft.autoRestart} onChange={(e) => update("autoRestart", e.target.checked)} /> Auto Restart and Scan</label>
                <div className="gb-field-row"><span>File format for data export</span><select value={draft.format} onChange={(e) => update("format", e.target.value as "csv" | "xlsx")}><option value="csv">CSV (comma separated file)</option><option value="xlsx">XLSX (Excel workbook)</option></select></div>
                <div className="gb-field-row"><span>CSV file columns separator</span><select value={draft.separator} onChange={(e) => update("separator", e.target.value as "," | ";")}><option value=",">, comma</option><option value=";">; semicolon</option></select></div>
                <div className="gb-field-row"><span>Encoding</span><select value={draft.encoding} onChange={(e) => update("encoding", e.target.value as "UTF-8")}><option>UTF-8</option></select></div>
              </div>
            </div>
          </div>
        ) : (
          <div className="gb-settings-body gb-connection-body">
            <div className="gb-connection-card"><span>Current source</span><strong>{source === "google" ? "Google Maps" : "OpenStreetMap / Overpass"}</strong></div>
            <div className="gb-connection-card"><span>Google API key</span><strong>{settings?.google_api_key_configured ? "Configured on server" : "Not configured"}</strong></div>
            <div className="gb-connection-card"><span>Google free cap</span><strong>{settings?.google_text_search_free_cap?.toLocaleString() ?? "—"} calls / month</strong></div>
            <div className="gb-connection-card"><span>Microsoft/Bing source</span><strong>Bing Maps Local Search is a legacy service; current free access is retired.</strong></div>
            <div className="gb-connection-card"><span>Connection test</span>
              <strong>
                <button className="gb-settings-action" onClick={() => void diag.refetch()} disabled={diag.isFetching}>{diag.isFetching ? "Testing…" : "Test connections"}</button>
              </strong>
            </div>
            {diag.error && <div className="gb-connection-note gb-hint-error">The backend did not answer: {diag.error instanceof Error ? diag.error.message : String(diag.error)}. Is it running on the API URL?</div>}
            {diag.data && (
              <div className="gb-diag">
                {diag.data.checks.map((c) => (
                  <div key={c.service} className={c.ok ? "ok" : "bad"}>{c.ok ? "✓" : "✗"} {c.service}: {c.message}{c.ok ? ` (${c.ms} ms)` : ""}</div>
                ))}
                <div className={diag.data.contact_email_set ? "ok" : "bad"}>{diag.data.contact_email_set ? "✓" : "✗"} CONTACT_EMAIL {diag.data.contact_email_set ? "is set" : "is empty. Set it in backend/.env (OpenStreetMap servers ask for a way to contact you)."}</div>
                <div className={diag.data.locations_database ? "ok" : "bad"}>{diag.data.locations_database ? "✓" : "✗"} Location database {diag.data.locations_database ? "found" : "missing: run python scripts/build_locations.py"}</div>
                <div className="note">{diag.data.env_file_loaded_hint}</div>
              </div>
            )}
            <div className="gb-connection-note">API credentials stay on the backend. The browser never receives the Google API key.</div>
          </div>
        )}

        <div className="gb-modal-footer">
          <button className="gb-btn gb-btn-primary" onClick={() => close(true)}>✓ Ok</button>
          <button className="gb-btn" onClick={() => close(false)}>✕ Cancel</button>
        </div>
      </div>
    </div>
  );
}
