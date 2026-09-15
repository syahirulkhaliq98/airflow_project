from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from datetime import datetime
from psycopg2.extras import execute_values
from datetime import datetime, timedelta
from urllib.parse import urlparse
from pathlib import Path
from fpdf import FPDF
import psycopg2, re, json, os, time
from webdriver_manager.chrome import ChromeDriverManager
from datetime import date as dt_date
import pandas as pd
from PIL import Image
import re
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from gridfs import GridFS


BASE_DIR = Path(__file__).resolve().parents[1]
RESOURCES_DIR = BASE_DIR / "dags" / "resources"
OUTPUT_DIR = BASE_DIR / "output"

category_path = str(Path(os.getenv("CATEGORY_PATH", RESOURCES_DIR / "categories.json")))
keyword_path = str(Path(os.getenv("KEYWORD_PATH", RESOURCES_DIR / "keywords.json")))
countries_path = str(Path(os.getenv("COUNTRIES_PATH", RESOURCES_DIR / "countries.json")))
excel_path = str(Path(os.getenv("OUTPUT_PATH", OUTPUT_DIR / "IDN Times")))

# conn = psycopg2.connect(host="localhost", database="adverse_media", user="postgres", password="Verity@456")
# cursor = conn.cursor()

os.makedirs(excel_path, exist_ok=True)

# Setup Chrome
def init_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--incognito")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-browser-side-navigation")
    options.add_argument("--enable-unsafe-swiftshader")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--log-level=3")
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-ssl-errors')
    options.add_argument("--start-maximized")
    options.binary_location = "/usr/bin/google-chrome"
    driver = webdriver.Chrome(
        service=Service("/usr/local/bin/chromedriver"),
        options=options
    )
    return driver

MONGO_URI = "mongodb://127.0.0.1:27017/"
MONGO_DB_NAME = "adverse_media"

mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]

raw_articles_collection = mongo_db["raw_articles"]
grid_fs = GridFS(mongo_db)

raw_articles_collection.create_index(
    "article_id",
    unique=True
)

print("✅ Connected to MongoDB")

def get_article_card_from_title(title_elem):
    candidate_xpaths = [
        "./ancestor::div[.//span[@data-testid='publish-date-article'] and .//span[contains(@data-cy,'ds-card-article-category')]][1]",
        "./ancestor::div[.//span[@data-testid='publish-date-article']][1]",
        "./ancestor::div[1]"
    ]

    for xpath in candidate_xpaths:
        try:
            return title_elem.find_element(By.XPATH, xpath)
        except Exception:
            continue

    return title_elem

# first init
driver = init_driver()

# Load keywords
with open(keyword_path, "r", encoding="utf-8") as f:
    data = json.load(f)

languages = data["language"][0]
english_keywords = languages.get("English", {}).get("keywords", [])
# malay_keywords = languages.get("Malay", {}).get("keywords", [])
indo_keywords = languages.get("Indo", {}).get("keywords", [])
all_keywords = indo_keywords 

# Load country mapping
with open(countries_path, "r", encoding="utf-8") as f:
    country_map = json.load(f)

