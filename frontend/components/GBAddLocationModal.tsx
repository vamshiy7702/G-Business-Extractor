"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getCities, getCountries, getStates, getZips } from "@/lib/api";
import SearchSelect from "@/components/SearchSelect";

export interface GLocation {
  id: string;
  country: string;
  state: string;
  city: string;
  postalCode: string;
  selected: boolean;
  countryCode?: string;
  stateId?: number | null;
  cityId?: number | null;
}

interface Props {
  open: boolean;
  initialValue?: GLocation;
  title?: string;
  onCancel: () => void;
  onSave: (values: GLocation[]) => void;
}

export const ALL_COUNTRIES = "All countries";
export const ALL_STATES = "All states";
export const ALL_CITIES = "All cities";
export const ALL_ZIPS = "All zip codes";

const fold = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const isAll = (v: string | undefined) => !v || /^all( |$)/i.test(v.trim());

/**
 * Cascading location picker: Country -> State -> City -> ZIP code.
 * Every list comes from the bundled database through the API and is filtered by the level above it,
 * so a state only lists its own cities and a city only lists its own ZIP codes.
 */
export default function GBAddLocationModal({ open, initialValue, title = "Add location", onCancel, onSave }: Props) {
  const [countryCode, setCountryCode] = useState("");
  const [stateId, setStateId] = useState<number | null>(null);
  const [cityId, setCityId] = useState<number | null>(null);
  const [zip, setZip] = useState("");
  const [manualZip, setManualZip] = useState("");
  const [multi, setMulti] = useState<Set<number>>(new Set());
  const [multiFilter, setMultiFilter] = useState("");
  const pending = useRef<{ country?: string; state?: string; city?: string; zip?: string } | null>(null);
  const editing = Boolean(initialValue);

  const countriesQ = useQuery({ queryKey: ["loc", "countries"], queryFn: getCountries, enabled: open, staleTime: Infinity });
  const statesQ = useQuery({ queryKey: ["loc", "states", countryCode], queryFn: () => getStates(countryCode), enabled: open && !!countryCode, staleTime: Infinity });
  const citiesQ = useQuery({ queryKey: ["loc", "cities", stateId], queryFn: () => getCities(stateId as number), enabled: open && stateId !== null, staleTime: Infinity });
  const zipsQ = useQuery({ queryKey: ["loc", "zips", cityId], queryFn: () => getZips(cityId as number), enabled: open && cityId !== null, staleTime: Infinity });

  // (re)initialise whenever the dialog opens
  useEffect(() => {
    if (!open) return;
    setCountryCode(initialValue?.countryCode ?? "");
    setStateId(initialValue?.stateId ?? null);
    setCityId(initialValue?.cityId ?? null);
    setZip(isAll(initialValue?.postalCode) ? "" : initialValue?.postalCode ?? "");
    setManualZip("");
    setMulti(new Set());
    setMultiFilter("");
    // Locations saved without ids (e.g. loaded from a file) are matched by name once each list has loaded.
    pending.current = initialValue && !initialValue.countryCode ? {
      country: isAll(initialValue.country) ? undefined : initialValue.country,
      state: isAll(initialValue.state) ? undefined : initialValue.state,
      city: isAll(initialValue.city) ? undefined : initialValue.city,
      zip: isAll(initialValue.postalCode) ? undefined : initialValue.postalCode,
    } : null;
  }, [open, initialValue]);

  useEffect(() => {
    const p = pending.current;
    if (!p?.country || !countriesQ.data) return;
    const hit = countriesQ.data.find((c) => c.code.toLowerCase() === p.country!.toLowerCase() || fold(c.name) === fold(p.country!));
    p.country = undefined;
    if (hit) setCountryCode(hit.code); else pending.current = null;
  }, [countriesQ.data, countryCode]);
  useEffect(() => {
    const p = pending.current;
    if (!p?.state || !statesQ.data) return;
    const hit = statesQ.data.find((s) => fold(s.name) === fold(p.state!));
    p.state = undefined;
    if (hit) setStateId(hit.id); else pending.current = null;
  }, [statesQ.data]);
  useEffect(() => {
    const p = pending.current;
    if (!p?.city || !citiesQ.data) return;
    const hit = citiesQ.data.find((c) => fold(c.name) === fold(p.city!));
    p.city = undefined;
    if (hit) setCityId(hit.id); else pending.current = null;
  }, [citiesQ.data]);
  useEffect(() => {
    const p = pending.current;
    if (!p?.zip || !zipsQ.data) return;
    if (zipsQ.data.some((z) => z.code === p.zip)) setZip(p.zip); else setManualZip(p.zip);
    pending.current = null;
  }, [zipsQ.data]);

  const countries = countriesQ.data ?? [];
  const states = statesQ.data ?? [];
  const cities = citiesQ.data ?? [];
  const zips = zipsQ.data ?? [];
  const country = countries.find((c) => c.code === countryCode);
  const state = states.find((s) => s.id === stateId);
  const city = cities.find((c) => c.id === cityId);

  const countryOpts = useMemo(() => countries.map((c) => ({ value: c.code, label: c.name })), [countries]);
  const stateOpts = useMemo(() => states.map((s) => ({ value: String(s.id), label: s.name })), [states]);
  const cityOpts = useMemo(() => cities.map((c) => ({ value: String(c.id), label: c.name })), [cities]);
  const zipOpts = useMemo(() => zips.map((z) => ({ value: z.code, label: z.label ? `${z.code} — ${z.label}` : z.code })), [zips]);
  const shownMulti = useMemo(() => states.filter((s) => !multiFilter.trim() || fold(s.name).includes(fold(multiFilter))), [states, multiFilter]);

  function pickCountry(code: string) { setCountryCode(code); setStateId(null); setCityId(null); setZip(""); setManualZip(""); setMulti(new Set()); }
  function pickState(v: string) { setStateId(v ? Number(v) : null); setCityId(null); setZip(""); setManualZip(""); }
  function pickCity(v: string) { setCityId(v ? Number(v) : null); setZip(""); setManualZip(""); }
  function toggleMulti(id: number, on: boolean) {
    setMulti((prev) => { const next = new Set(prev); if (on) next.add(id); else next.delete(id); return next; });
    setStateId(null); setCityId(null); setZip("");
  }

  function save() {
    const base = { selected: initialValue?.selected ?? true };
    if (!country) {
      onSave([{ id: initialValue?.id ?? crypto.randomUUID(), country: ALL_COUNTRIES, state: ALL_STATES, city: ALL_CITIES, postalCode: ALL_ZIPS, ...base }]);
      return;
    }
    if (!editing && multi.size > 0) {
      onSave(states.filter((s) => multi.has(s.id)).map((s) => ({
        id: crypto.randomUUID(), country: country.name, countryCode: country.code, state: s.name, stateId: s.id,
        city: ALL_CITIES, cityId: null, postalCode: ALL_ZIPS, ...base,
      })));
      return;
    }
    const code = zip || manualZip.trim();
    onSave([{
      id: initialValue?.id ?? crypto.randomUUID(),
      country: country.name, countryCode: country.code,
      state: state ? state.name : ALL_STATES, stateId: state?.id ?? null,
      city: city ? city.name : ALL_CITIES, cityId: city?.id ?? null,
      postalCode: city && code ? code : ALL_ZIPS,
      ...base,
    }]);
  }

  if (!open) return null;

  const loadError = countriesQ.error ?? statesQ.error ?? citiesQ.error ?? zipsQ.error;
  const noZipList = Boolean(city) && !zipsQ.isLoading && zips.length === 0;
  const hint = !country
    ? "All countries is saved as a scope only. Pick a country to run an extraction (a single search area is needed)."
    : multi.size > 0
      ? `${multi.size} state${multi.size === 1 ? "" : "s"} selected: one task location is added per state.`
      : !state
        ? `${country.name}: ${country.state_count} states/regions. Leave "All states" to search the whole country, or pick one.`
        : !city
          ? `${state.name}: ${cities.length.toLocaleString()} cities. Leave "All cities" to search the whole state, or pick one.`
          : noZipList
            ? `No ZIP list for ${city.name} in the bundled data, so the whole city is searched. You can type a ZIP below.`
            : `${city.name}: ${zips.length} ZIP code${zips.length === 1 ? "" : "s"} that belong to this city. Leave "All zip codes" to search the whole city.`;

  return (
    <div className="gb-modal-backdrop" onMouseDown={onCancel}>
      <div className="gb-location-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="gb-modal-title">{title}</div>
        <div className="gb-location-body">
          <div className="gb-location-form-caption">Select location:</div>
          <div className="gb-location-grid gb-loc-cascade">
            <div>
              <label htmlFor="loc-country">Country:</label>
              <SearchSelect id="loc-country" options={countryOpts} value={countryCode} allLabel={ALL_COUNTRIES}
                            loading={countriesQ.isLoading} onChange={pickCountry} />
            </div>
            <div>
              <label htmlFor="loc-state">State:</label>
              <SearchSelect id="loc-state" options={stateOpts} value={stateId === null ? "" : String(stateId)} allLabel={ALL_STATES}
                            disabled={!countryCode || multi.size > 0} loading={statesQ.isLoading} onChange={pickState} />
            </div>
            <div>
              <label htmlFor="loc-city">City:</label>
              <SearchSelect id="loc-city" options={cityOpts} value={cityId === null ? "" : String(cityId)} allLabel={ALL_CITIES}
                            disabled={stateId === null || multi.size > 0} loading={citiesQ.isLoading} onChange={pickCity} />
            </div>
            <div>
              <label htmlFor="loc-zip">Zip code:</label>
              {noZipList ? (
                <input id="loc-zip" value={manualZip} onChange={(e) => setManualZip(e.target.value.slice(0, 12))} placeholder="optional, e.g. 395007" />
              ) : (
                <SearchSelect id="loc-zip" options={zipOpts} value={zip} allLabel={ALL_ZIPS}
                              disabled={cityId === null} loading={zipsQ.isLoading} onChange={setZip} />
              )}
            </div>
          </div>

          {loadError && <div className="gb-location-hint gb-hint-error">Could not load location data: {loadError instanceof Error ? loadError.message : String(loadError)}</div>}
          <div className="gb-location-hint">{hint}</div>

          {!editing && country && states.length > 1 && (
            <>
              <div className="gb-location-or">Or select multiple states:</div>
              <input className="gb-multi-filter" placeholder="Filter states…" value={multiFilter} onChange={(e) => setMultiFilter(e.target.value)} />
              <div className="gb-multistate-box">
                {shownMulti.map((s) => (
                  <label key={s.id}><input type="checkbox" checked={multi.has(s.id)} onChange={(e) => toggleMulti(s.id, e.target.checked)} />{s.name}</label>
                ))}
                {!shownMulti.length && <span className="gb-no-quick-states">No matching states</span>}
              </div>
              <div className="gb-location-actions">
                <button className="gb-btn" onClick={() => { setMulti(new Set(shownMulti.map((s) => s.id))); setStateId(null); setCityId(null); setZip(""); }}>Select all</button>
                <button className="gb-btn" onClick={() => setMulti(new Set())}>Clear all</button>
              </div>
            </>
          )}
        </div>
        <div className="gb-modal-footer">
          <button className="gb-btn gb-btn-primary" onClick={save}>✓ Ok</button>
          <button className="gb-btn" onClick={onCancel}>✕ Cancel</button>
        </div>
      </div>
    </div>
  );
}
