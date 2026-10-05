import type { JobStatus } from "@/lib/types";

const STYLES: Record<JobStatus, string> = {
  queued: "bg-slate-100 text-slate-700 ring-slate-200",
  running: "bg-blue-50 text-blue-700 ring-blue-200",
  paused: "bg-amber-50 text-amber-700 ring-amber-200",
  done: "bg-green-50 text-green-700 ring-green-200",
  failed: "bg-red-50 text-red-700 ring-red-200",
  cancelled: "bg-slate-100 text-slate-700 ring-slate-200",
};

export default function StatusBadge({ status }: { status: JobStatus }) {
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[status] ?? STYLES.failed}`}>{status === "running" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />}{status}</span>;
}
