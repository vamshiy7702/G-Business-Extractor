"use client";

import type { Place } from "@/lib/types";
import { safeHref } from "@/lib/api";

function mapsHref(item: Place): string | null {
  if (item.lat !== null && item.lng !== null) return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${item.lat},${item.lng}`)}`;
  return safeHref(item.website);
}

function detailsHref(item: Place): string | null {
  if (item.source === "google" && item.source_place_id) return `https://www.google.com/maps/search/?api=1&query=Google+Maps+place&query_place_id=${encodeURIComponent(item.source_place_id)}`;
  if (item.lat !== null && item.lng !== null) return `https://www.openstreetmap.org/?mlat=${encodeURIComponent(item.lat)}&mlon=${encodeURIComponent(item.lng)}#map=18/${encodeURIComponent(item.lat)}/${encodeURIComponent(item.lng)}`;
  return null;
}

interface Props {
  items: Place[];
  onRowSelect: (id: number, additive: boolean, range: boolean) => void;
  selectedIds: Set<number>;
  loading: boolean;
}

export default function GBResultsGrid({ items, onRowSelect, selectedIds, loading }: Props) {
  return (
    <div className={`gb-results-wrap ${loading ? "is-loading" : ""}`}>
      <table className="gb-results-table">
        <thead>
          <tr>
            <th>Category</th>
            <th>Real Category</th>
            <th>Business Name</th>
            <th>Address</th>
            <th>City</th>
            <th>State</th>
            <th>Postal Code</th>
            <th>Country</th>
            <th>Phone</th>
            <th>Email</th>
            <th>Website</th>
            <th>Latitude</th>
            <th>Longitude</th>
            <th>Map Link</th>
            <th>Details Link</th>
            <th>Average Rating</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const map = mapsHref(item);
            const details = detailsHref(item);
            const selected = selectedIds.has(item.id);
            return (
              <tr
                key={item.id}
                className={selected ? "selected" : ""}
                onClick={(event) => onRowSelect(item.id, event.ctrlKey || event.metaKey, event.shiftKey)}
                title="Click to select. Ctrl/Command-click for multiple rows. Shift-click selects a range."
              >
                <td>{item.category || ""}</td>
                <td>{item.category || ""}</td>
                <td className="cell-strong">{item.name || ""}</td>
                <td title={item.address || ""}>{item.address || ""}</td>
                <td>{item.city || ""}</td>
                <td>{item.state || ""}</td>
                <td>{item.postal_code || ""}</td>
                <td>{item.country || ""}</td>
                <td>{item.phone || ""}</td>
                <td className={item.email_status === "error" ? "cell-error" : ""}>{item.email || ""}</td>
                <td>{item.website ? <a href={safeHref(item.website) ?? undefined} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{item.website.replace(/^https?:\/\//, "").slice(0, 34)}</a> : ""}</td>
                <td>{item.lat === null ? "" : item.lat.toFixed(6)}</td>
                <td>{item.lng === null ? "" : item.lng.toFixed(6)}</td>
                <td>{map ? <a href={map} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>Open</a> : ""}</td>
                <td>{details ? <a href={details} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>Open</a> : ""}</td>
                <td>{item.rating === null ? "" : `${item.rating.toFixed(1)} ★`}</td>
              </tr>
            );
          })}
          {items.length === 0 && <tr><td colSpan={16} className="gb-empty-results">No results yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
