"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelJob,
  createJob,
  deleteAllPlaces,
  deleteJobs,
  deletePlaces,
  exportUrl,
  getQuota,
  getSettings,
  listJobs,
  listPlaces,
  resumeJob,
} from "@/lib/api";
import type { CreateJobBody, Job, PlaceFilters } from "@/lib/types";
import GBusinessToolbar from "@/components/GBusinessToolbar";
import GBSettingsModal, { type GBSettings } from "@/components/GBSettingsModal";
import GBAddCategoryModal from "@/components/GBAddCategoryModal";
import GBAddLocationModal, { type GLocation } from "@/components/GBAddLocationModal";
import GBResultsGrid from "@/components/GBResultsGrid";
import { useJobStream } from "@/hooks/useJobStream";

interface CategoryItem { id: string; value: string; selected: boolean; }

// Start empty: the old seed data used a state value ("Lazio / RI") that is not a real state name, so the
// default task could never resolve to a search area. Pick real values with the location dialog instead.
const DEFAULT_SETTINGS: GBSettings = {
  language: "English",
  columns: {
    Category: true,
    "Real Category": true,
    "Business Name": true,
    "Full Address": true,
    City: true,
    State: true,
    "Postal Code": true,
    Country: true,
    Phone: true,
    Email: true,
    Website: true,
    Latitude: true,
    Longitude: true,
    "Map Link": true,
    "Details Link": true,
  },
  extractEmails: true,
  resultsPerTile: 25,
  maxPlaces: 500,
  threads: 3,
  autoExport: true,
  autoRestart: false,
  format: "csv",
  separator: ",",
  encoding: "UTF-8",
};

const RESULT_COLUMN_MAP: Record<string, string> = {
  Category: "category",
  "Real Category": "category",
  "Business Name": "name",
  "Full Address": "address",
  City: "city",
  State: "state",
  "Postal Code": "postal_code",
  Country: "country",
  Phone: "phone",
  Email: "email",
  Website: "website",
  Latitude: "lat",
  Longitude: "lng",
  "Map Link": "map_link",
  "Details Link": "details_link",
};

const SETTINGS_KEY = "lead-extractor-gbusiness-settings";
const PAGE_SIZE = 80;