def detect_country_from_text(article_text, country_map):
    if not article_text:
        return ""

    text = article_text.strip()
    location = ""

    # =========================================================
    # 1. Extract leading location
    # =========================================================

    patterns = [
        # KOMPAS
        r'^([A-ZÀ-ÿ\s]+),\s*KOMPAS\.com\s*[-—]',

        # ANTARA
        r'^([A-ZÀ-ÿ\s]+)\s*\(ANTARA\)',

        # IDN Times
        r'^([A-ZÀ-ÿ\s]+),\s*IDN\s*Times\s*[-—]',

        # CNN Indonesia
        r'^([A-ZÀ-ÿ\s]+),\s*CNN\s*Indonesia\s*[-—]',

        # Detik
        r'^([A-ZÀ-ÿ\s]+)\s*-\s*detik',

        # Generic news style
        r'^([A-ZÀ-ÿ\s]+),\s*[A-Za-z0-9\s\.]+\s*[-—]'
    ]

    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)

        if match:
            location = match.group(1).strip()
            break

    if not location:
        return ""

    # =========================================================
    # 2. Normalize
    # =========================================================

    location = re.sub(r'\s+', ' ', location).upper().strip()

    # =========================================================
    # 3. Split city / region
    # =========================================================

    if "," in location:
        city, region = [x.strip() for x in location.split(",", 1)]
    else:
        city = location
        region = ""

    # =========================================================
    # 4. Match against country map
    # =========================================================

    for country, regions in country_map.items():

        normalized_regions = [
            re.sub(r'\s+', ' ', r).upper().strip()
            for r in regions
        ]

        if (
            location in normalized_regions
            or city in normalized_regions
            or region in normalized_regions
        ):
            return country

    # =========================================================
    # 5. Fallback
    # =========================================================

    return ""

import re
from datetime import datetime

def convert_indo_date(date_text):
    month_map = {
        "Jan": "01",
        "Feb": "02",
        "Mar": "03",
        "Apr": "04",
        "Mei": "05",
        "Jun": "06",
        "Jul": "07",
        "Agu": "08",
        "Sep": "09",
        "Okt": "10",
        "Nov": "11",
        "Des": "12"
    }

    match = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', date_text)

    if not match:
        return None, ""

    day, month_name, year = match.groups()

    month = month_map.get(month_name.capitalize())

    if not month:
        return None, ""

    # date object for comparison
    date_obj = datetime(
        int(year),
        int(month),
        int(day)
    ).date()

    # formatted output
    date_str = f"{int(day):02d}/{int(month):02d}/{year}"

    return date_obj, date_str


columns = [
    "Subject", "Type", "Category", "Media Source", "Country", "Date",
    "Links", "Publication", "Title", "Article Text", "Status"
]

# start_date = datetime.now().date()
# start_date = (datetime.now() - timedelta(days=1)).date()
# current_date = start_date
# # current_date = datetime.strptime("2025-08-06", "%Y-%m-%d").date()
# reset_limit = 30
# backtrack_days = 0
all_rows = []

run_id = f"kompas_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

print(f"🆔 MongoDB crawler run ID: {run_id}")
# while True:
yesterday = (datetime.now() - timedelta(days=1)).date()
day_before = (datetime.now() - timedelta(days=3)).date()
# day_before = datetime.strptime("1 January 2026", "%d %B %Y").date()
# yesterday   = datetime.strptime("7 May 2026", "%d %B %Y").date()
yesterday_str = yesterday.strftime("%d %B %Y")
day_before_str = day_before.strftime("%d %B %Y")
target_dates = {yesterday, day_before}
earliest_date = min(target_dates)  # the older one (day_before)
date_range = [day_before, yesterday]

master_file = os.path.join(excel_path, "Master_IDN_Times.xlsx")
temp_file   = excel_file = os.path.join(excel_path, f"{day_before_str}_{yesterday_str}_IDN_Times.xlsx")
print(temp_file)

# Load master + temp if exist
if os.path.exists(master_file):
    df_master = pd.read_excel(master_file)
    master_links = set(df_master["Links"].astype(str).str.strip())
else:
    df_master = pd.DataFrame(columns=columns)
    master_links = set()

if os.path.exists(temp_file):
    df_temp = pd.read_excel(temp_file)
    temp_links = set(df_temp["Links"].astype(str).str.strip())
else:
    df_temp = pd.DataFrame(columns=columns)
    temp_links = set()

# ✅ Search once for both yesterday & day_before
found_any = False
skip_to_next_keyword = False

