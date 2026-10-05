import type { QuotaInfo } from "@/lib/types";

export default function QuotaCard({ quota }: { quota?: QuotaInfo }) {
  if (!quota) return null;
  const pct = quota.free_cap ? Math.min(100, (quota.calls / quota.free_cap) * 100) : 0;
  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">Google usage guard</h2>
          <p className="text-xs text-slate-500">{quota.month} · {quota.sku}</p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${quota.configured ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"}`}>
          {quota.configured ? "API key configured" : "API key not configured"}
        </span>
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full bg-indigo-600" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 flex justify-between text-sm text-slate-600">
        <span>{quota.calls.toLocaleString()} used</span>
        <span>{quota.remaining.toLocaleString()} free remaining</span>
      </div>
      <p className="mt-2 text-xs text-slate-500">Configured price after the free cap: ${quota.price_per_1000_usd.toFixed(2)} / 1,000 requests.</p>
    </div>
  );
}
