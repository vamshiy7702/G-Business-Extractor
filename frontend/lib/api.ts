import type { CategoryList, CreateJobBody, Diagnostics, Job, LocCity, LocCountry, LocState, LocZip, PlaceFilters, PlacesResponse, Quote, QuotaInfo, SettingsInfo } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

function describe(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".") || "request"}: ${d.msg ?? "invalid"}`)
      .join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${API_URL}. Is the backend running?`);
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { detail = (await res.json()).detail; } catch { /* non-JSON response */ }
    throw new ApiError(res.status, describe(detail, res.statusText));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function filterQuery(f: PlaceFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.has_phone) p.set("has_phone", "true");
  if (f.has_email) p.set("has_email", "true");
  if (f.has_website) p.set("has_website", "true");
  if (f.min_rating !== undefined) p.set("min_rating", String(f.min_rating));
  if (f.q?.trim()) p.set("q", f.q.trim());
  return p;
}

export const listJobs = () => request<Job[]>("/api/jobs");
export const getJob = (id: number) => request<Job>(`/api/jobs/${id}`);
export const createJob = (body: CreateJobBody) => request<Job>("/api/jobs", { method: "POST", body: JSON.stringify(body) });
export const estimateJob = (body: CreateJobBody) => request<Quote>("/api/jobs/estimate", { method: "POST", body: JSON.stringify(body) });
export const cancelJob = (id: number) => request<Job>(`/api/jobs/${id}/cancel`, { method: "POST" });
export const resumeJob = (id: number) => request<Job>(`/api/jobs/${id}/resume`, { method: "POST" });
export const enrichJob = (id: number) => request<Job>(`/api/jobs/${id}/enrich`, { method: "POST" });
export const deleteJob = (id: number) => request<void>(`/api/jobs/${id}`, { method: "DELETE" });
export const deleteJobs = (ids: number[]) => request<{ deleted: number[]; missing: number[] }>("/api/jobs/bulk-delete", { method: "POST", body: JSON.stringify({ ids }) });
export const deletePlaces = (jobId: number, ids: number[]) => request<{ deleted: number[]; count: number }>(`/api/jobs/${jobId}/places/delete`, { method: "POST", body: JSON.stringify({ ids }) });
export const deleteAllPlaces = (jobId: number) => request<{ deleted: number[]; count: number }>(`/api/jobs/${jobId}/places/delete-all`, { method: "POST" });
export const getHealth = () => request<{ status: string }>("/api/health");
export const getSettings = () => request<SettingsInfo>("/api/settings");
export const getQuota = () => request<QuotaInfo>("/api/quota");
export const getCountries = () => request<LocCountry[]>("/api/locations/countries");
export const getStates = (country: string) => request<LocState[]>(`/api/locations/states?country=${encodeURIComponent(country)}`);
export const getCities = (stateId: number) => request<LocCity[]>(`/api/locations/cities?state_id=${stateId}`);
export const getZips = (cityId: number) => request<LocZip[]>(`/api/locations/zips?city_id=${cityId}`);
export const getCategories = () => request<CategoryList>("/api/categories");
export const getDiagnostics = () => request<Diagnostics>("/api/diagnostics");

export function listPlaces(id: number, f: PlaceFilters & { offset: number; limit: number }) {
  const p = filterQuery(f);
  p.set("offset", String(f.offset));
  p.set("limit", String(f.limit));
  return request<PlacesResponse>(`/api/jobs/${id}/places?${p.toString()}`);
}

export function exportUrl(id: number, format: "csv" | "xlsx", f: PlaceFilters, columns?: string[], separator?: "," | ";"): string {
  const p = filterQuery(f);
  p.set("format", format);
  if (columns?.length) p.set("columns", columns.join(","));
  if (format === "csv" && separator) p.set("separator", separator);
  return `${API_URL}/api/jobs/${id}/export?${p.toString()}`;
}

export const streamUrl = (id: number) => `${API_URL}/api/jobs/${id}/stream`;

export function safeHref(url: string): string | null {
  try {
    const u = new URL(/^[a-z]+:\/\//i.test(url) ? url : `https://${url}`);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}
