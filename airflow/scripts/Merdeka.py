from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from datetime import datetime
import google.generativeai as genai
from psycopg2.extras import execute_values
from datetime import datetime, timedelta
from urllib.parse import urlparse
from pathlib import Path
from fpdf import FPDF
import psycopg2, re, json, os, time, uuid, fitz, io
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import random
from PIL import Image
import hashlib
import re

class PDF(FPDF):
    def __init__(self, title, date_published, publication, url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title_text = title
        self.date_published = date_published
        self.publication = publication
        self.url = url
        self.add_font('Calibri', '', 'C:/Windows/Fonts/calibri.ttf', uni=True)
        self.add_font('Calibri', 'B', 'C:/Windows/Fonts/calibrib.ttf', uni=True)

    def header(self):
        self.image(r"C:\Users\Syasya\OneDrive - Verity Intelligence Sdn Bhd\Puteri - Intern\Adverse Media\halocheck_logo_original.png", self.w - 45, 1, 40)
        self.set_font('Calibri', '', 11)
        self.cell(0, 7, self.title_text, ln=True)
        self.cell(0, 7, self.publication, ln=True)
        self.cell(0, 7, f'Date Published: {self.date_published}', ln=True)

        max_characters_per_line = 100
        lines = self.url.split('\n')
        for line in lines:
            if len(line) > max_characters_per_line:
                parts = [line[i:i + max_characters_per_line] for i in range(0, len(line), max_characters_per_line)]
                for part in parts:
                    self.cell(0, 7, part, ln=True, link=self.url)
            else:
                self.cell(0, 7, line, ln=True, link=self.url)

    def footer(self):
        self.set_x(25)
        self.set_y(-30)
        self.set_font('Calibri', '', 8)
        footer_lines = [
            'Information on this site is not an exhaustive source of information on the individual/subject matter of the search.',
            'Any reports or articles contained herein are not reflective of any conclusive findings. Our database may not comprehensively',
            'reflect all or subsequent developments in any matter relating to the individual/subject searched for. You are strongly advised',
            'to conduct further inquiries for any information that post-dates the date on which the search result was last modified.'
        ]
        for line in footer_lines:
            self.cell(0, 5, line, ln=True, align='C')
        self.ln(5)
        self.cell(0, 0, 'www.halocheck.com.my', align='L')
        self.cell(0, 0, '  2024 HaloCheck. All rights reserved. Terms of Use | Privacy Policy', align='R')

    def add_screenshot(self, screenshot_path):
        self.add_page()
        self.image(screenshot_path, x=10, y=self.get_y(), w=190)

# Paths
category_path = r"/home/khaliq/airflow_project/airflow/dags/resources/categories.json"
keyword_path = r"/home/khaliq/airflow_project/airflow/dags/resources/keywords.json"
countries_path = r"/home/khaliq/airflow_project/airflow/dags/resources/countries.json"
excel_path = r"/home/khaliq/airflow_project/airflow/output/Merdeka"

# conn = psycopg2.connect(host="192.168.1.132", database="adverse_media", user="postgres", password="Verity@456")
# cursor = conn.cursor()

# os.makedirs(pdf_path, exist_ok=True)
os.makedirs(excel_path, exist_ok=True)
genai.configure(api_key=os.getenv("GEMINI_API_KEY_1"))
model = genai.GenerativeModel("gemini-2.5-flash")

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

# first init
driver = init_driver()
wait = WebDriverWait(driver, 10)

# Load keywords
with open(keyword_path, "r", encoding="utf-8") as f:
    data = json.load(f)

languages = data["language"][0]
indo_keywords = languages.get("Indo", {}).get("keywords", [])
# malay_keywords = languages.get("Malay", {}).get("keywords", [])
all_keywords = indo_keywords 


from datetime import datetime

def parse_indonesian_datetime(datetime_text: str):
    """
    Input:
    'Jumat, 15 Mei 2026 08:09:26'

    Returns:
    (
        datetime.date(2026, 5, 15),
        '2026-05-15'
    )
    """

    bulan_map = {
        "Jan": "January",
        "Feb": "February",
        "Mar": "March",
        "Apr": "April",
        "Mei": "May",
        "Jun": "June",
        "Jul": "July",
        "Agu": "August",
        "Sep": "September",
        "Okt": "October",
        "Nov": "November",
        "Des": "December"
    }

    try:
        # Remove weekday
        cleaned = datetime_text.split(", ", 1)[1]

        # Convert month names
        for indo, eng in bulan_map.items():
            cleaned = cleaned.replace(indo, eng)

        # Parse datetime
        dt = datetime.strptime(cleaned, "%d %B %Y %H:%M:%S")

        # Actual date object
        date_obj = dt.date()

        # String format for display/export
        formatted_str = dt.strftime("%Y-%m-%d")
        # OR:
        # formatted_str = dt.strftime("%d-%m-%Y")

        return date_obj, formatted_str

    except Exception as e:
        print(f"⚠️ Date parse error: {e}")
        return None, None
    



def extract_country(article_text: str) -> str:
    prompt = f"""
    Extract only the most relevant country mentioned or implied in the article below.

    Rules:
    - Return ONLY the country name
    - No explanation
    - No punctuation
    - If multiple countries exist, return the most relevant one
    - If none clearly mentioned, infer from context

    Article:
    {article_text}
    """

    response = model.generate_content(prompt)
    return response.text.strip()

def safe_close_and_return(driver, keyword, url):
    """Safely close current tab and return to main window, restarting driver if needed."""
    try:
        driver.close()
        if driver.window_handles:
            driver.switch_to.window(driver.window_handles[0])
        else:
            raise Exception("No window handles left")
    except Exception as e:
        print(f"⚠️ Lost browser window: {e}. Restarting driver...")
        try:
            driver.quit()
        except:
            pass
        driver = init_driver()

        # Relaunch search for current keyword
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div.search-icon-wrapper"))
        ).click()
        search_input = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.ID, "_3038406769_keywords"))
        )
        search_input.clear()
        search_input.send_keys(keyword)
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "_3038406769_search"))
        ).click()
        time.sleep(3)
    return driver

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

