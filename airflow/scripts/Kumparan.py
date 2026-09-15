from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from datetime import datetime
from psycopg2.extras import execute_values
from datetime import datetime, timedelta
from urllib.parse import urlparse
from pathlib import Path
from fpdf import FPDF
from openai import OpenAI
import psycopg2, re, json, os, time, uuid, fitz, io, traceback, requests
from webdriver_manager.chrome import ChromeDriverManager
from datetime import date as dt_date
import pandas as pd
import random
from PIL import Image
import hashlib
import re
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from gridfs import GridFS

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
BASE_DIR = Path(__file__).resolve().parents[1]
RESOURCES_DIR = BASE_DIR / "dags" / "resources"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
OUTPUT_DIR = BASE_DIR / "output"

pdf_path = str(Path(os.getenv("PDF_PATH", SCREENSHOTS_DIR / "Kumparan")))
category_path = str(Path(os.getenv("CATEGORY_PATH", RESOURCES_DIR / "categories.json")))
keyword_path = str(Path(os.getenv("KEYWORD_PATH", RESOURCES_DIR / "keywords.json")))
countries_path = str(Path(os.getenv("COUNTRIES_PATH", RESOURCES_DIR / "countries.json")))
excel_path = str(Path(os.getenv("OUTPUT_PATH", OUTPUT_DIR / "Kumparan")))
DEEPEEK_API_KEY = "sk-bea43c4bb41040b9b4437007a82bf0b1"

# conn = psycopg2.connect(host="localhost", database="adverse_media", user="postgres", password="Verity@456")
# cursor = conn.cursor()

os.makedirs(pdf_path, exist_ok=True)
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

# first init
driver = init_driver()

# =========================
# MONGODB CONFIG
# =========================

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

import re

def detect_country_from_text(article_text, country_map):
    if not article_text:
        return ""

    text = article_text.strip()
    location = ""

    # 1️⃣ Kompas style
    match_kompas = re.match(
        r'^([A-Z\s]+),\s*KOMPAS\.com\s+[-—]',
        text
    )
    if match_kompas:
        location = match_kompas.group(1)

    # 2️⃣ ANTARA style
    else:
        match_antara = re.match(
            r'^(.+?)\s*\(ANTARA\)',
            text
        )
        if match_antara:
            location = match_antara.group(1)

    if not location:
        return ""

    # Normalize location
    location = location.upper().strip()

    # Split city / region
    if "," in location:
        city, region = [x.strip() for x in location.split(",", 1)]
    else:
        city = location
        region = ""

    # 3️⃣ Compare with country map (also normalized)
    for country, regions in country_map.items():
        regions_upper = [r.upper() for r in regions]

        if city in regions_upper or region in regions_upper:
            return country

    # 4️⃣ Fallback
    return ""


def infer_country_with_deepseek(article_text):
    if not article_text:
        return ""
    api_key = DEEPEEK_API_KEY
    if not api_key:
        return ""

    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    prompt = f"""
Extract the country name from the text below.
Return ONLY the country name as plain text. The country name MUST BE with english spelling. Do NOT return any explanation, reasoning, labels, or extra text.
If no country can be confidently determined, return an empty string.

Validation rules:
1. If the article text talks about a criminal case or case involving conviction, assign the country based on where the case/conviction took place and not where the person is from.
2. If the article text talks about an occurrence or event, state the country where the occurrence/event took place and not where the person is from.

Text:
{article_text}
"""

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
    except Exception as e:
        print(f"⚠️ Deepseek request failed: {e}")
        return ""

    try:
        data = resp.json()
    except Exception:
        print(f"⚠️ Deepseek returned non-JSON (status {resp.status_code})")
        return ""

    if resp.status_code != 200:
        # Prefer human-readable error
        err = data.get("error") if isinstance(data, dict) else data
        print(f"⚠️ Deepseek API error {resp.status_code}: {err}")
        return ""

    if "choices" not in data or not data["choices"]:
        print(f"⚠️ Deepseek API returned unexpected response: {data}")
        return ""

    try:
        country = data["choices"][0]["message"]["content"].strip()
        if not country:
            return ""
        return country.splitlines()[0].strip()
    except Exception as e:
        print(f"⚠️ Failed to parse Deepseek response: {e}")
        return ""

