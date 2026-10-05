"use client";

import { useMemo } from "react";
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { safeHref } from "@/lib/api";
import type { Place } from "@/lib/types";

const col = createColumnHelper<Place>();

export default function ResultsTable({ items, loading }: { items: Place[]; loading: boolean }) {
  const columns = useMemo(() => [
    col.accessor("name", { header: "Business", cell: (c) => <div><div className="font-medium text-slate-900">{c.getValue()}</div>{c.row.original.category && <div className="text-xs capitalize text-slate-500">{c.row.original.category}</div>}</div> }),
    col.accessor("phone", { header: "Phone", cell: (c) => c.getValue() || <Dash /> }),
    col.accessor("email", { header: "Email", cell: (c) => c.getValue() || <Dash /> }),
    col.accessor("website", { header: "Website", cell: (c) => { const value = c.getValue(); const href = value ? safeHref(value) : null; if (!value) return <Dash />; if (!href) return <span className="text-slate-500">{value}</span>; return <a href={href} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline">{new URL(href).hostname.replace(/^www\./, "")}</a>; } }),
    col.accessor("rating", { header: "Rating", cell: (c) => c.getValue() == null ? <Dash /> : <span>{c.getValue()?.toFixed(1)} ★</span> }),
    col.accessor("address", { header: "Address", cell: (c) => c.getValue() || <Dash /> }),
  ], []);

  const table = useReactTable({ data: items, columns, getCoreRowModel: getCoreRowModel(), getRowId: (r) => String(r.id) });
  return <div className={`overflow-x-auto ${loading ? "opacity-60" : ""}`}>
    <table className="min-w-full text-left text-sm"><thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">{table.getHeaderGroups().map((hg) => <tr key={hg.id}>{hg.headers.map((h) => <th key={h.id} className="px-4 py-2.5 font-medium">{flexRender(h.column.columnDef.header, h.getContext())}</th>)}</tr>)}</thead>
      <tbody className="divide-y divide-slate-100">{table.getRowModel().rows.map((r) => <tr key={r.id} className="hover:bg-slate-50">{r.getVisibleCells().map((c) => <td key={c.id} className="px-4 py-2.5 align-top">{flexRender(c.column.columnDef.cell, c.getContext())}</td>)}</tr>)}{items.length === 0 && <tr><td colSpan={columns.length} className="px-4 py-10 text-center text-slate-500">No results yet.</td></tr>}</tbody>
    </table>
  </div>;
}
function Dash() { return <span className="text-slate-300">—</span>; }