for keyword in all_keywords:
    print(f"\n🔍 Searching keyword: '{keyword}' (Date range {day_before_str} → {yesterday_str})")

    search_url = f"https://www.idntimes.com/search?q={keyword}"
    driver.get(search_url)
    time.sleep(3)

    # ---- Sort by Newest ----
    # try:
    #     terbaru_btn = WebDriverWait(driver, 10).until(
    #         EC.element_to_be_clickable((By.CSS_SELECTOR, 'a[data-qa-id="newest-non-active"]'))
    #     )
    #     driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", terbaru_btn)
    #     driver.execute_script("arguments[0].click();", terbaru_btn)
    #     print("✅ Clicked Terbaru")
    # except TimeoutException:
    #     print("⚠️ No 'Terbaru' button; continuing with defaults")

    # ---- Collect all article cards ----
    processed_links = set()
    stop_pagination = False

    while not stop_pagination:

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "h3[data-testid='title-article']")
                )
            )
        except TimeoutException:
            print("⏹️ No article titles found on current page.")
            break

        # 1️⃣ Get all currently loaded article titles
        title_elements = driver.find_elements(
            By.CSS_SELECTOR, "h3[data-testid='title-article']"
        )

        print(f"📰 Articles currently loaded: {len(title_elements)}")

        if not title_elements:
            break

        new_article_found = False

        # 2️⃣ Process ONLY new articles
        for title_elem in title_elements:
            try:
                article = get_article_card_from_title(title_elem)

                title = title_elem.text.strip()
                print(f"➡️ Processing: {title}")

                link = ""
                try:
                    link_elem = title_elem.find_element(By.XPATH, "./ancestor::a[1]")
                    link = link_elem.get_attribute("href")
                except Exception:
                    try:
                        link = article.find_element(By.CSS_SELECTOR, "a").get_attribute("href")
                    except Exception as e:
                        print(f"❌ Link not found: {e}")
                        link = ""

                category_name = ""
                try:
                    category_path_elem = article.find_element(
                        By.XPATH,
                        ".//span[contains(@data-cy,'ds-card-article-category')]"
                    )
                    category_name = category_path_elem.text.strip()
                    print(f"Media Source: {category_name}")
                except Exception as e:
                    print(f"❌ Media Source not found: {e}")
                    category_name = ""

                normalized_category = category_name.strip().lower()
                if normalized_category not in {"news", "business"}:
                    print(f"⏭️ Skipping article because category '{category_name}' is not allowed.")
                    continue

                article_date, date_formatted = None, ""
                try:
                    date_elem = article.find_element(
                        By.XPATH,
                        ".//span[contains(@data-testid,'publish-date') or contains(@data-cy,'publish-date')]"
                    )
                    article_date, date_formatted = convert_indo_date(date_elem.text)
                    print(f"📅 {date_formatted}")
                except Exception as e:
                    print(f"No Date Found: {e}")
                    pass

            # ---------- STOP CONDITIONS ----------
                if article_date and article_date < earliest_date:
                    print("⏹️ Old article reached — stopping pagination.")
                    stop_pagination = True
                    break

                if article_date and not (day_before <= article_date <= yesterday):
                    print("⏩ Skipped (out of date range)")
                    continue

                if link in processed_links or link in master_links or link in temp_links:
                    print(f"⏭️ Skipping duplicate: {link}")
                    continue

                article_id = hashlib.sha256(
                    link.encode("utf-8")
                ).hexdigest()[:16]

                if raw_articles_collection.find_one(
                    {"article_id": article_id},
                    {"_id": 1}
                ):
                    print(f"⏭️ Already exists in MongoDB: {link}")
                    continue

                processed_links.add(link)
                new_article_found = True

                # ---------- OPEN ARTICLE ----------
                existing_tabs = set(driver.window_handles)
                driver.execute_script("window.open(arguments[0]);", link)

                WebDriverWait(driver, 10).until(
                    lambda d: len(d.window_handles) > len(existing_tabs)
                )

                new_tab = list(set(driver.window_handles) - existing_tabs)[0]
                driver.switch_to.window(new_tab)
                time.sleep(3)
                
            # ---------- EXTRACT CONTENT ----------
                article_text = ""
                try:
                    # Wait a bit if needed
                    article_main = driver.find_element(By.ID, "article-description")

                    # Get ALL paragraph-like text inside article body
                    paragraphs = article_main.find_elements(
                        By.XPATH,
                        ".//p[not(ancestor::div[contains(@class,'wrapper-ads')])]"
                    )

                    collected_text = []

                    for p in paragraphs:
                        text = p.text.strip()

                        # Skip empty / unwanted lines
                        if not text:
                            continue

                        lower_text = text.lower()

                        if (
                            lower_text.startswith("baca juga")
                            or lower_text.startswith("advertisement")
                            or lower_text.startswith("iklan")
                            or "scroll untuk melanjutkan" in lower_text
                            or "disclaimer:" in lower_text
                            or "artificial intelligence" in lower_text
                        ):
                            continue

                        # Avoid duplicates
                        if text not in collected_text:
                            collected_text.append(text)

                    article_text = "\n\n".join(collected_text)
                    article_country = detect_country_from_text(article_text,country_map)

                except Exception as e:
                    print(f"❌ Article content extraction failed: {e}")
                    article_text = ""
                    article_country = ""                

                # ---------- SAVE ----------
                print("💾 Saving article")
                row = {
                    "Subject": "",
                    "Type": "",
                    "Category": keyword,
                    "Media Source": category_name,
                    "Country": article_country,
                    "Date": date_formatted,
                    "Links": link,
                    "Publication": "IDN Times",
                    "Title": title,
                    "Article Text": article_text,
                    "Status": "1"
                }

                df_temp = pd.concat(
                    [df_temp, pd.DataFrame([row], columns=columns)],
                    ignore_index=True
                )
                temp_links.add(link)
                df_temp.to_excel(temp_file, index=False)

                driver.close()
                driver.switch_to.window(driver.window_handles[0])

            except Exception as e:
                print(f"❌ Article error: {e}")
                try:
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except:
                    driver = init_driver()
                continue

        # 3️⃣ Click LOAD MORE button
        try:
            load_more_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(., 'Load More')]")
                )
            )

            print("🔄 Clicking Load More...")

            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});",
                load_more_btn
            )

            time.sleep(1)

            driver.execute_script(
                "arguments[0].click();",
                load_more_btn
            )

            time.sleep(3)

        except Exception as e:
            print(f"⏹️ No more Load More button: {e}")
            break