import re
from datetime import datetime

def convert_indo_date(date_text):
    month_map = {
        "Januari": "01",
        "Februari": "02",
        "Maret": "03",
        "April": "04",
        "Mei": "05",
        "Juni": "06",
        "Juli": "07",
        "Agustus": "08",
        "September": "09",
        "Oktober": "10",
        "November": "11",
        "Desember": "12"
    }

    match = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', date_text)
    if not match:
        return None, ""

    day, month_name, year = match.groups()
    month = month_map.get(month_name)

    # ✅ date object for comparisons
    date_obj = datetime(
        int(year),
        int(month),
        int(day)
    ).date()

    # ✅ formatted string for output
    date_str = f"{int(day)}/{int(month)}/{year}"

    return date_obj, date_str

def compress_screenshot_pdf(input_path, output_path, quality=35, max_width=1000):
    """
    Compress PDF containing screenshots.
    
    Args:
        input_path (str): Path to input PDF file.
        output_path (str): Path to save compressed PDF file.
        quality (int): JPEG compression quality (1-100).
        max_width (int): Maximum width in pixels (maintains aspect ratio).
    """
    if not os.path.exists(input_path):
        print(f"❌ File not found: {input_path}")
        return False

    print(f"📦 Compressing PDF: {input_path}")

    doc = fitz.open(input_path)
    new_doc = fitz.open()

    for page_num in range(len(doc)):
        print(f"🧩 Processing page {page_num + 1}/{len(doc)}")
        page = doc[page_num]
        mat = fitz.Matrix(1.5, 1.5)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data)).convert("RGB")

        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            print(f"📐 Resized to {max_width}x{new_height}")

        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        compressed_data = buffer.getvalue()

        new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(page.rect, stream=compressed_data)

    new_doc.save(output_path)
    new_doc.close()
    doc.close()

    original_size = os.path.getsize(input_path)
    new_size = os.path.getsize(output_path)
    savings = (original_size - new_size) / original_size * 100

    print(f"✅ Compression complete:")
    print(f"   Original: {original_size/1024/1024:.2f} MB")
    print(f"   Compressed: {new_size/1024/1024:.2f} MB")
    print(f"   Saved: {savings:.1f}%")

    return True

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


