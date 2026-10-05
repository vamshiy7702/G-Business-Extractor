export type JobStatus = "queued" | "running" | "paused" | "done" | "failed" | "cancelled";

export interface Job {
  id: number;
  keyword: string;
  city: string;
  state: string;
  country: string;
  postal_code: string;
  source: string;
  status: JobStatus;
  tiles_total: number;
  tiles_done: number;
  places_found: number;
  max_places: number;
  extract_emails: boolean;
  progress: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  estimate_calls: number | null;
  estimate_cost_usd: number | null;
  quota_free_cap: number | null;
  quota_calls_this_month: number | null;
  quota_remaining: number | null;
}

export interface Place {
  id: number;
  source: string;
  source_place_id: string;
  name: string;
  category: string;
  address: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  phone: string;
  email: string;
  website: string;
  lat: number | null;
  lng: number | null;
  rating: number | null;
  email_status: string;
}

export interface PlacesResponse {
  total: number;
  offset: number;
  limit: number;
  items: Place[];
}

export interface PlaceFilters {
  has_phone?: boolean;
  has_email?: boolean;
  has_website?: boolean;
  min_rating?: number;
  q?: string;
}

export interface CreateJobBody {
  keyword: string;
  location: { city: string; state: string; country: string; postal_code: string; country_code?: string; state_id?: number | null; city_id?: number | null };
  source: "osm" | "google";
  options: { max_places: number; results_per_tile: number; tile_deg: number; extract_emails: boolean; threads: number };
}

export interface Quote {
  source: string;
  tiles_total: number;
  estimated_calls: number;
  estimated_cost_usd: number;
  free_cap: number | null;
  calls_this_month: number | null;
  remaining_free_calls: number | null;
  sku: string | null;
  warning: string | null;
}

export interface SettingsInfo {
  default_source: string;
  sources: { name: string; label: string; configured: boolean; free: boolean }[];
  google_api_key_configured: boolean;
  google_pricing_region: string;
  google_text_search_free_cap: number;
  google_text_search_price_per_1000: number;
  max_concurrent_jobs: number;
  max_tiles_per_job: number;
  email_enrichment_enabled: boolean;
}

export interface QuotaInfo {
  month: string;
  sku: string;
  calls: number;
  free_cap: number;
  remaining: number;
  overage: number;
  configured: boolean;
  price_per_1000_usd: number;
}

export interface LocCountry { code: string; name: string; has_zip: boolean; state_count: number; }
export interface LocState { id: number; name: string; code: string | null; type: string | null; }
export interface LocCity { id: number; name: string; lat: number | null; lng: number | null; }
export interface LocZip { code: string; label: string | null; lat: number | null; lng: number | null; }
export interface CategoryList { suggestions: string[]; note: string; }
export interface DiagnosticCheck { service: string; ok: boolean; status: number | null; ms: number; message: string; }
export interface Diagnostics {
  checks: DiagnosticCheck[];
  google_configured: boolean;
  contact_email_set: boolean;
  locations_database: boolean;
  env_file_loaded_hint: string;
}