# Reload master in case it changed
if os.path.exists(master_file):
    df_master = pd.read_excel(master_file)

df_master = pd.concat([df_master, df_temp], ignore_index=True)
df_master.drop_duplicates(subset=["Links"], keep="first", inplace=True)

df_master.to_excel(master_file, index=False)
driver.quit()
print(f"Transfer complete. {len(df_temp)} rows added to {master_file}")

# # ✅ Insert df_temp into PostgreSQL
# if not df_temp.empty:
#     insert_sql = """
#         INSERT INTO public.raw_input_table (
#             "pdf_uuid", "Date", "Category", "Media Source", "Country",
#             "Links", "Publication", "Title", "Article Text",
#             "Subject", "Status", "Type"
#         )
#         VALUES %s
#         ON CONFLICT DO NOTHING;
#     """
    
#     rows_to_insert = [
#         (
#             str(uuid.uuid4()),       # pdf_uuid
#             row["Date"],             # Date
#             row["Category"],         # Category
#             row["Media Source"],     # Media Source
#             row["Country"],          # Country
#             row["Links"],            # Links
#             row["Publication"],      # Publication
#             row["Title"],            # Title
#             row["Article Text"],     # Article Text
#             row["Subject"],          # Subject
#             row["Status"],           # Status
#             row["Type"]             # Type
#         )
#         for _, row in df_temp.iterrows()
#     ]

#     execute_values(cursor, insert_sql, rows_to_insert)
#     conn.commit()
#     print(f"✅ Inserted {len(rows_to_insert)} rows into PostgreSQL")
# else:
#     print("⚠️ No new rows to insert into PostgreSQL")

# # ✅ Close DB connection
# cursor.close()
# conn.close()

# print("✅ Scraping completed.")