def scroll_and_capture(driver, pdf_id, save_path, title, date, publication, url):
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    scroll_pause = 1.5
    screenshots = []
    index = 0
    max_scrolls = 30

    # Step 1: Remove minimal ads ONLY (keep header for first screenshot)
    driver.execute_script("""
        const initialSelectors = [
            '#tbl-next-up',
            '#innity-apps-ad',
            '.google-auto-placed',
            'iframe[src*="doubleclick"]',
            '.trc_related_container',
            'div[id*="ats-overlay_bottom"]',
            '#cto_banner_content',
            'amp-img.img_ad',
            'amp-img[src*="googlesyndication"]',
            '.mgbox',
            '.ats-overlay-bottom-wrapper-rendered',
            '#google-anno-sa',
            'div[id^="innity_adslot_"]',
            'div[id^="innity_content_"]',
            'div[id^="innity_overlay_"]',
            'a[id^="innity_overlay_click_"]',
            'div[id^="innity_topbar_"]',
            'a[id^="btn_close_"]',
            'style[id^="innity_css_"]',
            'script[id^="innity_research_tag_"]',
            'iframe[id^="innity_iframe_"]',
            'iframe[id^="innity_research_tag_"]',
            'div[id="innity_research_tag_362347"]'
        ];
        initialSelectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(el => el.remove());
        });
    """)

    # Step 2: Ensure header + title are visible before first screenshot
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)

    try:
        section_el = driver.find_element(By.CSS_SELECTOR, 'span[itemprop="name"]')

        # Get header height
        header_height = driver.execute_script("""
            const header = document.querySelector('header');
            return header ? header.offsetHeight : 80;
        """)

        # Scroll the section into view, then adjust by header height
        driver.execute_script("""
            arguments[0].scrollIntoView({ block: 'start' });
            window.scrollBy(0, -arguments[1]);
        """, section_el, header_height)
        time.sleep(0.6)

    except Exception as e:
        print("⚠️ Could not locate section label to scroll into view. Proceeding.")

    # Now capture the first screenshot
    screenshot_path = os.path.join(pdf_path, f"{pdf_id}_{index}.png")
    driver.save_screenshot(screenshot_path)
    screenshots.append(screenshot_path)
    index += 1
        
    # Step 2.5: Scroll exactly by window height to avoid overlap or cut-off
    window_height = driver.execute_script("return window.innerHeight")
    driver.execute_script(f"window.scrollBy(0, {window_height});")
    time.sleep(scroll_pause)

    # Step 3: Now remove header and aggressive ad elements
    driver.execute_script("""
        const laterSelectors = [
            '#col-60-40',
            'div[id*="ad"]',
            'div[class*="ad"]',
            '.floating-ads',
            'script[src*="adsbygoogle"]',
            '#ats-overlay_bottom-6',
            '#cto_banner_content',
            '.mgbox',
            '.ats-overlay-bottom-wrapper-rendered',
            '#google-anno-sa',
            'div[id^="innity_adslot_"]',
            'div[id^="innity_content_"]',
            'div[id^="innity_overlay_"]',
            'a[id^="innity_overlay_click_"]',
            'div[id^="innity_topbar_"]',
            'a[id^="btn_close_"]',
            'style[id^="innity_css_"]',
            'script[id^="innity_research_tag_"]',
            'iframe[id^="innity_iframe_"]',
            'iframe[id^="innity_research_tag_"]',
            'div[id="innity_research_tag_362347"]'
        ];
        laterSelectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(el => el.remove());
        });
    """)

    # Keep track of image hashes to avoid duplicates
    image_hashes = set()

    for _ in range(max_scrolls - 1):
        stop_now = False

        # === Stop condition checks ===
        try:
            recommended = driver.find_element(By.XPATH, '//a[text()="Recommended stories"]')
            is_in_view = driver.execute_script("""
                const el = arguments[0];
                const rect = el.getBoundingClientRect();
                return rect.top >= 0 && rect.bottom <= window.innerHeight;
            """, recommended)
            if is_in_view:
                print("✅ 'Recommended stories' reached.")
                stop_now = True
        except:
            pass

        try:
            you_may_like = driver.find_element(By.XPATH, '//span[@role="heading" and contains(text(), "You May Like")]')
            like_in_view = driver.execute_script("""
                const el = arguments[0];
                const rect = el.getBoundingClientRect();
                return rect.top >= 0 && rect.bottom <= window.innerHeight;
            """, you_may_like)
            if like_in_view:
                print("✅ 'You May Like' section reached.")
                stop_now = True
        except:
            pass

        try:
            total_scroll_height = driver.execute_script("return document.body.scrollHeight;")
            viewport_bottom = driver.execute_script("return window.scrollY + window.innerHeight;")

            if viewport_bottom >= total_scroll_height:
                print("Reached end of page, stopping scroll.")
                stop_now = True
        except Exception as e:
            print(f"⚠️ Scroll position check failed: {e}")

        if stop_now:
            break

        # === Screenshot and check for duplicates ===
        screenshot_path = os.path.join(pdf_path, f"{pdf_id}_{index}.png")
        driver.save_screenshot(screenshot_path)

        # Compute hash
        with Image.open(screenshot_path) as img:
            image_bytes = img.tobytes()
            image_hash = hashlib.md5(image_bytes).hexdigest()

        if image_hash in image_hashes:
            print("⚠️ Duplicate screenshot detected. Skipping.")
            os.remove(screenshot_path)  # Remove duplicate file
        else:
            image_hashes.add(image_hash)
            screenshots.append(screenshot_path)
            index += 1

        # Scroll down
        scroll_height = driver.execute_script("return window.innerHeight;")
        driver.execute_script(f"window.scrollBy(0, {scroll_height});")
        time.sleep(scroll_pause)

    # === Stitch screenshots vertically ===
    images = [Image.open(p) for p in screenshots]
    total_height = sum(img.height for img in images)
    stitched_width = max(img.width for img in images)

    stitched = Image.new("RGB", (stitched_width, total_height))
    y_offset = 0
    for img in images:
        stitched.paste(img, (0, y_offset))
        y_offset += img.height
        img.close()
    for img_path in screenshots:
        os.remove(img_path)

    stitched_path = os.path.join(pdf_path, f"{pdf_id}_stitched.png")
    stitched.save(stitched_path)

    # === PDF dimensions: A4 landscape ===
    a4_width_mm = 210
    a4_height_mm = 297
    margin = 10  # millimeter margin
    content_height_mm = a4_height_mm - 2 * margin - 20  # 10mm margin top/bottom + ~20mm for header/footer

    # === Divide image into 2 screenshots per page ===
    screenshot_height = images[0].height
    slice_height = screenshot_height * 2
    num_slices = (stitched.height + slice_height - 1) // slice_height

    pdf = PDF(title, date, publication, url, orientation='P', unit='mm', format='A4')

    for i in range(num_slices):
        upper = i * slice_height
        lower = min((i + 1) * slice_height, stitched.height)
        part = stitched.crop((0, upper, stitched_width, lower))
        part_aspect = part.width / part.height

        fixed_part_width = a4_width_mm - margin * 2
        part_height = fixed_part_width / part_aspect
        if part_height > content_height_mm:
            part_height = content_height_mm
        x_centered = (a4_width_mm - fixed_part_width) / 2
        y = margin + 30  # top margin + space for header

        temp_part_path = stitched_path.replace(".png", f"_{uuid.uuid4().hex}.png")
        part.save(temp_part_path) 

        pdf.add_page()
        pdf.image(temp_part_path, x=x_centered, y=y, w=fixed_part_width, h=part_height)
        os.remove(temp_part_path)

    pdf.output(save_path)
    os.remove(stitched_path)
    print(f"📄 PDF saved with {num_slices} page(s): {save_path}")

    # ➕ Compress PDF and overwrite original
    compressed_temp = save_path.replace(".pdf", "_compressed_temp.pdf")
    if compress_screenshot_pdf(save_path, compressed_temp, quality=35, max_width=1000):
        os.replace(compressed_temp, save_path)
        print(f"✅ Replaced with compressed PDF: {save_path}")
    else:
        print("⚠️ Compression failed. Original PDF kept.")

    return True

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
# yesterday   = datetime.strptime("4 February 2026", "%d %B %Y").date()
yesterday_str = yesterday.strftime("%d %B %Y")
day_before_str = day_before.strftime("%d %B %Y")
target_dates = {yesterday, day_before}
earliest_date = min(target_dates)  # the older one (day_before)
date_range = [day_before, yesterday]

