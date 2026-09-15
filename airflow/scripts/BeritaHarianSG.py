import os
import time
import pandas as pd
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
import psycopg2
from psycopg2.extras import execute_values
from webdriver_manager.chrome import ChromeDriverManager
from pathlib import Path

# ---------- CONFIGURATION ----------
url_array = [
    ("https://www.beritaharian.sg/singapura/politik", "Politik"),
    ("https://www.beritaharian.sg/singapura/jenayah-mahkamah", "Jenayah & Mahkamah"),
]

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "output"
excel_path = str(Path(os.getenv("OUTPUT_PATH", OUTPUT_DIR / "Berita Harian Singapore")))

# conn = psycopg2.connect(host="192.168.1.132", database="adverse_media", user="postgres", password="Verity@456")
# cursor = conn.cursor()

# Date range: from 9 days ago up to yesterday
yesterday = (datetime.now() - timedelta(days=1)).date()
day_before = (datetime.now() - timedelta(days=10)).date()
yesterday_str = yesterday.strftime("%d %B %Y")
day_before_str = day_before.strftime("%d %B %Y")

master_file = os.path.join(excel_path, "Master_BeritaHarian_SG.xlsx")
temp_file = os.path.join(excel_path, f"{day_before_str}_{yesterday_str}_BeritaHarian_SG.xlsx")

# ---------- KEYWORDS ----------
KEYWORDS = [
    "Akta Hidupan Liar", "Akta Pekerjaan", "Aktiviti Penyeludupan Haram",
    "Aktiviti Wang Haram", "Bersalah", "Dadah", "Dakwa", "Dibebaskan", "Didakwa",
    "Didenda", "Disaman", "Ditahan Reman", "Dituduh", "Gangguan", "Gangguan Seksual",
    "Hasutan", "Jenayah", "Jenayah Seksual", "Judi", "Kanun Keseksaan", "Kecurian",
    "Kesalahan Berkaitan Keganasan", "Kesalahan Imigresen", "Kesalahan Trafik",
    "Melakukan Kerosakan", "Menculik", "Menyebabkan Kecederaan", "Orang Dikehendaki",
    "Palsu", "Pecah Amanah", "Pelaburan Wang Haram", "Pelanggaran", "Pembunuhan",
    "Bahan Terlarang", "Pencemaran", "Pencerobohan", "Penderaan", "Penipuan",
    "Penjara", "Pergaduhan", "Kekerasan", "Melanggar Peraturan", "Ragut", "Rasuah",
    "Reman", "Rogol", "Rompak", "Saman"
]

columns = ["Subject", "Type", "Media Source", "Country", "Date", "Links",
            "Publication", "Keyword", "Title", "Article Text", "Status"]

# ---------- LOAD EXISTING FILES ----------
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

# ---------- SAVE FUNCTION ----------
def append_to_excel(file_path, data_dict):
    """Append a single row to Excel immediately."""
    df = pd.DataFrame([data_dict])
    if not os.path.exists(file_path):
        df.to_excel(file_path, index=False)
    else:
        existing = pd.read_excel(file_path)
        combined = pd.concat([existing, df], ignore_index=True)
        combined.to_excel(file_path, index=False)

# ---------- SELENIUM SETUP ----------
options = Options()
options = Options()
options.add_argument("--start-maximized")
options.add_argument("--disable-notifications")
options.binary_location = "/usr/bin/google-chrome"
driver = webdriver.Chrome(
        service=Service("/usr/local/bin/chromedriver"),
        options=options
    )
