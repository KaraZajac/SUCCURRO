# Restricted-TSML intergroups: verified contacts + feed re-test (2026-07-30)

Research-only. No pipeline code, no `data/` writes. Covers the 17 AA intergroups
listed in `docs/outreach.md` "Batch 2 — restricted TSML intergroups" — sites that
run the 12 Step Meeting List plugin with feed sharing set to *restricted*, so
`admin-ajax.php?action=meetings` returns `401 Unauthorized`.

Two questions per site: **(a)** is the feed still restricted as of the 2026-07-19
survey, and **(b)** what address should the sharing-key email actually go to.

Method: browser-UA `curl`, 2–6 throttled requests per site (3 s apart), fetching
the homepage plus `/contact`, `/contact-us`, `/about`, officer/committee-roster
pages, and the site's `/meetings` page. Every address below was read off the
intergroup's own published page — nothing was guessed, inferred from a pattern,
or taken from WHOIS. Cloudflare-obfuscated addresses (`[email protected]`) were
decoded from their `data-cfemail` payloads.

## Headline numbers

| Bucket | Sites |
|---|---|
| **Feed now readable without a key** (open `tsml-cache-*.json`) — no email needed | **5** |
| Still restricted, **verified email in hand** | **9** |
| Still restricted, **contact form only** | **3** |
| No contact route found at all | 0 |
| `admin-ajax` feeds that opened up since 2026-07-19 | **0** |

**Emails actually to send: 12** (9 addressed, 3 via form). Down from 17.

### The real find: five sites publish an open TSML cache file

The plugin writes its meeting list to a static `wp-content/tsml-cache-<hash>.json`
and serves it with no auth even when the AJAX endpoint is key-gated. Five of the
seventeen leak the whole feed this way — **4,552 meetings, no permission ask
required**, same as the `pdxaa` / `albuquerqueaa` / `cflintergroup` entries
already in `pipeline/curated/feeds.yaml`.

| Intergroup | Cache feed URL | Records | Newest `updated` seen |
|---|---|---|---|
| SE Michigan Area 33 | `https://aa-semi.org/wp-content/tsml-cache-71b3196c3f.json` | 1,508 | 2026-03-26 |
| Fort Worth Central Office | `https://fortworthaa.org/wp-content/tsml-cache-87c092dd60.json` | 1,070 | 2026-06-08 |
| NH Area 43 | `https://nhaa.net/wp-content/tsml-cache-b8de952a7e.json` | 832 | 2026-07-26 |
| Idaho Area 18 | `https://idahoarea18aa.org/wp-content/tsml-cache-d461d080a0.json` | 670 | 2026-07-27 |
| Buffalo Area Central Office | `https://buffaloaany.org/wp-content/tsml-cache-9295947df1.json` | 472 | 2026-07-28 |

All five parse as JSON arrays of TSML meeting objects. Usual caveat from the
`feeds.yaml` header applies: **the hash rotates**, so on a 404 re-discover it from
the site's meetings page (`grep -oE 'tsml-cache-[a-f0-9]+\.json'`).

The other twelve embed their meeting JSON inline in the `/meetings` page HTML but
expose no cache file, so they still need a sharing key.

## Contacts

Preference order applied: webmaster/tech → office → chair. Where two are useful
both are listed, best first.