# while True:
yesterday = (datetime.now() - timedelta(days=1)).date()
day_before = (datetime.now() - timedelta(days=2)).date()
# day_before = datetime.strptime("1 January 1990", "%d %B %Y").date()
# yesterday   = datetime.strptime("16 December 2025", "%d %B %Y").date()
yesterday_str = yesterday.strftime("%d %B %Y")
day_before_str = day_before.strftime("%d %B %Y")
target_dates = {yesterday, day_before}
earliest_date = min(target_dates)  # the older one (day_before)
date_range = [day_before, yesterday]

master_file = os.path.join(excel_path, "Master_Merdeka.xlsx")
temp_file   = excel_file = os.path.join(excel_path, f"{day_before_str}_{yesterday_str}_Merdeka.xlsx")
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

import time
import pandas as pd
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException


# =========================
# MAIN SCRAPER
# =========================
for keyword in all_keywords:

    page_num = 1
    stop_pagination = False
    retries = 0

    search_url = f"https://www.merdeka.com/search?q={keyword}"

    print(f"\n🔍 Keyword: {keyword}")

    try:
        # =========================
        # LOAD ONLY ONCE (IMPORTANT FIX)
        # =========================
        driver.get(search_url)

    except Exception as e:
        print(f"❌ Failed to load keyword page: {e}")
        continue

    while not stop_pagination:

        print(f"\n📄 Processing Page {page_num}")

        try:
            # =========================
            # SORT BY DATE (optional but stable)
            # =========================
            try:
                sort_dropdown = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "div.gsc-selected-option-container"))
                )
                driver.execute_script("arguments[0].click();", sort_dropdown)

                date_option = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//div[contains(@class,'gsc-option') and normalize-space()='Date']")
                    )
                )
                driver.execute_script("arguments[0].click();", date_option)

                time.sleep(2)

            except Exception:
                pass

            # =========================
            # WAIT RESULTS
            # =========================
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "div.gsc-webResult.gsc-result")
                )
            )

            results = driver.find_elements(By.CSS_SELECTOR, "div.gsc-webResult.gsc-result")

            article_data = []
            found_any_valid = False

            # =========================
            # EXTRACT LINKS FIRST (CRITICAL FIX)
            # =========================
            for r in results:
                try:
                    links = r.find_elements(By.CSS_SELECTOR, "a.gs-title")
                    if not links:
                        continue

                    a = links[0]
                    title = a.text.strip()
                    link = a.get_attribute("href")

                    if not title or not link:
                        continue

                    found_any_valid = True
                    article_data.append((title, link))

                except StaleElementReferenceException:
                    continue
                except Exception:
                    continue

            if not found_any_valid:
                print("🚫 No valid articles — stopping keyword")
                break

            # =========================
            # PROCESS ARTICLES
            # =========================
            for title, link in article_data:

                if link in master_links or link in temp_links:
                    continue

                try:
                    driver.execute_script("window.open(arguments[0]);", link)
                    driver.switch_to.window(driver.window_handles[-1])

                    # =========================
                    # ARTICLE PAGE WAIT
                    # =========================
                    article_div = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.article"))
                    )

                    # =========================
                    # DATE PARSING
                    # =========================
                    formatted_date = ""
                    date_obj = None

                    try:
                        time_text = article_div.find_element(By.TAG_NAME, "time").text.strip()
                        date_obj, formatted_date = parse_indonesian_datetime(time_text)
                    except:
                        pass

                    # =========================
                    # STOP CONDITION (OLDER DATA)
                    # =========================
                    if date_obj and date_obj < earliest_date:
                        print("⏹️ Reached old articles — stopping pagination")
                        stop_pagination = True
                        if len(driver.window_handles) > 1:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                        else:
                            print("⚠️ Last window detected — not closing")
                        break

                    if date_obj and not (day_before <= date_obj <= yesterday):
                        if len(driver.window_handles) > 1:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                        else:
                            print("⚠️ Last window detected — not closing")
                        continue

                    # =========================
                    # CATEGORY
                    # =========================
                    try:
                        items = article_div.find_elements(
                            By.CSS_SELECTOR,
                            "ol.breadcrumb li.breadcrumb-item"
                        )

                        crumbs = [
                            item.text.strip()
                            for item in items
                            if item.text.strip()
                        ]

                        category = crumbs[-1] if crumbs else ""

                    except Exception:
                        category = ""

                    # =========================
                    # ARTICLE TEXT
                    # =========================
                    paragraphs = article_div.find_elements(By.TAG_NAME, "p")

                    article_text = "\n".join(
                        p.text.strip() for p in paragraphs if p.text.strip()
                    )
                    country = extract_country(article_text)

                    # =========================
                    # SAVE ROW
                    # =========================
                    row = {
                        "Subject": "",
                        "Type": "",
                        "Category": keyword,
                        "Media Source": category,
                        "Country": country,
                        "Date": formatted_date,
                        "Links": link,
                        "Publication": "Merdeka",
                        "Title": title,
                        "Article Text": article_text,
                        "Status": "1"
                    }

                    df_temp = pd.concat(
                        [df_temp, pd.DataFrame([row])],
                        ignore_index=True
                    )

                    temp_links.add(link)
                    df_temp.to_excel(temp_file, index=False)

                    print("💾 Saved:", title)

                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

                except Exception as e:
                    print(f"❌ Article error: {e}")

                    try:
                        if len(driver.window_handles) > 1:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                        else:
                            print("⚠️ Only one window left — skipping close to avoid killing session")
                            driver.get(search_url)
                    except:
                        print(f"⚠️ Recovery failed")
                        driver.get(search_url)

            # =========================
            # PAGINATION (FIXED - NO URL RESET)
            # =========================
            if stop_pagination:
                break

            try:
                page_buttons = driver.find_elements(By.CSS_SELECTOR, "div.gsc-cursor-page")

                next_page = None

                for btn in page_buttons:
                    if btn.text.strip() == str(page_num + 1):
                        next_page = btn
                        break

                if next_page:
                    driver.execute_script("arguments[0].click();", next_page)
                    page_num += 1
                    print(f"➡️ Moving to page {page_num}")
                    time.sleep(3)
                else:
                    print("✅ No more pages")
                    break

            except Exception as e:
                print(f"❌ Pagination error: {e}")
                break

        except Exception as e:
            print(f"❌ Page error: {e}")
            retries += 1

            if retries >= 2:
                break

            time.sleep(5)

print("✅ SCRAPING COMPLETE")


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