# ---------- SCRAPING LOOP ----------
for url, media_source in url_array:
    print(f"\n📰 Starting scrape for: {media_source} ({url})")
    driver.get(url)
    time.sleep(3)
    last_height = driver.execute_script("return document.body.scrollHeight")

    while True:
        articles = driver.find_elements(By.CSS_SELECTOR, "[data-testid^='article']")
        print(f"Found {len(articles)} articles on current page...")

        stop_scraping = False

        for a in articles:
            try:
                # ----- Extract title -----
                try:
                    title = a.find_element(By.TAG_NAME, "h2").text.strip()
                except:
                    title = None

                # ----- Extract date -----
                try:
                    date_text = a.find_element(By.CSS_SELECTOR, "span[data-testid='date']").text.strip()
                    date_str = date_text.split("|")[0].strip()
                    date_obj = datetime.strptime(date_str, "%b %d, %Y").date()
                except:
                    date_text, date_obj = None, None

                # ----- Extract link -----
                try:
                    link = a.find_element(By.CSS_SELECTOR, "a[data-testid='link']").get_attribute("href")
                    if link and link.startswith("/"):
                        link = "https://www.beritaharian.sg" + link
                except:
                    link = None

                if not link or not title:
                    continue

                # ----- Date Checks -----
                if date_obj is None:
                    print(f"⚠️ Skipping '{title}' — no valid date found.")
                    continue
                if date_obj > yesterday:
                    print(f"⏭️ Skipping '{title}' — newer than yesterday.")
                    continue
                if date_obj < day_before:
                    print(f"🛑 Older than {day_before}, stopping scrape.")
                    stop_scraping = True
                    break

                # ----- Duplicate Check -----
                if link in master_links or link in temp_links:
                    print(f"⏭️ Skipping duplicate: {link}")
                    continue

                # ----- Open Article Page -----
                driver.execute_script("window.open(arguments[0]);", link)
                driver.switch_to.window(driver.window_handles[1])
                time.sleep(2)

                try:
                    article_text = driver.find_element(By.CSS_SELECTOR, "div[data-testid='article-body']").text.strip()
                except:
                    article_text = ""

                driver.close()
                driver.switch_to.window(driver.window_handles[0])

                # ----- Keyword Check -----
                found_keyword = next((kw for kw in KEYWORDS if kw.lower() in article_text.lower()), None)

                if found_keyword:
                    print(f"✅ '{found_keyword}' found — saving '{title}'")
                    article_data = {
                        "Subject": "",
                        "Type": "",
                        "Media Source": media_source,
                        "Country": "Singapore",
                        "Date": date_obj.strftime("%d %b %Y"),
                        "Links": link,
                        "Publication": "Berita Harian Singapore",
                        "Keyword": found_keyword,
                        "Title": title,
                        "Article Text": article_text,
                        "Status": 1
                    }
                    append_to_excel(temp_file, article_data)
                    temp_links.add(link)
                else:
                    print(f"⏭️ Skipped (no keyword found): {title}")

            except Exception as e:
                print(f"⚠️ Error processing article: {e}")
                continue

        if stop_scraping:
            print(f"🛑 Completed scraping for {media_source} — reached date limit.\n")
            break

        # ----- Scroll Down -----
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
        time.sleep(3)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            print("⚙️ No more new articles to load, moving to next section...")
            break
        last_height = new_height

driver.quit()
print("✅ Scraping completed, now merging temp into master...")

# ---------- MERGE TEMP → MASTER ----------
if os.path.exists(temp_file):
    df_temp = pd.read_excel(temp_file)
    combined = pd.concat([df_master, df_temp], ignore_index=True)
    combined.drop_duplicates(subset=["Links"], inplace=True)
    combined.to_excel(master_file, index=False)
    print(f"📘 Master file updated successfully: {master_file}")
else:
    print("⚠️ No temp file found — nothing to merge.")


#if not df_temp.empty:
#    insert_sql = """
#        INSERT INTO public.raw_input_table (
#            "pdf_uuid", "Date", "Category", "Media Source", "Country",
#            "Links", "Publication", "Title", "Article Text",
#            "Subject", "Status", "Type"
#        )
#        VALUES %s
#        ON CONFLICT DO NOTHING;
#    """
    
#    rows_to_insert = [
#        (
#            str(uuid.uuid4()),       # pdf_uuid
#            row["Date"],             # Date
#            row["Category"],         # Category
#            row["Media Source"],     # Media Source
#            row["Country"],          # Country
#            row["Links"],            # Links
#            row["Publication"],      # Publication
#            row["Title"],            # Title
#            row["Article Text"],     # Article Text
#            row["Subject"],          # Subject
#            row["Status"],           # Status
#            row["Type"]             # Type
#        )
#        for _, row in df_temp.iterrows()
#    ]

#    execute_values(cursor, insert_sql, rows_to_insert)
#    conn.commit()
#    print(f"✅ Inserted {len(rows_to_insert)} rows into PostgreSQL")
#else:
#    print("⚠️ No new rows to insert into PostgreSQL")

# ✅ Close DB connection
#cursor.close()
#conn.close()

print("✅ Scraping completed.")


