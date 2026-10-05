"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { API_URL, getHealth } from "@/lib/api";

export default function Header() {
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, refetchInterval: 15000, retry: false });
  const ok = health.isSuccess;
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-6">
          <Link href="/" className="text-lg font-semibold text-indigo-700">Lead Extractor</Link>
          <nav className="flex gap-4 text-sm text-slate-600">
            <Link href="/" className="hover:text-slate-900">Dashboard</Link>
            <Link href="/new" className="hover:text-slate-900">New task</Link>
            <Link href="/settings" className="hover:text-slate-900">Settings</Link>
          </nav>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500" title={API_URL}>
          <span className={`h-2 w-2 rounded-full ${health.isLoading ? "bg-slate-300" : ok ? "bg-green-500" : "bg-red-500"}`} />
          {health.isLoading ? "Checking API…" : ok ? "API connected" : "API offline"}
        </div>
      </div>
    </header>
  );
}
