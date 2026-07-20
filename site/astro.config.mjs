import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

// PAGES_SITE / PAGES_BASE allow subpath preview deploys (family convention)
export default defineConfig({
  site: process.env.PAGES_SITE || "https://succurro.org",
  base: process.env.PAGES_BASE || "/",
  output: "static",
  trailingSlash: "ignore",
  integrations: [sitemap()],
});
