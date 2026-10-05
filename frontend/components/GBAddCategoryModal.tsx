"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getCategories } from "@/lib/api";

export default function GBAddCategoryModal({
  open,
  initialValue,
  title = "Add Category",
  onCancel,
  onSave,
}: {
  open: boolean;
  initialValue?: string;
  title?: string;
  onCancel: () => void;
  onSave: (value: string) => void;
}) {
  const [value, setValue] = useState(initialValue ?? "");
  const cats = useQuery({ queryKey: ["categories"], queryFn: getCategories, enabled: open, staleTime: Infinity });
  useEffect(() => { if (open) setValue(initialValue ?? ""); }, [open, initialValue]);
  if (!open) return null;
  return (
    <div className="gb-modal-backdrop" onMouseDown={onCancel}>
      <div className="gb-small-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="gb-modal-title">{title}</div>
        <div className="gb-modal-content">
          <label className="gb-form-label">Category / keyword</label>
          <input autoFocus list="gb-category-suggestions" value={value} onChange={(e) => setValue(e.target.value)} placeholder="e.g. dentist" onKeyDown={(e) => { if (e.key === "Enter" && value.trim()) onSave(value.trim()); }} />
          <datalist id="gb-category-suggestions">{(cats.data?.suggestions ?? []).map((c) => <option key={c} value={c} />)}</datalist>
          <div className="gb-location-hint">Start typing to see categories OpenStreetMap understands directly. Other words are searched by business name, which finds fewer results.</div>
        </div>
        <div className="gb-modal-footer"><button className="gb-btn gb-btn-primary" onClick={() => value.trim() && onSave(value.trim())}>✓ Ok</button><button className="gb-btn" onClick={onCancel}>✕ Cancel</button></div>
      </div>
    </div>
  );
}