master_file = os.path.join(excel_path, "Master_Kumparan.xlsx")
temp_file   = excel_file = os.path.join(excel_path, f"{day_before_str}_{yesterday_str}_Kumparan.xlsx")
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

    search_url = f"https://kumparan.com/search/{keyword}"
    driver.get(search_url)

    # ---- Sort by Newest ----
    try:
        terbaru_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'a[data-qa-id="newest-non-active"]'))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", terbaru_btn)
        driver.execute_script("arguments[0].click();", terbaru_btn)
        print("✅ Clicked Terbaru")
    except TimeoutException:
        print("⚠️ No 'Terbaru' button; continuing with defaults")

    # ---- Collect all article cards ----
    processed_links = set()
    stop_pagination = False

    while not stop_pagination:

        # 1️⃣ Get all currently loaded articles
        articles = driver.find_elements(
            By.CSS_SELECTOR, 'div[data-qa-id="story-result-card"]'
        )

        print(f"📰 Articles currently loaded: {len(articles)}")

        new_article_found = False

        # 2️⃣ Process ONLY new articles
        for article in articles:
            try:
                link = None
                try:
                    link_elem = article.find_element(
                        By.CSS_SELECTOR,
                        'a[aria-label="news-card-label-link"]'
                    )
                except NoSuchElementException:
                    print("⚠️ Fallback: anchor with aria-label not found, trying any article link")
                    link_elem = article.find_element(By.CSS_SELECTOR, 'a[href]')

                link = link_elem.get_attribute("href")
                if not link:
                    print("⚠️ Skipping article: empty href")
                    continue

                title = ""
                try:
                    title = article.find_element(
                        By.CSS_SELECTOR,
                        'span[data-qa-id="title"]'
                    ).text.strip()
                except NoSuchElementException:
                    title_elem = article.find_element(By.CSS_SELECTOR, 'h3, h2, span')
                    title = title_elem.text.strip()

                print(f"➡️ Processing: {title}")

                if link in processed_links:
                    print(f"⏭️ Skipping duplicate article on page: {link}")
                    continue

                if link in master_links or link in temp_links:
                    print(f"⏭️ Skipping duplicate in master/temp: {link}")
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

                category_name = ""
                try:
                    category_path_elem = article.find_element(By.CSS_SELECTOR, 'span[data-qa-id="author-name"]')
                    category_name = category_path_elem.text.strip()
                    print(f"Media Source: {category_name}")
                except Exception as e:
                    print(f"❌ Media Source not found: {e}")
                    pass
                
                normalized_category = category_name.strip().lower()
                if normalized_category not in {"kumparannews",'kumparanbisnis', 'kumparanhits', 'bbc news indonesia', 'pandangan jogja', 'kumparantech', 'kabar harian'}:
                    print(f"⏭️ Skipping article because category '{category_name}' is not allowed.")
                    continue

                # ---------- OPEN ARTICLE ----------
                existing_tabs = set(driver.window_handles)
                driver.execute_script("window.open(arguments[0]);", link)

                WebDriverWait(driver, 10).until(
                    lambda d: len(d.window_handles) > len(existing_tabs)
                )
                driver.switch_to.window(driver.window_handles[-1])
                time.sleep(3)
                html_content = driver.page_source
                print(f"🔎 Opened article tab: {driver.current_url}")
                

                # ---------- DATE ----------
                article_date, date_formatted = None, ""
                try:
                    print("🔎 Looking for publish date")
                    date_elem = driver.find_element(
                        By.CSS_SELECTOR, 'time[data-qa-id="publish-date"]'
                    )
                    article_date, date_formatted = convert_indo_date(date_elem.text)
                    print(f"📅 {date_formatted}")
                except Exception as e:
                    print(f"⚠️ No Date Found: {e}")
                    pass

            # ---------- STOP CONDITIONS ----------
                if article_date and article_date < day_before:
                    print("⏹️ Old article reached — stopping pagination.")
                    stop_pagination = True
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                    break

                if article_date and not (day_before <= article_date <= yesterday):
                    print("⏩ Skipped (out of date range)")
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                    continue
                
                # if link in processed_links or link in master_links or link in temp_links:
                #     print(f"⏭️ Skipping duplicate: {link}")
                #     driver.close()
                #     driver.switch_to.window(driver.window_handles[0])
                #     continue

                print("Date OK")
            # ---------- EXTRACT CONTENT ----------
                print("Extracting article content...")
                try:
                    article_text = ""
                    print("🔎 Looking for article body")
                    article_main = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "main[data-qa-id='article-main']"))
                    )

                    # wait until at least one paragraph exists beneath the article body
                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "main[data-qa-id='article-main'] p[data-qa-id='story-paragraph'], main[data-qa-id='article-main'] p"))
                    )

                    paragraphs = article_main.find_elements(
                        By.CSS_SELECTOR,
                        "p[data-qa-id='story-paragraph'], p"
                    )

                    print(f"📄 Found {len(paragraphs)} paragraph elements in article body")
                    article_text = "\n\n".join(
                        p.text.strip()
                        for p in paragraphs
                        if p.text.strip()
                    )

                    if not article_text:
                        print("⚠️ No text found in article body, falling back to page paragraphs")
                        all_paragraphs = driver.find_elements(By.CSS_SELECTOR, "p")
                        article_text = "\n\n".join(
                            p.text.strip()
                            for p in all_paragraphs
                            if p.text.strip() and len(p.text.strip()) > 20
                        )
                        print(f"📄 Fallback found {len(all_paragraphs)} paragraphs, extracted {len(article_text.splitlines())} lines")

                    html_file_id = grid_fs.put(
                        html_content.encode("utf-8"),
                        filename=f"{article_id}.html",
                        contentType="text/html",
                        article_id=article_id,
                        source="Kompas Indonesia",
                        article_url=link
                    )

                    print(f"💾 HTML saved to GridFS: {article_id}.html")

                except Exception as e:
                    print(f"❌ Article content extraction failed: {e}")
                    print(f"   URL: {driver.current_url}")
                    try:
                        print(f"   Title: {driver.title}")
                    except:
                        pass
                    try:
                        article_source = driver.page_source[:500]
                        print(f"   Page source start: {article_source}")
                    except:
                        pass
                    traceback.print_exc()
                    article_text = ""

                # ---------- SAVE ----------
                try:
                    country = infer_country_with_deepseek(article_text) or detect_country_from_text(article_text, country_map)
                    print(f"🌏 Country detected: {country}")
                    print("💾 Saving article")
                except Exception as e:
                    print(f"❌ Country detection failed: {e}")
                    country = "Unknown"
                
                # =========================
                # SAVE RAW METADATA TO MONGODB
                # =========================

                mongo_document = {
                    "article_id": article_id,

                    "source": {
                        "publication": "Kompas Indonesia",
                        "source_type": "adverse_media"
                    },

                    "url": link,

                    "crawled_at": datetime.now(),

                    "crawl": {
                        "crawler": "kumparan_scraper",
                        "run_id": run_id,
                        "keyword": keyword
                    },

                    "raw": {
                        "title": title,
                        "date": date_formatted,
                        "category": category,
                        "article_text": article_text
                    },

                    "html": {
                        "file_id": html_file_id,
                        "filename": f"{article_id}.html"
                    },

                    "processing": {
                        "status": "pending",
                        "processed_at": None,
                        "error": None
                    }
                }

                try:
                    raw_articles_collection.insert_one(mongo_document)

                    print(f"✅ Raw article saved to MongoDB: {article_id}")

                except DuplicateKeyError:
                    print(f"⏭️ Article already exists in MongoDB: {link}")

                    # Remove GridFS file so we don't leave an orphan
                    grid_fs.delete(html_file_id)

                except Exception as e:
                    print(f"❌ MongoDB insertion failed: {e}")

                    # Remove GridFS file if metadata insertion fails
                    grid_fs.delete(html_file_id)

                row = {
                    "Subject": "",
                    "Type": "",
                    "Category": keyword,
                    "Media Source": category_name,
                    "Country": country,
                    "Date": date_formatted,
                    "Links": link,
                    "Publication": "Kumparan",
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
                print(f"   URL: {driver.current_url if driver.window_handles else 'unknown'}")
                try:
                    print(f"   Title: {driver.title}")
                except:
                    pass
                traceback.print_exc()
                try:
                    if driver.window_handles:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                except Exception as close_err:
                    print(f"⚠️ Failed to close article tab: {close_err}")
                    driver = init_driver()
                continue

        # 3️⃣ Stop if scroll produced nothing new
        if not new_article_found:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)

            articles_after_retry = driver.find_elements(
                By.CSS_SELECTOR, 'div[data-qa-id="story-result-card"]'
            )

            if len(articles_after_retry) == len(articles):
                print("⏹️ No new articles detected — finished.")
                break

        # 4️⃣ Scroll to load MORE
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

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



