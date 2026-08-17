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
import psycopg2, re, json, os, time, uuid, fitz, io
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime, timedelta
from datetime import date as dt_date
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
BASE_DIR = Path(__file__).resolve().parents[1]
RESOURCES_DIR = BASE_DIR / "dags" / "resources"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
OUTPUT_DIR = BASE_DIR / "output"

pdf_path = str(Path(os.getenv("PDF_PATH", SCREENSHOTS_DIR / "Liputan")))
category_path = str(Path(os.getenv("CATEGORY_PATH", RESOURCES_DIR / "categories.json")))
keyword_path = str(Path(os.getenv("KEYWORD_PATH", RESOURCES_DIR / "keywords.json")))
countries_path = str(Path(os.getenv("COUNTRIES_PATH", RESOURCES_DIR / "countries.json")))
excel_path = str(Path(os.getenv("OUTPUT_PATH", OUTPUT_DIR / "Liputan")))


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

# def detect_country_from_text(article_text):
#     """
#     Detects country from the beginning of the article text.
#     Returns the country name if found, else empty string.
#     """

#     # Make text uppercase for consistent matching
#     text_upper = article_text.upper()

#     # Pattern 1: "SITE, CITY - ..." (Liputan6 style)
#     match = re.match(r"^[A-Z0-9\.\-]+,\s*([A-Z\s]+)\s*[-–—]", text_upper)
#     if match:
#         city = match.group(1).strip()
#         for country, cities in country_map.items():
#             if city in cities:
#                 return country

#     # Pattern 2: Fallback: look for known city anywhere in the first 100 chars
#     for country, cities in country_map.items():
#         for city in cities:
#             if city in text_upper[:100]:
#                 return country

#     return ""  # unknown

def detect_country_from_text(article_text):

    text_upper = article_text.upper()

    # Pattern 1: Liputan6 format
    match = re.match(r"^[A-Z0-9\.\-]+,\s*([A-Z\s]+)\s*[-–—]", text_upper)
    if match:
        city = match.group(1).strip()
        for country, cities in country_map.items():
            if city in cities:
                return country

    # Pattern 2: Check first 150 chars safely
    first_part = text_upper[:150]

    for country, cities in country_map.items():
        for city in cities:
            if re.search(rf"\b{re.escape(city)}\b", first_part):
                return country

    return ""

def extract_article_text(driver):
    article_text_parts = []

    def collect_paragraph_text(elements):
        texts = []
        for el in elements:
            text = el.text.strip()
            if not text:
                continue

            lower = text.lower()
            if lower.startswith("baca juga"):
                continue
            if lower == "advertisement":
                continue

            texts.append(text)
        return texts

    # 1️⃣ PRIMARY: Normal article body
    try:
        main_div = driver.find_element(
            By.CSS_SELECTOR, "div.article-content-body__item-content"
        )

        paragraphs = main_div.find_elements(By.TAG_NAME, "p")
        article_text_parts = collect_paragraph_text(paragraphs)

    except:
        pass

    # 2️⃣ FALLBACK: Photo-tag header content (single block text)
    if not article_text_parts:
        try:
            photo_header = driver.find_element(
                By.CSS_SELECTOR, "div.read-page--photo-tag--header__content"
            )
            text = photo_header.text.strip()
            if text:
                article_text_parts.append(text)

        except:
            pass

    # 3️⃣ FALLBACK: readpage__desc paragraph
    if not article_text_parts:
        try:
            desc_p = driver.find_elements(
                By.CSS_SELECTOR, "p.readpage__desc"
            )
            article_text_parts = collect_paragraph_text(desc_p)

        except:
            pass

    # 4️⃣ Final join
    return "\n\n".join(article_text_parts)


INDO_MONTHS = {
    "Januari": 1, "Februari": 2, "Maret": 3, "April": 4,
    "Mei": 5, "Juni": 6, "Juli": 7, "Agustus": 8,
    "September": 9, "Oktober": 10, "November": 11, "Desember": 12
}

def convert_indo_date(text):
    text = text.strip()

    # Case 1: Full date, e.g. "7 Februari 2026"
    try:
        for indo_month, month_num in INDO_MONTHS.items():
            if indo_month in text:
                day, month_name, year = text.split()
                day = int(day)
                month = INDO_MONTHS[month_name]
                year = int(year)
                return datetime(year, month, day).date(), text
    except Exception:
        pass

    # Case 2: Relative time, e.g. "2 jam lalu", "1 hari lalu"
    if "lalu" in text:
        parts = text.split()
        num = int(parts[0])
        unit = parts[1]

        delta = None
        if "jam" in unit:
            delta = timedelta(hours=num)
        elif "hari" in unit:
            delta = timedelta(days=num)
        elif "menit" in unit:
            delta = timedelta(minutes=num)

        if delta:
            return (datetime.now() - delta).date(), text

    # Unknown format
    return None, text


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

def safe_find(parent, by, selector):
    try:
        return parent.find_element(by, selector)
    except:
        return None

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

