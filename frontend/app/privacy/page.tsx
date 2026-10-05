import Link from "next/link";

export default function PrivacyPolicy() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link href="/" className="text-sm text-slate-500 hover:text-slate-800">← Dashboard</Link>
      <div className="card space-y-4 p-6">
        <h1 className="text-2xl font-semibold">Privacy Policy</h1>
        <p className="text-sm leading-6 text-slate-700">Use this template as the starting point for your application’s privacy policy. Replace it with a policy reviewed for your business before public launch. Explain what search inputs, job history, exported lead data, API credentials, and logs are stored, why they are stored, retention periods, deletion procedures, and how users can contact you about privacy.</p>
        <p className="text-xs text-slate-500">This page is a product template, not legal advice.</p>
      </div>
    </div>
  );
}
