"""State-published WIC clinic layers (ArcGIS) -> site records (food, family).

There is no national WIC clinic dataset; a handful of state health departments
publish their clinic directory as a public ArcGIS layer. The curated registry
(pipeline/curated/wic-layers.yaml) lists verified layers with a per-layer field
mapping; this module harvests every entry. A broken layer is skipped loudly
rather than failing the run — but if fewer than 3 layers (or 200 clinics
total) survive, the module aborts without writing.

Ownership: records cite wic/<layer-id>; replace_records("sites", "wic/", ...)
owns the whole family, including layers since removed from the registry.

Usage: python3 -m pipeline.wic [--force]
"""
import json
import re
import sys
from urllib.parse import quote

from .emit import Places, replace_records, today, write_source
from .util import Flow, ROOT, SOURCES, fetch, load_yaml

REGISTRY = ROOT / "pipeline" / "curated" / "wic-layers.yaml"
PAGE_SIZE = 1000
DESCRIPTION = ("WIC clinic — Special Supplemental Nutrition Program for Women, "
               "Infants, and Children: healthy food benefits, nutrition counseling, "
               "and breastfeeding support for pregnant and postpartum parents and "
               "children under 5.")
# combined single-line address: "12501 Willowbrook Rd SE, Cumberland, MD 21502"
ADDR_RE = re.compile(r"^(.+),\s*([^,]+?),\s*([A-Za-z]{2})\.?(?:\s+(\d{5})(?:-\d{4})?)?\s*$")
_DIGITS = re.compile(r"\d")


def clean(value) -> str:
    """Stringify + strip; some feeds pad values with non-breaking spaces."""
    if value is None:
        return ""
    return str(value).replace("\xa0", " ").strip()


def clean_phone(raw: str) -> str | None:
    digits = "".join(_DIGITS.findall(raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return None


def clean_zip(value) -> str | None:
    s = clean(value)
    if s.endswith(".0"):  # zip codes that arrived as floats
        s = s[:-2]
    return s if re.fullmatch(r"\d{5}", s) else None


def titlecase(text: str) -> str:
    return re.sub(r"\bWic\b", "WIC", text.title())


def harvest(layer, force) -> list[dict]:
    """Fetch every feature of one registry layer; returns raw feature list."""
    features, offset, page = [], 0, 1
    order = quote(layer["oid"])
    while True:
        cache = SOURCES / "wic" / f"{layer['id']}-p{page}.json"
        url = (f"{layer['url']}/query?where=1%3D1&outFields=*&f=json&outSR=4326"
               f"&orderByFields={order}&resultRecordCount={PAGE_SIZE}"
               f"&resultOffset={offset}")
        data = json.loads(fetch(url, cache, force=force).read_text())
        if "features" not in data:
            raise SystemExit(f"wic/{layer['id']}: unexpected payload: {str(data)[:200]}")
        features.extend(data["features"])
        if not data.get("exceededTransferLimit") and len(data["features"]) < PAGE_SIZE:
            return features
        offset += len(data["features"])
        page += 1


def main(argv):
    force = "--force" in argv
    places = Places()
    registry = load_yaml(REGISTRY)

    records, layers_ok, skipped = [], 0, []
    for layer in registry:
        lid, state, fmap = layer["id"], layer["state"], layer["fields"]
        try:
            features = harvest(layer, force)
        except SystemExit as e:
            skipped.append(lid)
            print(f"wic: SKIPPING layer {lid}: {e}")
            continue

        source_id = write_source(
            "wic", lid, kind="dataset", publisher=layer["publisher"],
            title=layer["title"], url=layer["url"], tier="primary",
        )
        count, seen = 0, set()
        for feat in features:
            a = feat["attributes"]
            f = {k: clean(a.get(v)) for k, v in fmap.items()}
            if layer.get("caps"):
                f = {k: titlecase(v) if k != "zip" else v for k, v in f.items()}
            name = f.get("name", "")
            if not name:
                continue
            if "wic" not in name.lower():
                name += " WIC Clinic"

            street = f.get("street") or None
            city, zip5 = f.get("city", ""), clean_zip(f.get("zip"))
            if f.get("address"):  # combined one-line address field
                m = ADDR_RE.match(f["address"])
                if m and m.group(3).lower() == state:
                    street, city = m.group(1).strip(), m.group(2).strip()
                    zip5 = m.group(4)
            key = (name.lower(), (street or "").lower(), city.lower())
            if key in seen:
                continue
            seen.add(key)

            geoid, place_slug = places.resolve(state, city)
            rec = {
                "_state": state, "_place_slug": place_slug, "_name": name,
                "categories": ["food", "family-support"],
            }
            desc = DESCRIPTION
            agency = f.get("agency")
            if agency and agency.lower() not in name.lower():
                desc += f" Operated by {agency}."
            if f.get("note"):
                desc += f" ({f['note']})"
            rec["description"] = desc
            if city:
                rec["address"] = Flow({k: v for k, v in {
                    "street": street, "street2": f.get("street2") or None,
                    "city": city, "state": state, "zip": zip5,
                }.items() if v})
            geom = feat.get("geometry") or {}
            if isinstance(geom.get("y"), (int, float)) and 15 < geom["y"] <= 72:
                rec["geo"] = Flow(lat=round(geom["y"], 5), lng=round(geom["x"], 5))
                if not geoid:  # city didn't resolve; fall back to nearest, state-matched
                    near = places.nearest(geom["y"], geom["x"])
                    if near and near[0] == state:
                        geoid, place_slug = near[1], near[2]
                        rec["_place_slug"] = place_slug
            if geoid:
                rec["place"] = geoid
            phone = clean_phone(f.get("phone", ""))
            if phone:
                rec["phone"] = phone
            website = f.get("website", "")
            if website.startswith("http"):
                rec["website"] = website
            email = f.get("email", "")
            if "@" in email:
                rec["email"] = email
            rec["external_ids"] = Flow(wic=f"{lid}:{a.get(layer['oid'])}")
            rec["sources"] = [source_id]
            rec["verified"] = Flow(on=today(), method="api")
            records.append(rec)
            count += 1
        layers_ok += 1
        print(f"wic/{lid}: {count} clinics")

    if skipped:
        print(f"wic: skipped layers: {', '.join(skipped)}")
    if layers_ok < 3:
        raise SystemExit(f"wic: only {layers_ok} working layers — not writing")
    if len(records) < 200:
        raise SystemExit(f"wic: only {len(records)} clinics total — not writing")

    replace_records("sites", "wic/", records)


if __name__ == "__main__":
    main(sys.argv[1:])
