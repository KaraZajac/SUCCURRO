// Data access layer (family pattern: JUDGMENT/TOCSIN site/src/lib/data.js).
// Reads ../data YAML directly with node:fs at build time. Small shared files
// are cached per process; per-place files are loaded on demand so dev mode
// never parses the whole 100k-record corpus.
import fs from "node:fs";
import path from "node:path";
import { parse } from "yaml";

function findData() {
  let dir = process.cwd();
  for (let i = 0; i < 6; i++) {
    const candidate = path.join(dir, "data", "meta.yaml");
    if (fs.existsSync(candidate)) return path.join(dir, "data");
    dir = path.dirname(dir);
  }
  throw new Error("data/meta.yaml not found walking up from " + process.cwd());
}

export const DATA = findData();
const cache = new Map();

function load(rel) {
  if (cache.has(rel)) return cache.get(rel);
  const file = path.join(DATA, rel);
  const value = fs.existsSync(file)
    ? parse(fs.readFileSync(file, "utf8"))
    : undefined;
  cache.set(rel, value);
  return value;
}

export function loadFresh(rel) {
  const file = path.join(DATA, rel);
  return fs.existsSync(file) ? parse(fs.readFileSync(file, "utf8")) : undefined;
}

export const meta = () => load("meta.yaml");
export const taxonomy = () => load("taxonomy/services.yaml");

export function taxonomyIndex() {
  if (!cache.has("_taxIdx")) {
    const idx = new Map(taxonomy().map((t) => [t.id, t]));
    cache.set("_taxIdx", idx);
  }
  return cache.get("_taxIdx");
}

export const label = (token) => taxonomyIndex().get(token)?.label || token;

export const STATES = () =>
  fs.readdirSync(path.join(DATA, "places")).map((f) => f.replace(/\.yaml$/, "")).sort();

export const placesFor = (state) => load(`places/${state}.yaml`) || [];

// Every (state, placeSlug) that has at least one site or meeting file.
export function servedPlaces() {
  if (cache.has("_served")) return cache.get("_served");
  const found = new Map(); // "st/slug" -> {state, slug}
  for (const kind of ["sites", "meetings"]) {
    const base = path.join(DATA, kind);
    if (!fs.existsSync(base)) continue;
    for (const state of fs.readdirSync(base)) {
      for (const f of fs.readdirSync(path.join(base, state))) {
        const slug = f.replace(/\.yaml$/, "");
        found.set(`${state}/${slug}`, { state, slug });
      }
    }
  }
  const list = [...found.values()];
  cache.set("_served", list);
  return list;
}

export const sitesFor = (state, slug) => loadFresh(`sites/${state}/${slug}.yaml`) || [];
export const meetingsFor = (state, slug) => loadFresh(`meetings/${state}/${slug}.yaml`) || [];

export function orgsFor(state) {
  const base = path.join(DATA, "orgs", state);
  if (!fs.existsSync(base)) return [];
  return fs.readdirSync(base).map((f) => loadFresh(`orgs/${state}/${f}`));
}

export const source = (id) => loadFresh(`sources/${id}.yaml`);

export function allSources() {
  if (cache.has("_sources")) return cache.get("_sources");
  const base = path.join(DATA, "sources");
  const list = [];
  for (const dir of fs.readdirSync(base)) {
    for (const f of fs.readdirSync(path.join(base, dir))) {
      list.push(loadFresh(`sources/${dir}/${f}`));
    }
  }
  list.sort((a, b) => (a.publisher + a.title).localeCompare(b.publisher + b.title));
  cache.set("_sources", list);
  return list;
}

export function sourceIndex() {
  if (!cache.has("_srcIdx")) {
    cache.set("_srcIdx", new Map(allSources().map((s) => [s.id, s])));
  }
  return cache.get("_srcIdx");
}

export function rootOf(token) {
  const tax = taxonomyIndex();
  let t = tax.get(token);
  while (t?.parent) t = tax.get(t.parent);
  return t?.id || token;
}

export const nationalGeometry = () => load("geometry/national.yaml");
export const stateGeometry = (st) => load(`geometry/${st}.yaml`);

// One full-corpus scan, cached: root-category site counts nationally and per
// state, plus per-place totals (sites + meetings) for map dot sizing.
export function categoryCounts() {
  if (cache.has("_catCounts")) return cache.get("_catCounts");
  const national = {};
  const byState = {};
  const byPlaceTotal = {};
  for (const { state, slug } of servedPlaces()) {
    const key = `${state}/${slug}`;
    let total = 0;
    for (const s of sitesFor(state, slug)) {
      const root = rootOf((s.categories || [])[0] || "other");
      national[root] = (national[root] || 0) + 1;
      (byState[state] ??= {})[root] = (byState[state][root] || 0) + 1;
      total += 1;
    }
    total += meetingsFor(state, slug).length;
    byPlaceTotal[key] = total;
  }
  const result = { national, byState, byPlaceTotal };
  cache.set("_catCounts", result);
  return result;
}

// fixed entity->color assignment (Latte hues, CVD-validated chart order)
export const CATEGORY_COLORS = {
  food: "#fe640b", health: "#1e66f5", "family-youth": "#df8e1d",
  "mental-health": "#8839ef", recovery: "#40a02b", lgbtq: "#ea76cb",
  housing: "#209fb5", veterans: "#179299", crisis: "#d20f39",
  legal: "#e64553", financial: "#dd7878", seniors: "#04a5e5",
  "mutual-aid": "#dc8a78", other: "#9ca0b0",
};
export const catColor = (root) => CATEGORY_COLORS[root] || CATEGORY_COLORS.other;

export const STATE_NAMES = {
  al: "Alabama", ak: "Alaska", az: "Arizona", ar: "Arkansas", ca: "California",
  co: "Colorado", ct: "Connecticut", de: "Delaware", dc: "District of Columbia",
  fl: "Florida", ga: "Georgia", hi: "Hawaii", id: "Idaho", il: "Illinois",
  in: "Indiana", ia: "Iowa", ks: "Kansas", ky: "Kentucky", la: "Louisiana",
  me: "Maine", md: "Maryland", ma: "Massachusetts", mi: "Michigan",
  mn: "Minnesota", ms: "Mississippi", mo: "Missouri", mt: "Montana",
  ne: "Nebraska", nv: "Nevada", nh: "New Hampshire", nj: "New Jersey",
  nm: "New Mexico", ny: "New York", nc: "North Carolina", nd: "North Dakota",
  oh: "Ohio", ok: "Oklahoma", or: "Oregon", pa: "Pennsylvania",
  pr: "Puerto Rico", ri: "Rhode Island", sc: "South Carolina",
  sd: "South Dakota", tn: "Tennessee", tx: "Texas", ut: "Utah", vt: "Vermont",
  va: "Virginia", wa: "Washington", wv: "West Virginia", wi: "Wisconsin",
  wy: "Wyoming", us: "National",
};
