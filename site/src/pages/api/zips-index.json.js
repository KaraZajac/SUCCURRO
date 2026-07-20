// ZIP (ZCTA) centroids for search-by-ZIP: {"90210": [lat, lng], ...}.
// The search page resolves a ZIP to nearby communities client-side against
// the places index (which carries per-place geo).
import { zipCentroids } from "../../lib/data.js";

export async function GET() {
  return new Response(JSON.stringify(zipCentroids()), {
    headers: { "Content-Type": "application/json" },
  });
}