export default function MainExtractor() {
  const qc = useQueryClient();
  const [source, setSource] = useState<"osm" | "google">("osm");   // free by default; Google needs a server API key
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [locations, setLocations] = useState<GLocation[]>([]);
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<number>>(new Set());
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const [resultSelectedIds, setResultSelectedIds] = useState<Set<number>>(new Set());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [categoryModal, setCategoryModal] = useState<{ open: boolean; id?: string }>({ open: false });
  const [locationModal, setLocationModal] = useState<{ open: boolean; id?: string }>({ open: false });
  const [notice, setNotice] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [hasPhone, setHasPhone] = useState(false);
  const [hasEmail, setHasEmail] = useState(false);
  const [hasWebsite, setHasWebsite] = useState(false);
  const [minRating, setMinRating] = useState<number | undefined>(undefined);
  const [resultPage, setResultPage] = useState(0);
  const [exportMenu, setExportMenu] = useState(false);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [appSettings, setAppSettings] = useState<GBSettings>(DEFAULT_SETTINGS);
  const lastSelectedResultIndex = useRef<number | null>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(SETTINGS_KEY);
      if (saved) setAppSettings({ ...DEFAULT_SETTINGS, ...JSON.parse(saved), columns: { ...DEFAULT_SETTINGS.columns, ...JSON.parse(saved).columns } });
    } catch {
      // Keep defaults if local storage is invalid.
    }
  }, []);

  useEffect(() => {
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(appSettings)); } catch { /* best effort */ }
  }, [appSettings]);

  const jobsQ = useQuery({
    queryKey: ["jobs"],
    queryFn: listJobs,
    refetchInterval: (query) => query.state.data?.some((j) => j.status === "running" || j.status === "queued") ? 2000 : 7000,
  });
  const quotaQ = useQuery({ queryKey: ["quota"], queryFn: getQuota, refetchInterval: 15000 });
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: getSettings, staleTime: 30000 });
  const jobs = jobsQ.data ?? [];

  useEffect(() => {
    if (activeTaskId === null && jobs.length > 0) setActiveTaskId(jobs[0].id);
    if (activeTaskId !== null && !jobs.some((j) => j.id === activeTaskId)) setActiveTaskId(jobs[0]?.id ?? null);
    setSelectedTaskIds((prev) => {
      const next = new Set(Array.from(prev).filter((id) => jobs.some((j) => j.id === id)));
      return next.size === prev.size ? prev : next;
    });
  }, [jobs, activeTaskId]);

  const activeJob = jobs.find((j) => j.id === activeTaskId) ?? null;
  const live = Boolean(activeJob && (activeJob.status === "running" || activeJob.status === "queued"));

  useJobStream(
    activeTaskId ?? 0,
    live,
    (snapshot) => {
      qc.setQueryData<Job[]>(["jobs"], (old) => old?.map((item) => item.id === snapshot.id ? snapshot : item));
      qc.invalidateQueries({ queryKey: ["places", activeTaskId] });
      qc.invalidateQueries({ queryKey: ["quota"] });
    },
    () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["places", activeTaskId] });
    },
  );

  const filters: PlaceFilters = useMemo(() => ({ q, has_phone: hasPhone, has_email: hasEmail, has_website: hasWebsite, min_rating: minRating }), [q, hasPhone, hasEmail, hasWebsite, minRating]);
  const placesQ = useQuery({
    queryKey: ["places", activeTaskId, filters, resultPage, pageSize],
    queryFn: () => listPlaces(activeTaskId as number, { ...filters, offset: resultPage * pageSize, limit: pageSize }),
    enabled: activeTaskId !== null,
    refetchInterval: live ? 2500 : false,
  });

  const selectedCategories = categories.filter((item) => item.selected);
  const selectedLocations = locations.filter((item) => item.selected);

  const refreshJobs = () => {
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["quota"] });
  };
  const refreshPlaces = () => qc.invalidateQueries({ queryKey: ["places", activeTaskId] });

  const create = useMutation({
    mutationFn: createJob,
    onSuccess: (job) => {
      setActiveTaskId(job.id);
      setSelectedTaskIds((prev) => new Set(prev).add(job.id));
      refreshJobs();
    },
  });
  const cancel = useMutation({ mutationFn: cancelJob, onSuccess: refreshJobs, onError: (e) => setNotice(e instanceof Error ? e.message : String(e)) });
  const resume = useMutation({ mutationFn: resumeJob, onSuccess: refreshJobs, onError: (e) => setNotice(e instanceof Error ? e.message : String(e)) });
  const bulkRemove = useMutation({
    mutationFn: deleteJobs,
    onSuccess: async () => {
      setSelectedTaskIds(new Set());
      setActiveTaskId(null);
      setResultSelectedIds(new Set());
      await qc.invalidateQueries({ queryKey: ["jobs"] });
      await qc.invalidateQueries({ queryKey: ["quota"] });
    },
    onError: (e) => setNotice(e instanceof Error ? e.message : String(e)),
  });
  const removePlaces = useMutation({
    mutationFn: ({ ids }: { ids: number[] }) => deletePlaces(activeTaskId as number, ids),
    onSuccess: async (data) => {
      setResultSelectedIds(new Set());
      await refreshPlaces();
      await refreshJobs();
      setNotice(`${data.count} result${data.count === 1 ? "" : "s"} deleted.`);
    },
    onError: (e) => setNotice(e instanceof Error ? e.message : String(e)),
  });
  const removeAllPlaces = useMutation({
    mutationFn: () => deleteAllPlaces(activeTaskId as number),
    onSuccess: async (data) => {
      setResultSelectedIds(new Set());
      await refreshPlaces();
      await refreshJobs();
      setNotice(`${data.count} result${data.count === 1 ? "" : "s"} deleted.`);
    },
    onError: (e) => setNotice(e instanceof Error ? e.message : String(e)),
  });

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 12000);
    return () => clearTimeout(timer);
  }, [notice]);

  // Auto restart: retry a failed task a few times with a growing delay. It used to retry every 0.8 s forever,
  // which hammered the data server and hid the real error behind an endless failed/running flicker.
  const restartCounts = useRef<Map<number, number>>(new Map());
  useEffect(() => {
    if (!appSettings.autoRestart || activeJob?.status !== "failed") return;
    const tries = restartCounts.current.get(activeJob.id) ?? 0;
    if (tries >= 3) return;
    const timer = window.setTimeout(() => {
      restartCounts.current.set(activeJob.id, tries + 1);
      void resume.mutateAsync(activeJob.id).catch(() => undefined);
    }, 5000 * (tries + 1));
    return () => window.clearTimeout(timer);
  }, [appSettings.autoRestart, activeJob?.id, activeJob?.status]);

  // Auto export: download the full result set of a task the moment it is seen finishing. It used to fire for
  // the latest finished task every time the app was opened in a new tab (and for tasks with no results).
  const prevStatus = useRef<Map<number, string>>(new Map());
  useEffect(() => {
    for (const job of jobs) {
      const before = prevStatus.current.get(job.id);
      prevStatus.current.set(job.id, job.status);
      if (!appSettings.autoExport || job.status !== "done" || !job.places_found) continue;
      if (before !== "running" && before !== "queued") continue;
      const columns = Object.entries(appSettings.columns).filter(([, enabled]) => enabled).map(([label]) => RESULT_COLUMN_MAP[label]).filter(Boolean);
      const a = document.createElement("a");
      a.href = exportUrl(job.id, appSettings.format, {}, columns, appSettings.separator);
      a.download = `leads-job-${job.id}.${appSettings.format}`;
      a.click();
    }
  }, [jobs, appSettings]);

  function toggleCategory(id: string) {
    setCategories((prev) => prev.map((item) => item.id === id ? { ...item, selected: !item.selected } : item));
  }

  function toggleLocation(id: string) {
    setLocations((prev) => prev.map((item) => item.id === id ? { ...item, selected: !item.selected } : item));
  }

  function isAllValue(v: string) {
    return /^all( |$)/i.test(v.trim());
  }

  function normalizeCountry(value: string) {
    return value.trim().toLowerCase() === "all countries" ? "All countries" : value;
  }

  async function startSelected() {
    const resumable = jobs.filter((job) => selectedTaskIds.has(job.id) && (job.status === "paused" || job.status === "failed" || job.status === "queued"));
    if (resumable.length) {
      for (const job of resumable) {
        try { await resume.mutateAsync(job.id); } catch { return; }
      }
    }
    if (!selectedCategories.length || !selectedLocations.length) {
      if (!resumable.length) setNotice("Select at least one category and one location.");
      return;
    }
    if (source === "google" && settingsQ.data && !settingsQ.data.google_api_key_configured) {
      setNotice("Google Maps needs GOOGLE_PLACES_API_KEY in backend/.env (then restart the backend). Switch DATA SOURCE to OpenStreetMap to run without a key.");
      return;
    }
    const bad = selectedLocations.find((l) => isAllValue(l.country));
    if (bad) {
      setNotice("\"All countries\" cannot be searched as one area. Edit the location and choose a country (state, city and ZIP are optional).");
      return;
    }

    const norm = (v: string) => v.trim().toLowerCase();
    const sameTask = (job: Job, category: CategoryItem, loc: GLocation) =>
      job.source === source && norm(job.keyword) === norm(category.value) &&
      norm(displayLocationValue(job.country, "country") ?? "") === norm(displayLocationValue(loc.country, "country") ?? "") &&
      norm(displayLocationValue(job.state, "state") ?? "") === norm(displayLocationValue(loc.state, "state") ?? "") &&
      norm(displayLocationValue(job.city, "city") ?? "") === norm(displayLocationValue(loc.city, "city") ?? "") &&
      norm(displayLocationValue(job.postal_code, "zip") ?? "") === norm(displayLocationValue(loc.postalCode, "zip") ?? "");

    setNotice("Creating extraction tasks…");
    setProblems([]);
    const failures: string[] = [];
    let createdCount = 0;
    let skipped = 0;
    for (const category of selectedCategories) {
      for (const location of selectedLocations) {
        // Pressing "Get data" twice used to create a duplicate of every task. Re-use the existing one instead.
        const existing = jobs.find((job) => sameTask(job, category, location));
        if (existing) {
          skipped += 1;
          if (existing.status === "failed" || existing.status === "paused") {
            try { await resume.mutateAsync(existing.id); setActiveTaskId(existing.id); } catch { return; }
          }
          continue;
        }
        const body: CreateJobBody = {
          keyword: category.value,
          location: {
            city: displayLocationValue(location.city, "city"),
            state: displayLocationValue(location.state, "state"),
            country: normalizeCountry(location.country),
            postal_code: displayLocationValue(location.postalCode, "zip"),
            country_code: location.countryCode ?? "",
            state_id: location.stateId ?? null,
            city_id: location.cityId ?? null,
          },
          source,
          options: {
            max_places: appSettings.maxPlaces,
            results_per_tile: appSettings.resultsPerTile,
            tile_deg: 0.05,
            extract_emails: appSettings.extractEmails,
            threads: appSettings.threads,
          },
        };
        try {
          const job = await create.mutateAsync(body);
          createdCount += 1;
          setActiveTaskId(job.id);
        } catch (err) {
          const where = [location.country, location.state, location.city].filter((x) => x && !/^all /i.test(x)).join(", ") || location.country;
          failures.push(`${category.value} in ${where}: ${err instanceof Error ? err.message : String(err)}`);
        }
      }
    }
    setProblems(failures);
    setNotice(`${createdCount} extraction task${createdCount === 1 ? "" : "s"} started${skipped ? `, ${skipped} already existed (not duplicated)` : ""}.`);
  }

  async function stopSelected() {
    const running = jobs.filter((job) => selectedTaskIds.has(job.id) && (job.status === "running" || job.status === "queued"));
    for (const job of running) await cancel.mutateAsync(job.id);
    if (!running.length) setNotice("No running task is selected.");
  }

  function selectTask(id: number, additive: boolean, range: boolean) {
    const index = jobs.findIndex((job) => job.id === id);
    setActiveTaskId(id);
    setResultSelectedIds(new Set());
    setResultSelectedIds(new Set());
    setSelectedTaskIds((prev) => {
      if (range && index >= 0) {
        const last = Array.from(prev).map((taskId) => jobs.findIndex((job) => job.id === taskId)).filter((x) => x >= 0).pop();
        if (last !== undefined) {
          const [start, end] = last <= index ? [last, index] : [index, last];
          return new Set(jobs.slice(start, end + 1).map((job) => job.id));
        }
      }
      if (additive) {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id); else next.add(id);
        return next;
      }
      return new Set([id]);
    });
  }

  function toggleResultSelection(id: number, additive: boolean, range: boolean) {
    const items = placesQ.data?.items ?? [];
    const index = items.findIndex((item) => item.id === id);
    setResultSelectedIds((prev) => {
      if (range && index >= 0 && lastSelectedResultIndex.current !== null) {
        const [start, end] = lastSelectedResultIndex.current <= index ? [lastSelectedResultIndex.current, index] : [index, lastSelectedResultIndex.current];
        return new Set([...prev, ...items.slice(start, end + 1).map((item) => item.id)]);
      }
      if (additive) {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id); else next.add(id);
        lastSelectedResultIndex.current = index;
        return next;
      }
      lastSelectedResultIndex.current = index;
      return new Set([id]);
    });
  }

  async function deleteSelectedTasks() {
    const ids = Array.from(selectedTaskIds);
    if (!ids.length) { setNotice("Select at least one task to delete."); return; }
    setNotice(`Deleting ${ids.length} selected task${ids.length === 1 ? "" : "s"}…`);
    await bulkRemove.mutateAsync(ids);
  }

  async function deleteAllTasks() {
    if (!jobs.length) { setNotice("There are no tasks to delete."); return; }
    setNotice(`Deleting all ${jobs.length} task${jobs.length === 1 ? "" : "s"}…`);
    await bulkRemove.mutateAsync(jobs.map((job) => job.id));
  }

  function saveTasks() {
    const payload = {
      version: 1,
      categories: categories.map((c) => c.value),
      locations: locations.map((l) => ({ country: l.country, state: l.state, city: l.city, postal_code: l.postalCode, country_code: l.countryCode, state_id: l.stateId, city_id: l.cityId })),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "lead-extractor-tasks.tsk"; a.click(); URL.revokeObjectURL(url);
  }

  function loadTasks(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(String(reader.result));
        const loadedCats = Array.isArray(data.categories) ? (data.categories as unknown[]).filter((x): x is string => typeof x === "string").map((x, i) => ({ id: `cat-${Date.now()}-${i}`, value: x, selected: true })) : [];
        const loadedLocs = Array.isArray(data.locations) ? (data.locations as unknown[]).filter((x): x is object => Boolean(x && typeof x === "object")).map((x0, i) => { const x = x0 as { country?: string; state?: string; city?: string; postal_code?: string; country_code?: string; state_id?: number | null; city_id?: number | null }; return ({
          id: `loc-${Date.now()}-${i}`,
          country: x.country?.trim() || "All countries",
          state: x.state?.trim() || "All states",
          city: x.city?.trim() || "All cities",
          postalCode: x.postal_code?.trim() || "All zip codes",
          countryCode: x.country_code || undefined,
          stateId: x.state_id ?? null,
          cityId: x.city_id ?? null,
          selected: true,
        }); }) : [];
        if (loadedCats.length) setCategories(loadedCats);
        if (loadedLocs.length) setLocations(loadedLocs);
        setNotice("Task file loaded. Press Get data to create extraction tasks.");
      } catch {
        setNotice("Unable to read the .tsk file. Use the format created by Save Tasks.");
      }
    };
    reader.readAsText(file);
  }

  function loadCategoryFile(file: File) {
    const reader = new FileReader(); reader.onload = () => {
      const values = String(reader.result).split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
      setCategories(values.map((value, i) => ({ id: `cat-${Date.now()}-${i}`, value, selected: true })));
    }; reader.readAsText(file);
  }

  function loadLocationFile(file: File) {
    const reader = new FileReader(); reader.onload = () => {
      const values = String(reader.result).split(/\r?\n/).map((x) => x.trim()).filter(Boolean).map((line) => {
        const [country = "India", state = "All states", city = "All cities", postalCode = "All zip codes"] = line.split(",").map((v) => v.trim());
        return { id: crypto.randomUUID(), country: country || "All countries", state: state || "All states", city: city || "All cities", postalCode: postalCode || "All zip codes", selected: true };
      });
      setLocations(values);
    }; reader.readAsText(file);
  }

  function selectedExportColumns() {
    return Object.entries(appSettings.columns).filter(([, enabled]) => enabled).map(([label]) => RESULT_COLUMN_MAP[label]).filter(Boolean);
  }

  const activeExport = activeTaskId !== null ? exportUrl(activeTaskId, "csv", filters, selectedExportColumns(), appSettings.separator) : "";
  const activeExportXlsx = activeTaskId !== null ? exportUrl(activeTaskId, "xlsx", filters, selectedExportColumns()) : "";
  const total = placesQ.data?.total ?? 0;
  const from = total ? resultPage * pageSize + 1 : 0;
  const to = Math.min(total, (resultPage + 1) * pageSize);
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);

  const allCategorySelected = categories.length > 0 && categories.every((c) => c.selected);
  const allLocationSelected = locations.length > 0 && locations.every((l) => l.selected);
  const allTaskSelected = jobs.length > 0 && jobs.every((j) => selectedTaskIds.has(j.id));
  const allVisibleResultsSelected = (placesQ.data?.items ?? []).length > 0 && (placesQ.data?.items ?? []).every((p) => resultSelectedIds.has(p.id));

  return (
    <div className="gb-page">
      <GBusinessToolbar
        source={source}
        onSourceChange={setSource}
        onStart={startSelected}
        onStop={stopSelected}
        onSettings={() => setSettingsOpen(true)}
        onAutoExport={() => setAppSettings((s) => ({ ...s, autoExport: !s.autoExport }))}
        onAutoRestart={() => setAppSettings((s) => ({ ...s, autoRestart: !s.autoRestart }))}
      />

      <div className="gb-workspace">
        {notice && <div className="gb-notice">{notice}</div>}
        {problems.length > 0 && (
          <div className="gb-notice gb-notice-error" role="alert">
            <strong>{problems.length} task{problems.length === 1 ? " was" : "s were"} not created:</strong>
            <ul>{problems.map((m) => <li key={m}>{m}</li>)}</ul>
            <button onClick={() => setProblems([])}>Dismiss</button>
          </div>
        )}
        {activeJob && (activeJob.status === "failed" || (activeJob.status === "paused" && activeJob.error)) && (
          <div className="gb-notice gb-notice-error">Task {activeJob.id} {activeJob.status}: {activeJob.error ?? "unknown error"} — progress is saved; select the task and press Get data to resume. Open Settings → Connection → Test connections if this keeps happening.</div>
        )}
        {activeJob && activeJob.status === "done" && activeJob.places_found === 0 && (
          <div className="gb-notice gb-notice-info">Task {activeJob.id} finished but found no businesses for “{activeJob.keyword}” here. Try a broader area (leave City on “All cities”), another spelling of the category, or the Google source (OpenStreetMap has fewer listings for niche categories).</div>
        )}

        <section className="gb-top-grid">
          <div className="gb-panel">
            <div className="gb-panel-title">Categories / keywords</div>
            <div className="gb-listbox">
              {categories.map((item) => (
                <label key={item.id} className="gb-list-row">
                  <input type="checkbox" checked={item.selected} onChange={() => toggleCategory(item.id)} />
                  <span title={item.value}>{item.value}</span>
                </label>
              ))}
              {!categories.length && <div className="gb-list-empty">No categories</div>}
            </div>
            <div className="gb-panel-actions">
              <button onClick={() => setCategoryModal({ open: true })}>Add Category</button>
              <button disabled={selectedCategories.length !== 1} onClick={() => setCategoryModal({ open: true, id: selectedCategories[0]?.id })}>Edit</button>
              <button disabled={!selectedCategories.length} onClick={() => setCategories((prev) => prev.filter((x) => !x.selected))}>Delete</button>
              <label className="gb-file-button">Upload<input type="file" accept=".txt,.csv" onChange={(e) => { const file = e.target.files?.[0]; if (file) loadCategoryFile(file); e.currentTarget.value = ""; }} /></label>
              <button onClick={() => setCategories((prev) => prev.map((x) => ({ ...x, selected: !allCategorySelected })))}>{allCategorySelected ? "Clear" : "Select All"}</button>
              <button onClick={() => setCategories((prev) => prev.map((x) => ({ ...x, selected: false })))}>Clear Selection</button>
            </div>
          </div>

          <div className="gb-panel">
            <div className="gb-panel-title">Locations</div>
            <div className="gb-listbox">
              {locations.map((item) => (
                <label key={item.id} className="gb-list-row">
                  <input type="checkbox" checked={item.selected} onChange={() => toggleLocation(item.id)} />
                  <span title={`${item.country}, ${item.state}, ${item.city}, ${item.postalCode}`}>{`${item.country}, ${item.state}, ${item.city}, ${item.postalCode}`}</span>
                </label>
              ))}
              {!locations.length && <div className="gb-list-empty">No locations</div>}
            </div>
            <div className="gb-panel-actions">
              <button onClick={() => setLocationModal({ open: true })}>Add Location</button>
              <button disabled={selectedLocations.length !== 1} onClick={() => setLocationModal({ open: true, id: selectedLocations[0]?.id })}>Edit</button>
              <button disabled={!selectedLocations.length} onClick={() => setLocations((prev) => prev.filter((x) => !x.selected))}>Delete</button>
              <label className="gb-file-button">Upload<input type="file" accept=".txt,.csv" onChange={(e) => { const file = e.target.files?.[0]; if (file) loadLocationFile(file); e.currentTarget.value = ""; }} /></label>
              <button onClick={() => setLocations((prev) => prev.map((x) => ({ ...x, selected: !allLocationSelected })))}>{allLocationSelected ? "Clear" : "Select All"}</button>
              <button onClick={() => setLocations((prev) => prev.map((x) => ({ ...x, selected: false })))}>Clear Selection</button>
            </div>
          </div>

          <div className="gb-panel gb-task-panel">
            <div className="gb-panel-title">Task to do</div>
            <div className="gb-table-scroll gb-task-scroll">
              <table className="gb-task-table">
                <thead><tr><th>Task ID</th><th>Categories</th><th>Location</th><th>Country</th><th>State</th><th>City</th><th>Status</th><th>Found</th></tr></thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr
                      key={job.id}
                      className={`${activeTaskId === job.id ? "active" : ""} ${selectedTaskIds.has(job.id) ? "task-selected" : ""}`}
                      onClick={(event) => selectTask(job.id, event.ctrlKey || event.metaKey, event.shiftKey)}
                      title="Click to select. Ctrl/Command-click for multiple tasks. Shift-click for a range."
                    >
                      <td>{job.id}</td>
                      <td>{job.keyword}</td>
                      <td>{[displayLocationValue(job.country, "country"), displayLocationValue(job.state, "state"), displayLocationValue(job.city, "city"), displayLocationValue(job.postal_code, "zip")].join(", ")}</td>
                      <td>{displayLocationValue(job.country, "country")}</td>
                      <td>{displayLocationValue(job.state, "state")}</td>
                      <td>{displayLocationValue(job.city, "city")}</td>
                      <td className={`gb-st gb-st-${job.status}`} title={job.error ?? job.status}>{statusLabel(job)}</td>
                      <td>{job.places_found}</td>
                    </tr>
                  ))}
                  {jobs.length === 0 && <tr><td colSpan={8} className="gb-task-empty">No tasks yet. Select a category and location, then click Get data.</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="gb-task-actions">
              <button onClick={() => setSelectedTaskIds(allTaskSelected ? new Set() : new Set(jobs.map((j) => j.id)))}>{allTaskSelected ? "Clear" : "Select All"}</button>
              <button onClick={() => setSelectedTaskIds(new Set())}>Clear</button>
              <button onClick={deleteSelectedTasks} disabled={!selectedTaskIds.size || bulkRemove.isPending}>Delete Selection</button>
              <button onClick={deleteAllTasks} disabled={!jobs.length || bulkRemove.isPending}>Delete All</button>
              <button onClick={saveTasks}>Save Tasks</button>
              <label className="gb-file-button">Load Tasks<input type="file" accept=".tsk,.json" onChange={(e) => { const file = e.target.files?.[0]; if (file) loadTasks(file); e.currentTarget.value = ""; }} /></label>
            </div>
          </div>
        </section>

        <section className="gb-commandbar">
          <button className="gb-action-primary" onClick={startSelected} disabled={create.isPending || resume.isPending}><span>▶</span> Get data</button>
          <button className="gb-action-stop" onClick={stopSelected} disabled={cancel.isPending}><span>●</span> Stop</button>
          <div className="gb-command-spacer" />
          <button onClick={() => setResultSelectedIds(new Set(placesQ.data?.items.map((p) => p.id) ?? []))} disabled={!placesQ.data?.items.length}>{allVisibleResultsSelected ? "Clear" : "Select all"}</button>
          <button onClick={() => setResultSelectedIds(new Set())}>Clear</button>
          <button disabled={!resultSelectedIds.size || removePlaces.isPending} onClick={() => activeTaskId && removePlaces.mutate({ ids: Array.from(resultSelectedIds) })}>Delete selected</button>
          <button disabled={!activeTaskId || !total || removeAllPlaces.isPending} onClick={() => activeTaskId && removeAllPlaces.mutate()}>Delete all</button>
          <div className="gb-export-wrap">
            <button className="gb-export" disabled={!activeTaskId || total === 0} onClick={() => setExportMenu((v) => !v)}>Export ▾</button>
            {exportMenu && activeTaskId && <div className="gb-export-menu"><a href={activeExport} download onClick={() => setExportMenu(false)}>CSV</a><a href={activeExportXlsx} download onClick={() => setExportMenu(false)}>Excel (XLSX)</a></div>}
          </div>
        </section>

        <section className="gb-results-panel">
          <div className="gb-results-toolbar">
            <div className="gb-result-filters">
              <span className="gb-filter-caption">Filter</span>
              <input value={q} onChange={(e) => { setQ(e.target.value); setResultPage(0); }} placeholder="business name / address / email" />
              <label><input type="checkbox" checked={hasPhone} onChange={(e) => { setHasPhone(e.target.checked); setResultPage(0); }} /> phone</label>
              <label><input type="checkbox" checked={hasEmail} onChange={(e) => { setHasEmail(e.target.checked); setResultPage(0); }} /> email</label>
              <label><input type="checkbox" checked={hasWebsite} onChange={(e) => { setHasWebsite(e.target.checked); setResultPage(0); }} /> website</label>
              <select value={minRating ?? ""} onChange={(e) => { setMinRating(e.target.value ? Number(e.target.value) : undefined); setResultPage(0); }}><option value="">Any rating</option><option value="3">3+</option><option value="3.5">3.5+</option><option value="4">4+</option><option value="4.5">4.5+</option></select>
            </div>
            <div className="gb-live-status"><span className={`gb-status-dot ${live ? "running" : activeJob?.status === "done" ? "done" : activeJob?.status === "failed" ? "failed" : ""}`} />{activeJob ? `${activeJob.status.toUpperCase()} · ${Math.round(activeJob.progress)}% · ${activeJob.places_found} found` : "READY"}</div>
          </div>
          <GBResultsGrid items={placesQ.data?.items ?? []} selectedIds={resultSelectedIds} onRowSelect={toggleResultSelection} loading={placesQ.isFetching} />
          <div className="gb-results-footer">
            <span>{activeJob ? `${activeJob.keyword} · ${displayLocationValue(activeJob.city, "city")}, ${displayLocationValue(activeJob.state, "state")}` : "No active task"}</span>
            <span>{from}–{to} of {total}</span>
            <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setResultPage(0); }}><option value={50}>50 / page</option><option value={80}>80 / page</option><option value={100}>100 / page</option></select>
            <button disabled={resultPage === 0} onClick={() => { setResultPage((p) => Math.max(0, p - 1)); setResultSelectedIds(new Set()); }}>◀</button>
            <button disabled={resultPage >= lastPage} onClick={() => { setResultPage((p) => Math.min(lastPage, p + 1)); setResultSelectedIds(new Set()); }}>▶</button>
            <span className="gb-quota">Google quota: {quotaQ.data ? `${quotaQ.data.calls.toLocaleString()} / ${quotaQ.data.free_cap.toLocaleString()}` : "—"}</span>
          </div>
        </section>
      </div>

      <footer className="gb-statusbar"><span>{activeJob ? `Working on task ${activeJob.id}… ${activeJob.status}` : "Ready"}</span><span>Data source: {source === "google" ? "Google Maps" : "OpenStreetMap"}</span></footer>

      <GBSettingsModal
        open={settingsOpen}
        source={source}
        value={appSettings}
        onChange={(next) => { setAppSettings(next); setNotice("Settings saved."); }}
        onClose={() => setSettingsOpen(false)}
      />
      <GBAddCategoryModal
        open={categoryModal.open}
        title={categoryModal.id ? "Edit Category" : "Add Category"}
        initialValue={categories.find((c) => c.id === categoryModal.id)?.value}
        onCancel={() => setCategoryModal({ open: false })}
        onSave={(value) => {
          if (categoryModal.id) setCategories((prev) => prev.map((c) => c.id === categoryModal.id ? { ...c, value } : c));
          else setCategories((prev) => [...prev, { id: crypto.randomUUID(), value, selected: true }]);
          setCategoryModal({ open: false });
        }}
      />
      <GBAddLocationModal
        open={locationModal.open}
        title={locationModal.id ? "Edit location" : "Add location"}
        initialValue={locations.find((l) => l.id === locationModal.id)}
        onCancel={() => setLocationModal({ open: false })}
        onSave={(values) => {
          if (locationModal.id) setLocations((prev) => prev.flatMap((l) => (l.id === locationModal.id ? values : [l])));
          else setLocations((prev) => [...prev, ...values]);
          setLocationModal({ open: false });
        }}
      />
    </div>
  );
}

function statusLabel(job: Job) {
  if (job.status === "running") return `running ${Math.round(job.progress)}%`;
  return job.status;
}

function displayLocationValue(value: string | undefined, kind: "country" | "state" | "city" | "zip"): string {
  const normalized = (value ?? "").trim().toLowerCase();
  if (kind === "country") return !normalized || normalized === "all" || normalized === "all countries" ? "All countries" : (value ?? "");
  if (kind === "state") return !normalized || normalized === "all" || normalized === "all states" ? "All states" : (value ?? "");
  if (kind === "city") return !normalized || normalized === "all" || normalized === "all cities" ? "All cities" : (value ?? "");
  return !normalized || normalized === "all" || normalized === "all zip codes" || normalized === "all zips" ? "All zip codes" : (value ?? "");
}
