import os
import re
import json
import time
import requests
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from bs4 import BeautifulSoup
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================

API_KEY = "6ddd278bf17648ac"

BASE_URL = "https://api.queryly.com/json.aspx"

# Keep your current 48-hour behaviour
end_date = datetime.now()
start_date = end_date - timedelta(hours=48)

CUTOFF_UNIX = int(start_date.timestamp())


# ============================================================
# FILE / FOLDER CONFIG
# ============================================================
BASE_DIR = Path(__file__).resolve().parents[1]
RESOURCES_DIR = BASE_DIR / "dags" / "resources"
OUTPUT_DIR = BASE_DIR / "output"
FOLDER_NAME = OUTPUT_DIR / "The_Star"

# Adjust this path if your actual keywords.json is elsewhere
KEYWORDS_PATH = RESOURCES_DIR / "keywords.json"

# Adjust this path if your actual categories.json is elsewhere
CATEGORIES_PATH = RESOURCES_DIR / "categories.json"

# Location mapping file
LOCATIONS = RESOURCES_DIR / "countries.json"


# Create output folder if it does not exist
os.makedirs(FOLDER_NAME, exist_ok=True)


# ============================================================
# LOAD KEYWORDS
# ============================================================

with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
    kw_data = json.load(f)

keywords = kw_data["language"][0]["English"]["keywords"]


# ============================================================
# LOAD ALLOWED CATEGORIES
# ============================================================

with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
    cat_data = json.load(f)

allowed_categories = set()

for entry in cat_data["publication"][0].values():
    if entry["source"] == "theStar":
        allowed_categories.update(entry["category"])

allowed_categories_lower = {
    c.lower() for c in allowed_categories
}


# ============================================================
# LOAD COUNTRY / LOCATION MAPPING
# ============================================================

with open(LOCATIONS, "r", encoding="utf-8") as f:
    raw_country_map = json.load(f)

country_map = {
    country: set(loc.lower() for loc in locations)
    for country, locations in raw_country_map.items()
}


# ============================================================
# COUNTRY DETECTION
# ============================================================

def detect_country_from_text(text, country_map):
    """
    Detect country from the beginning of the article text.

    The first section before ':' or '-' is treated as the
    location/source identifier.

    Example:
        "Malaysia: Former minister..." -> Malaysia

        "Singapore - Former director..." -> Singapore

        "Kuala Lumpur: ..." -> Malaysia
        (if Kuala Lumpur exists in locations.json)
    """

    if not text:
        return ""

    first_part = re.split(r'[:\-]', text, maxsplit=1)[0].strip()

    first_part = re.sub(
        r'\(.*?\)',
        '',
        first_part
    ).strip().rstrip(',').lower()

    if not first_part:
        return ""

    for country, locations in country_map.items():
        if first_part in locations:
            return country

    return ""


# ============================================================
# API HELPER
# ============================================================

def fetch_page(query, endindex=0, batchsize=100):
    """
    Return a single page of results from Queryly.
    """

    params = {
        "queryly_key": API_KEY,
        "query": query,
        "endindex": endindex,
        "batchsize": batchsize,
        "sort": "date",
        "timezoneoffset": "-450",
        "extendeddatafields": (
            "paywalltype,isexclusive,kicker,kickerurl,"
            "summary,sponsor"
        ),
        "showfaceted": "true",
    }

    r = requests.get(
        BASE_URL,
        params=params,
        timeout=30
    )

    r.raise_for_status()

    return r.json()


# ============================================================
# COLLECT ARTICLES FOR KEYWORD
# ============================================================

def collect_articles_for_keyword(keyword, cutoff_unix):
    """
    Paginate through all results for a keyword until articles
    are older than cutoff.
    """

    all_items = []

    endindex = 0
    batchsize = 100

    while True:

        data = fetch_page(
            keyword,
            endindex,
            batchsize
        )

        items = data.get("items", [])

        if not items:
            break

        # Stop early if the last item is already older
        # than cutoff because results are date-sorted.
        last_pub = items[-1].get(
            "pubdateunix",
            0
        )

        all_items.extend(items)

        if last_pub < cutoff_unix:
            break

        endindex += batchsize

        time.sleep(0.5)

    return all_items


# ============================================================
# MAIN ARTICLE COLLECTION
# ============================================================

collected = {}

seen_urls = set()


for kw in keywords:

    print(f"Searching: {kw}")

    items = collect_articles_for_keyword(
        kw,
        CUTOFF_UNIX
    )

    for item in items:

        url = item.get("link")

        if not url or url in seen_urls:
            continue

        pub_unix = item.get(
            "pubdateunix",
            0
        )

        if pub_unix < CUTOFF_UNIX:
            continue

        kicker = item.get(
            "kicker",
            ""
        ).strip().lower()

        if kicker not in allowed_categories_lower:
            continue

        seen_urls.add(url)

        collected[url] = {

            "Title": item.get("title"),

            "Link": url,

            "Date": datetime.fromtimestamp(
                pub_unix
            ).strftime("%Y-%m-%d %H:%M"),

            "Category": item.get("kicker"),

            "Intro": item.get(
                "description",
                ""
            ),

            "Paywall": item.get(
                "paywalltype",
                ""
            ),

            "Keyword": kw,
        }


