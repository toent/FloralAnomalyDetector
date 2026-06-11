import argparse
import csv
import re
import sys
import time
import os
import json
import requests

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# Wikimedia asks for a descriptive User-Agent. Put your contact info here.
HEADERS = {"User-Agent": "FloraDatasetBuilder/2.0 (educational project; contact: you@example.com)"}

ROOT_CATEGORY = "Category:Flora by country"

# Page title prefixes that are never individual plant taxa, skipped early to save API calls. Anything else still has to pass the Wikidata P225 check.
SKIP_TITLE_PREFIXES = (
    "List of", "Lists of", "Flora of", "Fauna of", "Index of",
    "Outline of", "Glossary of", "Vegetation of", "Forests of",
    "Endemism in", "Wildlife of", "Environment of", "Protected areas",
)

# Subcategories matching these are not followed during recursion.
SKIP_SUBCAT_KEYWORDS = ("fauna", "animals", "fungi", "birds", "insects", "lists of")

# Words in the lead sentence that confirm the article is about a plant.
PLANT_HINTS = (
    "plant", "tree", "shrub", "herb", "grass", "fern", "moss", "vine",
    "orchid", "cactus", "flower", "conifer", "palm", "sedge", "liverwort",
    "hornwort", "alga", "algae", "cycad", "bamboo", "succulent", "legume",
)

# Words that mark the article as something other than a plant.
NON_PLANT_HINTS = (
    "species of bird", "species of insect", "species of mammal",
    "species of fish", "species of moth", "species of butterfly",
    "species of beetle", "species of spider", "species of snail",
    "species of reptile", "species of amphibian", "species of fungus",
    "genus of fungi", "genus of moths", "genus of beetles",
    "genus of birds", "species of lichen", "lichenized fungus",
)

# Habitat label mapped to keywords searched in the article intro.
HABITAT_KEYWORDS = {
    "grasslands": ("grassland", "savanna", "prairie", "steppe", "meadow"),
    "desert": ("desert", "arid", "semi-arid", "xeric"),
    "mountains": ("mountain", "alpine", "montane", "subalpine", "highland"),
    "water": ("aquatic", "wetland", "marsh", "swamp", "lake", "river",
              "stream", "pond", "bog", "riparian", "floodplain"),
    "forest": ("forest", "woodland", "rainforest", "jungle"),
    "coastal": ("coastal", "dune", "seashore", "beach", "mangrove", "salt marsh"),
    "shrubland": ("shrubland", "scrub", "heath", "chaparral", "fynbos"),
    "tundra": ("tundra",),
}

HEADERS = {"User-Agent": "FloraDatasetBuilder/2.0 (Fontys student project; mats.yourname@student.fontys.nl)"}


def api_get(url, params, retries=5):
    params = dict(params)
    params["format"] = "json"
    params["formatversion"] = 2
    params["maxlag"] = 5
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)

            # 429 means we are told to back off. Honor Retry-After if present.
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 30))
                print(f"  Rate limited, waiting {wait}s as instructed...")
                time.sleep(wait + 1)
                continue

            r.raise_for_status()
            data = r.json()
            if "error" in data and data["error"].get("code") == "maxlag":
                print("  Server busy (maxlag), waiting 5s...")
                time.sleep(5)
                continue
            return data
        except (requests.exceptions.HTTPError,
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            if attempt < retries - 1:
                wait = 10 * (attempt + 1)
                print(f"  Request failed ({e}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    return {}


def get_country_categories():
    """Return a list of (category_title, country_name) under Flora by country."""
    countries = []
    cmcontinue = None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": ROOT_CATEGORY,
            "cmtype": "subcat",
            "cmlimit": 500,
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        data = api_get(WIKI_API, params)
        for member in data.get("query", {}).get("categorymembers", []):
            title = member["title"]
            m = re.match(r"^Category:Flora of (.+)$", title)
            if not m:
                continue
            country = re.sub(r"^[Tt]he ", "", m.group(1)).strip()
            countries.append((title, country))
        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
        time.sleep(0.1)
    return countries


def get_category_pages(category_title, max_depth=2, max_pages=None):
    """Collect article pages (pageid, title) in a category, recursing into
    subcategories up to max_depth levels."""
    pages = []
    visited = {category_title}
    queue = [(category_title, 0)]

    while queue:
        cat, depth = queue.pop(0)
        cmcontinue = None
        while True:
            params = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": cat,
                "cmtype": "page|subcat",
                "cmlimit": 500,
            }
            if cmcontinue:
                params["cmcontinue"] = cmcontinue
            data = api_get(WIKI_API, params)
            for member in data.get("query", {}).get("categorymembers", []):
                title = member["title"]
                if member["ns"] == 14:
                    lower = title.lower()
                    if depth + 1 <= max_depth and title not in visited \
                            and not any(k in lower for k in SKIP_SUBCAT_KEYWORDS):
                        visited.add(title)
                        queue.append((title, depth + 1))
                elif member["ns"] == 0:
                    if not title.startswith(SKIP_TITLE_PREFIXES):
                        pages.append((member["pageid"], title))
                        if max_pages and len(pages) >= max_pages:
                            return pages
            cmcontinue = data.get("continue", {}).get("cmcontinue")
            if not cmcontinue:
                break
            time.sleep(0.1)
        time.sleep(0.1)
    return pages


def fetch_page_details(titles):
    """For up to 20 titles, return {title: {"extract": str, "qid": str}}."""
    out = {}
    params = {
        "action": "query",
        "titles": "|".join(titles),
        "redirects": 1,
        "prop": "extracts|pageprops",
        "exintro": 1,
        "explaintext": 1,
        "exlimit": "max",
        "ppprop": "wikibase_item",
    }
    data = api_get(WIKI_API, params)
    query = data.get("query", {})

    # Map redirected titles back to the names we asked for.
    redirect_map = {}
    for rd in query.get("redirects", []):
        redirect_map[rd["to"]] = rd["from"]

    for page in query.get("pages", []):
        if page.get("missing"):
            continue
        title = page["title"]
        original = redirect_map.get(title, title)
        out[original] = {
            "extract": page.get("extract", "") or "",
            "qid": page.get("pageprops", {}).get("wikibase_item", ""),
        }
    return out


def fetch_wikidata_names(qids):
    """For up to 50 QIDs, return {qid: (scientific_name, common_name)}."""
    out = {}
    params = {
        "action": "wbgetentities",
        "ids": "|".join(qids),
        "props": "claims|labels",
        "languages": "en",
    }
    data = api_get(WIKIDATA_API, params)
    for qid, entity in data.get("entities", {}).items():
        if "missing" in entity:
            continue
        claims = entity.get("claims", {})

        sci = ""
        for claim in claims.get("P225", []):
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(value, str) and value:
                sci = value
                break

        common = ""
        for claim in claims.get("P1843", []):
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(value, dict) and value.get("language") == "en":
                common = value.get("text", "")
                break

        # Fall back to the English label when it differs from the scientific name.
        if not common:
            label = entity.get("labels", {}).get("en", {}).get("value", "")
            if label and label.lower() != sci.lower():
                common = label

        out[qid] = (sci, common)
    return out


def looks_like_plant(extract):
    head = extract[:400].lower()
    if any(hint in head for hint in NON_PLANT_HINTS):
        return False
    return any(re.search(r"\b" + re.escape(hint), head) for hint in PLANT_HINTS)


def detect_habitat(extract):
    text = extract.lower()
    found = []
    for label, keywords in HABITAT_KEYWORDS.items():
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw), text):
                found.append(label)
                break
    return "; ".join(found)


def chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def scrape(output_path, max_countries=None, max_pages_per_country=None,
           depth=2, species_only=True):
    cache_path = output_path + ".pages.json"

    if os.path.exists(cache_path):
        print(f"Loading cached page list from {cache_path}...")
        with open(cache_path, encoding="utf-8") as f:
            page_countries = {t: set(c) for t, c in json.load(f).items()}
    else:
        print("Fetching country categories...")
        countries = get_country_categories()
        if max_countries:
            countries = countries[:max_countries]
        print(f"Found {len(countries)} country categories.")

        page_countries = {}
        for i, (cat_title, country) in enumerate(countries, 1):
            print(f"[{i}/{len(countries)}] Collecting pages for {country}...")
            pages = get_category_pages(cat_title, max_depth=depth,
                                       max_pages=max_pages_per_country)
            for _, title in pages:
                page_countries.setdefault(title, set()).add(country)
            print(f"  {len(pages)} pages (unique plants so far: {len(page_countries)})")

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({t: sorted(c) for t, c in page_countries.items()}, f)
        print(f"Page list cached to {cache_path}")

    titles = sorted(page_countries.keys())
    print(f"\nProcessing {len(titles)} unique pages...")

    rows_written = 0
    skipped = 0
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["common_name", "scientific_name", "country", "habitat"])
        writer.writeheader()

        for batch_num, title_batch in enumerate(chunks(titles, 20), 1):
            details = fetch_page_details(title_batch)
            time.sleep(0.1)

            # Resolve names for the whole batch in one Wikidata call.
            qids = [d["qid"] for d in details.values() if d["qid"]]
            names = {}
            for qid_batch in chunks(qids, 50):
                names.update(fetch_wikidata_names(qid_batch))
                time.sleep(0.1)

            for title in title_batch:
                detail = details.get(title)
                if not detail or not detail["qid"]:
                    skipped += 1
                    continue

                sci, common = names.get(detail["qid"], ("", ""))

                # No P225 taxon name means the page is not a taxon at all.
                if not sci:
                    skipped += 1
                    continue

                # Keep species and below; genus names have no space.
                if species_only and " " not in sci:
                    skipped += 1
                    continue

                if not looks_like_plant(detail["extract"]):
                    skipped += 1
                    continue

                habitat = detect_habitat(detail["extract"])
                for country in sorted(page_countries[title]):
                    writer.writerow({
                        "common_name": common,
                        "scientific_name": sci,
                        "country": country,
                        "habitat": habitat,
                    })
                    rows_written += 1

            f.flush()
            if batch_num % 10 == 0:
                done = min(batch_num * 20, len(titles))
                print(f"  {done}/{len(titles)} pages, {rows_written} rows, "
                      f"{skipped} skipped")

    print(f"\nDataset saved to: {output_path}")
    print(f"Total rows: {rows_written}, skipped non-taxon/non-plant pages: {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build a flora dataset from Wikipedia's Category:Flora by country")
    parser.add_argument("output", nargs="?", default="flora_dataset.csv")
    parser.add_argument("--max-countries", type=int, default=None,
                        help="Limit number of country categories (useful for testing)")
    parser.add_argument("--max-pages-per-country", type=int, default=None,
                        help="Limit pages collected per country (useful for testing)")
    parser.add_argument("--depth", type=int, default=2,
                        help="Subcategory recursion depth inside each country (default 2)")
    parser.add_argument("--include-genera", action="store_true",
                        help="Also include genus-level articles, not just species")
    args = parser.parse_args()

    try:
        scrape(args.output,
               max_countries=args.max_countries,
               max_pages_per_country=args.max_pages_per_country,
               depth=args.depth,
               species_only=not args.include_genera)
    except KeyboardInterrupt:
        print("\nInterrupted. Partial CSV is saved (rows are flushed per batch).")
        sys.exit(1)