"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export interface SSOption { value: string; label: string; }

interface Props {
  id?: string;
  options: SSOption[];
  value: string;                 // "" means the "All ..." choice
  allLabel: string;              // text for the empty/"All" choice, e.g. "All states"
  onChange: (value: string) => void;
  disabled?: boolean;
  loading?: boolean;
  placeholder?: string;
  maxVisible?: number;
}

/** Searchable dropdown: type to filter thousands of options (cities) without freezing the page. */
export default function SearchSelect({ id, options, value, allLabel, onChange, disabled, loading, placeholder, maxVisible = 150 }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const selectedLabel = value === "" ? allLabel : options.find((o) => o.value === value)?.label ?? value;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matches = q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
    return matches;
  }, [options, query]);
  const visible = filtered.slice(0, maxVisible);
  const showAll = !query.trim() || allLabel.toLowerCase().includes(query.trim().toLowerCase());
  const rows: SSOption[] = showAll ? [{ value: "", label: allLabel }, ...visible] : visible;

  useEffect(() => {
    function away(e: MouseEvent) { if (root.current && !root.current.contains(e.target as Node)) setOpen(false); }
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  useEffect(() => { setActive(0); }, [query, open]);
  useEffect(() => {
    (listRef.current?.children[active] as HTMLElement | undefined)?.scrollIntoView?.({ block: "nearest" });
  }, [active]);

  function choose(v: string) { onChange(v); setOpen(false); setQuery(""); }

  function onKey(e: React.KeyboardEvent) {
    if (!open && (e.key === "ArrowDown" || e.key === "Enter")) { e.preventDefault(); setOpen(true); return; }
    if (!open) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(rows.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); if (rows[active]) choose(rows[active].value); }
    else if (e.key === "Escape") { e.preventDefault(); setOpen(false); }
  }

  return (
    <div className={`gb-ss ${disabled ? "is-disabled" : ""}`} ref={root}>
      <input
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={id ? `${id}-list` : undefined}
        autoComplete="off"
        disabled={disabled}
        value={open ? query : selectedLabel}
        placeholder={open ? "Type to search…" : placeholder}
        onFocus={() => { if (!disabled) setOpen(true); }}
        onClick={() => { if (!disabled) setOpen(true); }}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onKeyDown={onKey}
      />
      <span className="gb-ss-caret" aria-hidden>{loading ? "…" : "▾"}</span>
      {open && !disabled && (
        <ul className="gb-ss-list" id={id ? `${id}-list` : undefined} role="listbox" ref={listRef}>
          {rows.map((o, i) => (
            <li key={`${o.value}|${i}`} role="option" aria-selected={o.value === value}
                className={`${i === active ? "active" : ""} ${o.value === value ? "selected" : ""}`}
                onMouseDown={(e) => { e.preventDefault(); choose(o.value); }}
                onMouseEnter={() => setActive(i)}>
              {o.label}
            </li>
          ))}
          {filtered.length > maxVisible && <li className="gb-ss-more" aria-disabled>…{filtered.length - maxVisible} more, keep typing to narrow down</li>}
          {!rows.length && <li className="gb-ss-more" aria-disabled>No matches</li>}
        </ul>
      )}
    </div>
  );
}
