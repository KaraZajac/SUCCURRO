// Build-time place-finder index: every community with listed services, with
// per-root-category listing counts so the search page can answer
// "town + need" without loading anything else. AUSPEX pattern — works in dev
// and prod (Pagefind only exists after a build).
import {
  servedPlaces, placesFor, sitesFor, meetingsFor, taxonomyIndex,
} from "../../lib/data.js";

export async function GET() {
  const tax = taxonomyIndex();
  const rootOf = (token) => {
    let t = tax.get(token);
    while (t?.parent) t = tax.get(t.parent);
    return t?.id || token;
  };

  const recCache = new Map();
  const placeRec = (state, slug) => {
    if (!recCache.has(state)) {
      recCache.set(state, new Map(placesFor(state).map((p) => [p.slug, p])));
    }
    return recCache.get(state).get(slug);
  };

  const entries = [];
  for (const { state, slug } of servedPlaces()) {
    const counts = {};
    for (const s of sitesFor(state, slug)) {
      const root = rootOf((s.categories || [])[0] || "other");
      counts[root] = (counts[root] || 0) + 1;
    }
    const meetings = meetingsFor(state, slug).length;
    if (meetings) counts.meetings = meetings;
    const rec = placeRec(state, slug);
    const entry = {
      n: rec?.name || slug.replace(/-/g, " "),
      st: state,
      p: slug,
      c: counts,
    };
    if (rec?.geo) entry.g = [rec.geo.lat, rec.geo.lng];
    entries.push(entry);
  }
  entries.sort((a, b) => a.n.localeCompare(b.n));
  return new Response(JSON.stringify(entries), {
    headers: { "Content-Type": "application/json" },
  });
}