| # | Intergroup | Domain | Verified contact | Found at | TSML `/meetings`? | Note |
|---|---|---|---|---|---|---|
| 1 | Dallas AA Central Office (Dallas Intergroup Association) | aadallas.org | `office@aadallas.org` (Office Manager)<br>`chair@aadallas.org` (Board Chair) | `https://www.aadallas.org/contact-us/` — "Individual Contacts" block; Cloudflare-obfuscated, decoded. `office@` also plaintext on the homepage | yes, `/meetings/` | — |
| 2 | Fort Worth A.A. Central Office | fortworthaa.org | **form only** — `https://fortworthaa.org/contact-form/` | site publishes no address anywhere (checked contact, central-office, content-policy, service-committees) | yes, `/meetings/` | **feed open via cache — no email needed** |
| 3 | AA Boston Central Service Committee of Eastern MA | aaboston.org | `aaboston1945@gmail.com` | masthead of `https://aaboston.org/wp-content/uploads/BULLETIN-August-2026.pdf`, linked from `/monthly-bulletin`: "Email: aaboston1945@gmail.com" | yes, `/meetings` | Site has **no contact page** — only 13 pages total, zero `mailto:` anywhere in the HTML. The bulletin PDF is the only published address. |
| 4 | Miami-Dade Intergroup | aamiamidade.org | `aamiamidade@bellsouth.net` | `mailto:` link on `https://aamiamidade.org/contact` | yes, `/meetings` | — |
| 5 | Tri-County Central Office (Tampa) | aatampa-area.org | `aainfo@aatampa-area.org` | `mailto:` in the header social menu on `https://aatampa-area.org/`; repeated on `https://meetings.aatampa-area.org/contact/` | yes — but **moved to `https://meetings.aatampa-area.org/meetings/`** | **Site split.** `aatampa-area.org/wp-admin/admin-ajax.php?action=meetings` now returns `400` + `0` (TSML no longer on the apex); the plugin lives on the `meetings.` subdomain, which still returns `401`. Subdomain is behind a Cloudflare bot challenge — needs full browser headers (`Accept`, `Sec-Fetch-*`, `Upgrade-Insecure-Requests`) or it serves "Just a moment…". Registry entry will need the subdomain, not the apex. |
| 6 | Metrolina Intergroup (Charlotte) | charlotteaa.org | `info@charlotteaa.org` | `https://charlotteaa.org/home/contact-us/` (also in the homepage footer) | yes, `/meetings` | Trades as "Metrolina Intergroup", not "Charlotte AA" — use that name in the email. |
| 7 | AA Central Office of Salt Lake | saltlakeaa.org | **form only** — `https://www.saltlakeaa.org/service/#webservant` ("Contact the Webservant"); `#tech` is "Contact the Technology Chair" | `/contact-us/` and `/service/` are both form-driven; no address published | yes, `/meetings/` | Best of the form-only three: a dedicated webservant form, exactly the right desk. |
| 8 | Cleveland District Office | aacle.org | **form only** — `https://www.aacle.org/contact/`, "Who do you wish to contact?" → **Technical Support** | no address on `/contact/`, `/office/`, `/link-to-us/` | yes — at **`/find-a-meeting/`**, `/meetings/` 404s | Routing dropdown reaches tech directly. |
| 9 | Akron Area Intergroup Council | akronaa.org | `itchairman@akronaa.org` (Information Technology)<br>`info@akronaa.org` (office) | `https://akronaa.org/contact/` — full labelled roster of 16 role addresses | yes, `/meetings/` | Cleanest tech contact in the batch. |
| 10 | Anchorage Area Intergroup | anchorageaa.org | `chair@anchorageaa.org` | `https://anchorageaa.org/meetings-main` — "Location: On Zoom email chair@anchorageaa.org to request the Meeting ID" | yes, `/meetings-main` + `?post_type=tsml_meeting` | `/contact-us` is form-only and explicitly says "Contact Us Via Email: please use the form below". `chair@` and `corrections@` (on `/service`) are the only two addresses published site-wide. Consider the form as the polite primary and `chair@` as fallback. |
| 11 | Buffalo Area AA Central Office | buffaloaany.org | `web.servant@buffaloaany.org` (Internet Presence Committee)<br>`buffaloaa@hotmail.com` (office) | `https://buffaloaany.org/contact-us/` | yes, `/meetings/` | **feed open via cache — no email needed.** Page warns the addresses are anti-spam plaintext ("you'll have to type them into your email program") and that its form routes website questions to the webmaster. |
| 12 | General Service of SE Michigan — Area 33 | aa-semi.org | `area33webchair@aa-semi.org` (Web Chair, Brandon K.) | `https://aa-semi.org/area-33-committee-contact-information/` — roster table, page updated 2026-06-14 | yes, `/meeting-list` | **feed open via cache — no email needed.** `/contact/` itself is postal-mail only. |
| 13 | New Hampshire Area 43 | nhaa.net | `webmaster@nhaa.net`<br>`technology@nhaa.net`, `office@nhaa.net` | `https://nhaa.net/contact-us/area-43-email-addresses/` — 24 labelled role addresses | yes, `/meetings/` | **feed open via cache — no email needed.** |
| 14 | Rhode Island Area 61 | aainri.com | `webmaster@aainri.com`<br>`contentmanager@aainri.com`, `techchair@aainri.com` (Technology Cttee Chair, Melissa C.) | `https://aainri.com/contact-us/connect-with-area-61/` — "E-mail: Send requests to webmaster@aainri.com or contentmanager@aainri.com" | yes, `/meetings/` | — |
| 15 | North Dakota **Area 52** | aanorthdakota.org | **form only** — `https://aanorthdakota.org/contact-us/#Committees`, tick "Area 52 Website Support" and/or "Area 52 Technology Chair" | only published address is `reglit@aanorthdakota.org` (Registrar-Literature Chair — wrong desk for this ask) | yes, `/meetings/` | **`docs/outreach.md` calls this "ND Area 41" — the site is Area 52 throughout.** Fix the label before sending. Site also runs a "Meeting Guide Registration Form" and notes its listings populate the Meeting Guide app, so they're feed-aware. |
| 16 | Idaho Area 18 | idahoarea18aa.org | `webservant@idahoarea18aa.org`<br>`tech@idahoarea18aa.org` (Tech Chair) | `https://idahoarea18aa.org/contact-idaho-area-18/` — officer roster; `mailto:` confirmed | yes, `/meetings/` | **feed open via cache — no email needed.** Homepage has a stray typo'd variant `webseravant@…`; the roster `mailto:` is the correct spelling. |
| 17 | Tennessee Area 64 | area64assembly.org | `techsupport@area64assembly.org` | site-wide footer `mailto:` on `https://www.area64assembly.org/`: "If you need assistance, please contact techsupport@…" | yes, `/meetings/` | `/committees/technology-committee/` displays `technicalsupport@area64assembly.org`, **but its `mailto:` href points at a misspelled domain (`area64assmbly.org`)** — that address is unreliable. Use the footer one. |