# while True:
yesterday = (datetime.now() - timedelta(days=1)).date()
day_before = (datetime.now() - timedelta(days=8)).date()
# day_before = datetime.strptime("1 January 2026", "%d %B %Y").date()
# yesterday   = datetime.strptime("9 February 2026", "%d %B %Y").date()
yesterday_str = yesterday.strftime("%d %B %Y")
day_before_str = day_before.strftime("%d %B %Y")
from_date_url = day_before.strftime("%d/%m/%Y")
to_date_url   = yesterday.strftime("%d/%m/%Y")
target_dates = {yesterday, day_before}
earliest_date = min(target_dates)  # the older one (day_before)
date_range = [day_before, yesterday]

master_file = os.path.join(excel_path, "Master_Liputan.xlsx")
temp_file   = excel_file = os.path.join(excel_path, f"{day_before_str}_{yesterday_str}_Liputan.xlsx")
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
driver.get("https://www.liputan6.com/")
CATEGORY_LIST = ["Bali Nusra","Bank", "Crypto", "Ekonomi", "Energi & Tambang", "Histori", "Hollywood", "Home & Decor",
                 "Internasional", "Jawa Barat", "Jawa Tengah - DIY", "Jawa Timur", "K-Pop", "Kalimantan", "Lifestyle",
                 "Megapolitan", "", "News", "Peristiwa", "Politik", "Regional", "Saham", "Selibritis", "Sulawesi",
                 "Sumatera", "Unik"]

for keyword in all_keywords:
    print(f"\n🔍 Searching keyword: '{keyword}' (Date range {day_before_str} → {yesterday_str})")

    search_url = f"https://www.liputan6.com/search?order=latest&channel_id=&from_date={from_date_url}&to_date={to_date_url}&type=all&q={keyword}"
    driver.get(search_url)

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
    rows = []
        
    while not stop_pagination:
        new_article_found = False

        articles = driver.find_elements(
            By.CSS_SELECTOR, "article.articles--iridescent-list--item"
        )

        print(f"📰 Articles currently loaded: {len(articles)}")

        for art in articles:
            try:
                # 🔎 ELEMENTS (FROM YOUR SNIPPET)
                title_el   = safe_find(art, By.CSS_SELECTOR, "h4 a")
                time_el    = safe_find(art, By.CSS_SELECTOR, "time")
                # category_el = safe_find(art, By.CSS_SELECTOR, "a.articles--iridescent-list--text-item__category")

                link = title_el.get_attribute("href") if title_el else None
                if not link:
                    continue

                if link in processed_links or link in master_links or link in temp_links:
                    continue

                processed_links.add(link)
                new_article_found = True

                title = title_el.text.strip() if title_el else None
                # category = category_el.text.strip() if category_el else None

                print(f"➡️ Processing: {title}")

                # ---------- DATE ----------
                dt = None
                pg_datetime = None

                if time_el:
                    # Get the 'datetime' attribute, which is a proper ISO string
                    time_text = time_el.get_attribute("datetime")  # <-- this is a string like "2026-01-27T07:32:15+07:00"
    
                    if time_text:
                        dt = datetime.fromisoformat(time_text)   # Convert to Python datetime
                        pg_datetime = dt.strftime("%Y-%m-%d")  # PostgreSQL friendly
                        print(f"Raw time text: {time_text}")
                        print(f"Article Date: {pg_datetime}")

                    # if article_date:
                    #     formatted_date = article_date.strftime("%-d/%-m/%Y")
                    #     print(f"📅 {formatted_date}")

                # ---------- STOP CONDITIONS ----------
                # if article_date and article_date < earliest_date:
                #     print("⏹️ Old article reached — stopping pagination.")
                #     stop_pagination = True
                #     break

                # if article_date and not (day_before <= article_date <= yesterday):
                #     print("⏩ Skipped (out of date range)")
                #     continue

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
                
                category = None
                try:
                    category_elements = driver.find_elements(
                        By.CSS_SELECTOR,
                        'a.read-page--breadcrumb--item__title[data-category]'
                    )

                    if category_elements:
                        category = category_elements[-1].get_attribute("data-category").strip()
                except Exception as e:
                    print("Category extraction error:", e)
                    category = ""

                if category not in CATEGORY_LIST:
                    print(f"⏭️ Skipping category '{category}'")
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                    continue

                title = ""

                title_selectors = [
                    "h1.read-page--header--title",
                    "h1.readpage__title.mt-4",
                    "h1.read-page--photo-tag--header__title"
                ]

                for selector in title_selectors:
                    try:
                        el = driver.find_element(By.CSS_SELECTOR, selector)
                        if el and el.text.strip():
                            title = el.text.strip()
                            break
                    except:
                        continue

                print("Extracted Title:", title)

                article_text = ""

                try:
                    article_text = extract_article_text(driver)
                    if not article_text:
                        print("⚠️ Article text not found in any known container")
                    country = detect_country_from_text(article_text)
                except Exception as e:
                    print(f"❌ Failed to extract article text: {e}")
                    article_text = ""
                    country = ""
                 
                
                # ---------- SAVE ----------
                print("💾 Saving article")
                row = {
                    "Subject": "",
                    "Type": "",
                    "Category": keyword,
                    "Media Source": category,
                    "Country": country,
                    "Date": pg_datetime,
                    "Links": link,
                    "Publication": "Liputan6",
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

        # 3️⃣ Stop if scroll produced nothing new
        if not new_article_found:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(5)

            articles_after_retry = driver.find_elements(
                By.CSS_SELECTOR, "article.articles--iridescent-list--item"
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