print(
    f"Collected {len(collected)} unique "
    f"articles in the last 48h."
)


# ============================================================
# FETCH FULL ARTICLE TEXT
# ============================================================

def fetch_full_text(url):
    """
    Fetch the article page and extract story-body text
    from the non-paywalled portion.
    """

    try:

        r = requests.get(
            url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        r.raise_for_status()

        soup = BeautifulSoup(
            r.text,
            "html.parser"
        )

        body = soup.find(
            "div",
            id="story-body"
        )

        if body:

            return " ".join(
                p.get_text(strip=True)
                for p in body.find_all("p")
            )

    except Exception as e:

        print(
            f"  ⚠️ Could not fetch {url}: {e}"
        )

    return ""


# ============================================================
# ADD FULL TEXT
# ============================================================

for url, art in collected.items():

    print(f"Fetching article: {url}")

    art["FullText"] = fetch_full_text(url)

    time.sleep(0.5)


# ============================================================
# ADD COUNTRY
# ============================================================

for url, art in collected.items():

    # Country detection is based on FullText,
    # as requested.
    art["Country"] = detect_country_from_text(
        art.get("FullText", ""),
        country_map
    )


# ============================================================
# CREATE DATAFRAME
# ============================================================

df = pd.DataFrame(
    collected.values()
)


# ============================================================
# FILE NAMING
# ============================================================

start_date_str = start_date.strftime(
    "%d %B %Y"
)

end_date_str = end_date.strftime(
    "%d %B %Y"
)

master_file = os.path.join(
    FOLDER_NAME,
    "Master_The_Star.xlsx"
)

temp_file = os.path.join(
    FOLDER_NAME,
    f"{start_date_str}_{end_date_str}_The_Star.xlsx"
)


# ============================================================
# SAVE TEMPORARY DATE-RANGE FILE
# ============================================================

df.to_excel(
    temp_file,
    index=False
)

print(
    f"Saved date-range file: {temp_file}"
)


# ============================================================
# OPTIONAL MASTER FILE
# ============================================================

# If you want to retain the existing Master_The_Star.xlsx
# separately, this saves the current result there as well.

df.to_excel(
    master_file,
    index=False
)

print(
    f"Saved master file: {master_file}"
)


# ============================================================
# SUMMARY
# ============================================================

print(
    f"Total articles: {len(df)}"
)

print(
    f"Date range: "
    f"{start_date_str} - {end_date_str}"
)

print(
    f"Files created:"
)

print(
    f"  - {temp_file}"
)

print(
    f"  - {master_file}"
)

conn = psycopg2.connect(host="192.168.1.132", database="adverse_media", user="postgres", password="Verity@456")
cursor = conn.cursor()

# ✅ Insert df_temp into PostgreSQL
if not df.empty:
    insert_sql = """
        INSERT INTO public.raw_input_table (
            "pdf_uuid", "Date", "Category", "Media Source", "Country",
            "Links", "Publication", "Title", "Article Text",
            "Subject", "Status", "Type"
        )
        VALUES %s
        ON CONFLICT DO NOTHING;
    """
    
    rows_to_insert = [
        (
            str(uuid.uuid4()),       # pdf_uuid
            datetime.strptime(row["Date"], "%Y-%m-%d %H:%M").strftime("%Y-%m-%d") if row["Date"] else None,             # Date
            row["Keyword"],         # Category
            row["Category"],     # Media Source
            row["Country"],          # Country
            row["Link"],            # Links
            "The Star",      # Publication
            row["Title"],            # Title
            row["FullText"],     # Article Text
            "",          # Subject
            1,           # Status
            "",             # Type
        )
        for _, row in df.iterrows()
    ]
    execute_values(cursor, insert_sql, rows_to_insert)
    conn.commit()
    print(f"✅ Inserted {len(rows_to_insert)} rows into PostgreSQL")
else:
    print("⚠️ No new rows to insert into PostgreSQL")

try:
    dedup_query = """
    WITH ranked AS (
        SELECT 
            ctid,
            ROW_NUMBER() OVER (
                PARTITION BY "Links"
                ORDER BY 
                    "Status" DESC,
                    "Date" DESC
            ) AS rn
        FROM raw_input_table
    )
    DELETE FROM raw_input_table
    WHERE ctid IN (
        SELECT ctid
        FROM ranked
        WHERE rn > 1
    );
    """

    cursor.execute(dedup_query)
    conn.commit()

    print("🧹 Deduplication complete")

except Exception as e:
    print(f"❌ Deduplication failed: {e}")
    conn.rollback()

# ✅ Close DB connection
finally:
    cursor.close()
    conn.close()
    print("✅ Database connection closed")