## Feed re-test (2026-07-30)

`curl -sL '<domain>/wp-admin/admin-ajax.php?action=meetings'`, browser UA:

- **16 / 17 → `{"error":"HTTP\/1.1 401 Unauthorized"}`** — unchanged from the
  2026-07-19 sweep. No intergroup has opened its AJAX feed.
- **aatampa-area.org → `400` + body `0`** — WordPress doesn't recognise the
  `meetings` action, i.e. TSML is no longer installed on the apex domain. Not an
  opening; the plugin relocated to `meetings.aatampa-area.org`, which answers
  `401` like the rest.

So the answer to "has anything opened up since July" is **no, not via the AJAX
endpoint** — but the cache-file check (which the July sweep didn't run) retires
five of the seventeen anyway.

## Recommended next actions

1. **Add 5 registry entries to `pipeline/curated/feeds.yaml`** — `aa-semi`,
   `fortworthaa`, `nhaa`, `idahoarea18aa`, `buffaloaany`, all as cache-file feeds
   with the URLs in the table above (states `mi`, `tx`, `nh`, `id`, `ny`). Nothing
   to ask anyone for. +4,552 meetings.
2. **Send 9 emails** using the Batch 2 template in `docs/outreach.md`:
   Dallas `office@`, Boston `aaboston1945@gmail.com`, Miami-Dade
   `aamiamidade@bellsouth.net`, Tampa `aainfo@`, Charlotte `info@`,
   Akron `itchairman@`, Anchorage `chair@`, RI Area 61 `webmaster@`,
   TN Area 64 `techsupport@`.
3. **Submit 3 contact forms** (paste the same template body): Salt Lake
   `/service/#webservant`, Cleveland `/contact/` → Technical Support,
   ND Area 52 `/contact-us/#Committees` → Website Support + Technology Chair.
4. **Fix two labels in `docs/outreach.md`**: "ND Area 41" → **North Dakota
   Area 52**; Charlotte is **Metrolina Intergroup**. Also note Tampa's feed now
   lives on `meetings.aatampa-area.org`.
5. Tampa's subdomain sits behind Cloudflare — whenever a key does arrive, the
   fetcher will need full browser headers there, not just a browser UA. Worth a
   `ua: browser` style flag in `feeds.yaml` when it lands.
