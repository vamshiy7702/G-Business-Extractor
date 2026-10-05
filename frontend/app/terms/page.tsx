import Link from "next/link";

export default function TermsofUse() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link href="/" className="text-sm text-slate-500 hover:text-slate-800">← Dashboard</Link>
      <div className="card space-y-4 p-6">
        <h1 className="text-2xl font-semibold">Terms of Use</h1>
        <p className="text-sm leading-6 text-slate-700">Use this template as the starting point for your application’s terms. Replace it with terms reviewed for your business before public launch. The application is provided for lawful business-data research and lead-management workflows. Users are responsible for complying with applicable laws, source-provider terms, and outreach/anti-spam requirements.</p>
        <p className="text-xs text-slate-500">This page is a product template, not legal advice.</p>
      </div>
    </div>
  );
}
