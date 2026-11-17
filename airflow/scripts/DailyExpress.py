from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from psycopg2.extras import execute_values
from datetime import datetime, timedelta
from urllib.parse import urlparse
import tempfile
from pathlib import Path
from PIL import Image
from fpdf import FPDF
import time
import psycopg2, re, json, os, time, uuid, fitz, io
import pandas as pd
import atexit

# Paths
BASE_DIR = Path(__file__).resolve().parents[1]
RESOURCES_DIR = BASE_DIR / "dags" / "resources"
OUTPUT_DIR = BASE_DIR / "output"

category_path = str(Path(os.getenv("CATEGORY_PATH", RESOURCES_DIR / "categories.json")))
keyword_path = str(Path(os.getenv("KEYWORD_PATH", RESOURCES_DIR / "keywords.json")))
countries_path = str(Path(os.getenv("COUNTRIES_PATH", RESOURCES_DIR / "countries.json")))
excel_path = str(Path(os.getenv("OUTPUT_PATH", OUTPUT_DIR / "Daily Express")))
url = "https://www.dailyexpress.com.my/"

# conn = psycopg2.connect(host="192.168.1.132", database="adverse_media", user="postgres", password="Verity@456")
# cursor = conn.cursor()

# os.makedirs(pdf_path, exist_ok=True)
os.makedirs(excel_path, exist_ok=True)

options = webdriver.ChromeOptions()
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--incognito")
options.add_argument("--enable-unsafe-swiftshader")
options.add_argument("--disable-infobars")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-browser-side-navigation")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument('--ignore-certificate-errors')
options.add_argument('--ignore-ssl-errors')
options.add_argument("--start-maximized")
options.binary_location = "/usr/bin/google-chrome"

driver = webdriver.Chrome(
    service=Service("/usr/local/bin/chromedriver"),
    options=options
)
PAGE_LOAD_TIMEOUT = 60      # seconds
MAX_KEYWORD_ATTEMPTS = 3    # attempts per keyword per date before skipping it
driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)


def new_driver():
    d = webdriver.Chrome(service=Service("/usr/local/bin/chromedriver"), options=options)
    d.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return d


def open_search_form():
    """Load the homepage and open the search form (same steps as the start of each date)."""
    driver.get(url)
    time.sleep(10)
    WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.LINK_TEXT, "Search"))
    ).click()
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.ID, "searchForm"))
    )


driver.get(url)

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

#Categories
with open(category_path, "r", encoding="utf-8") as f:
    publication_data = json.load(f)

publication_list = publication_data["publication"][0]
source_category_map = {
    entry["source"]: entry["category"]
    for entry in publication_list.values()
}
domain = urlparse(url).netloc
current_source = "dailyExpress" if "dailyexpress.com.my" in domain else None
allowed_categories = source_category_map.get(current_source, [])

#Keywords
with open(keyword_path, "r", encoding="utf-8") as f:
    data = json.load(f)

languages = data["language"][0]
english_keywords = languages.get("English", {}).get("keywords", [])
all_keywords = english_keywords 

#Countries
with open(countries_path, "r", encoding="utf-8") as f:
    country_map = json.load(f)

def detect_country_from_text(article_text):
    match_comma = re.match(r"^([A-Z][A-Z\s]+?),\s*([A-Z][A-Z\s]+)", article_text)
    if match_comma:
        return match_comma.group(2).strip().title()

    match_colon = re.match(r"^([A-Z][A-Za-z\s]*)\s*[:-]", article_text)
    if match_colon:
        possible_state = match_colon.group(1).strip()
        for country, states in country_map.items():
            if possible_state in states:
                return country
        return possible_state

    return ""

# def scroll_and_capture(driver, pdf_id, save_path, title, date, publication, url):
#     WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

#     scroll_pause = 1.5
#     screenshots = []
#     index = 0
#     max_scrolls = 20

#     # Step 1: Minimal ad removal
#     driver.execute_script("""
#         const selectors = [
#             'div.catfish_wrapper',
#             '.adsbygoogle, .sponsorcard, [id^="gpt"], script, ins'
#         ];
#         selectors.forEach(sel => document.querySelectorAll(sel).forEach(el => el.remove()));
#     """)

#     # Step 2: Scroll to top
#     driver.execute_script("window.scrollTo(0, 0);")
#     time.sleep(1)

#     last_scroll = -1
#     current_scroll = driver.execute_script("return window.scrollY")
#     scrolls_done = 0

#     while current_scroll != last_scroll and scrolls_done < max_scrolls:
#         try:
#             screenshot_path = os.path.join(pdf_path, f"{pdf_id}_{index}.png")
#             driver.save_screenshot(screenshot_path)
#             screenshots.append(screenshot_path)
#             print(f"Screenshot {index} taken")
#             index += 1
#         except Exception as e:
#             print(f"Screenshot failed: {e}")
#             break

#         last_scroll = current_scroll
#         driver.execute_script("window.scrollBy(0, window.innerHeight);")
#         time.sleep(scroll_pause)
#         current_scroll = driver.execute_script("return window.scrollY")
#         scrolls_done += 1

#     # Step 4: Stitch screenshots
#     images = [Image.open(p) for p in screenshots]
#     total_height = sum(img.height for img in images)
#     stitched_width = max(img.width for img in images)

#     stitched = Image.new("RGB", (stitched_width, total_height))
#     y_offset = 0
#     for img in images:
#         stitched.paste(img, (0, y_offset))
#         y_offset += img.height
#         img.close()

#     for img_path in screenshots:
#         os.remove(img_path)

#     stitched_path = os.path.join(pdf_path, f"{pdf_id}_stitched.png")
#     stitched.save(stitched_path)

#     # Step 5: Generate PDF
#     a4_width_mm = 210
#     a4_height_mm = 297
#     margin = 10
#     content_height_mm = a4_height_mm - 2 * margin - 20

#     slice_height = images[0].height * 2
#     num_slices = (stitched.height + slice_height - 1) // slice_height

#     pdf = PDF(title, date, publication, url, orientation='P', unit='mm', format='A4')

#     for i in range(num_slices):
#         upper = i * slice_height
#         lower = min((i + 1) * slice_height, stitched.height)
#         part = stitched.crop((0, upper, stitched_width, lower))
#         part_aspect = part.width / part.height

#         fixed_width = a4_width_mm - margin * 2
#         part_height = min(fixed_width / part_aspect, content_height_mm)
#         x_centered = (a4_width_mm - fixed_width) / 2
#         y = margin + 30

#         temp_part_path = stitched_path.replace(".png", f"_{uuid.uuid4().hex}.png")
#         part.save(temp_part_path)

#         pdf.add_page()
#         pdf.image(temp_part_path, x=x_centered, y=y, w=fixed_width, h=part_height)
#         os.remove(temp_part_path)

#     pdf.output(save_path)
#     os.remove(stitched_path)
#     print(f"PDF saved with {num_slices} page(s): {save_path}")
#     return True

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

def scroll_and_capture(driver, pdf_id, save_path, title, date, publication, url):
    try:
        # Ensure the page is loaded
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2)

        # Minimal ad removal
        driver.execute_script("""
            const selectors = [
                'div.catfish_wrapper',
                '.adsbygoogle, .sponsorcard, [id^="gpt"], script, ins'
            ];
            selectors.forEach(sel => document.querySelectorAll(sel).forEach(el => el.remove()));
        """)

        # Scroll to top
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

        # Take screenshot of current viewport
        screenshot_path = os.path.join(pdf_path, f"{pdf_id}_top.png")
        driver.save_screenshot(screenshot_path)

        # Create PDF
        pdf = PDF(title, date, publication, url, orientation='P', unit='mm', format='A4')
        pdf.add_page()
        pdf.image(screenshot_path, x=10, y=40, w=190)  # adjust position/width if needed
        pdf.output(save_path)

        os.remove(screenshot_path)
        print(f"PDF saved with 1 page: {save_path}")
    
        compressed_temp = save_path.replace(".pdf", "_compressed_temp.pdf")
        if compress_screenshot_pdf(save_path, compressed_temp, quality=35, max_width=1000):
            os.replace(compressed_temp, save_path)
            print(f"✅ Replaced with compressed PDF: {save_path}")
        else:
            print("⚠️ Compression failed. Original PDF kept.")

        return True

    except Exception as e:
        print(f"Top screenshot capture failed: {e}")
        return False

def insert_row(row, conn, cursor):
    try:
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
                row["Date"],             # Date
                row["Category"],         # Category
                row["Media Source"],     # Media Source
                row["Country"],          # Country
                row["Links"],            # Links
                row["Publication"],      # Publication
                row["Title"],            # Title
                row["Article Text"],     # Article Text
                row["Subject"],          # Subject
                row["Status"],           # Status
                row["Type"],             # Type
            )
            for _, row in df_temp.iterrows()
        ]
        execute_values(cursor, insert_sql, rows_to_insert)
        conn.commit()
        print(f"✅ Inserted {len(rows_to_insert)} rows into PostgreSQL")
        return True
    except Exception as e:
        print(f"Insert error: {e}")
        return False
    
def extract_article_text_with_retry(driver, url, retries=1):
    """Try extracting article text, retry if it fails or is empty."""
    for attempt in range(retries + 1):
        try:
            # Wait until container exists
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.newsContent"))
            )
            article_container = driver.find_element(By.CSS_SELECTOR, "div.newsContent")

            # Wait for visible text
            WebDriverWait(driver, 120).until(
                lambda d: article_container.text.strip() != ""
            )
            text = article_container.text.strip()

            if text:  # ✅ success
                return text
            else:
                print(f"⚠️ Empty text attempt {attempt+1} for {url}")
        except Exception as e:
            print(f"⚠️ Extraction attempt {attempt+1} failed for {url}: {e}")

        # if not last attempt → wait + retry
        if attempt < retries:
            time.sleep(3)
            driver.refresh()  # reload the page for retry
    return ""  # still failed

def cleanup_driver():
    try:
        driver.quit()
    except:
        pass

columns = [
    "Subject", "Type", "Category", "Media Source", "Country", "Date",
    "Links", "Publication", "Title", "Article Text", "Status"
]

# while True:
yesterday = (datetime.now() - timedelta(days=1)).date()
day_before = (datetime.now() - timedelta(days=3)).date()
yesterday_str = yesterday.strftime("%d %B %Y")
day_before_str = day_before.strftime("%d %B %Y")

date_range = [yesterday,day_before]

master_file = os.path.join(excel_path, "Master_DailyExpress.xlsx")
temp_file   = excel_file = os.path.join(excel_path, f"{day_before_str}_{yesterday_str}_DailyExpress.xlsx")
# temp_file   = excel_file = os.path.join(excel_path, f"12 May 2026_17 May 2026_DailyExpress.xlsx")
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

for current_date in date_range:
    found_any = False

    try:
        driver.get(url)
        time.sleep(10)
        #Click search
        WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.LINK_TEXT, "Search"))
        ).click()

        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "searchForm"))
        )

        keyword_index = 0
        keyword_attempts = 0

        while keyword_index < len(all_keywords):
            keyword = all_keywords[keyword_index]
            print(f"\nSearching for: '{keyword}' on {current_date}")

            try:
                #Find and enter keyword in search input
                search_input = WebDriverWait(driver, 15).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, '#searchForm input[name="query"]'))
                )
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", search_input)
                time.sleep(0.5)
                search_input.clear()
                search_input.send_keys(keyword)

                #Expand the Advanced Search form
                try:
                    advanced_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "button.accordion-button"))
                    )
                    if "collapsed" in advanced_button.get_attribute("class"):
                        driver.execute_script("arguments[0].click();", advanced_button)
                        time.sleep(0.5)
                except Exception as e:
                    print("Advanced Search error:", e)

                #Set date
                Select(driver.find_element(By.ID, "sDay")).select_by_value(str(current_date.day))
                Select(driver.find_element(By.ID, "sMonth")).select_by_value(str(current_date.month))
                Select(driver.find_element(By.ID, "sYear")).select_by_value(str(current_date.year))

                #Submit
                submit_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"][form="searchForm"]'))
                )
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_button)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", submit_button)

                time.sleep(10)

                #If no results
                try:
                    alert_box = driver.find_element(By.CSS_SELECTOR, "div.alert.alert-warning")
                    if "No search result were found" in alert_box.text:
                        print(f"No results found for '{keyword}' on {current_date}.")
                        keyword_index += 1
                        keyword_attempts = 0
                        continue
                except:
                    pass

                #Process results
                skip_to_next_keyword = False
                WebDriverWait(driver, 10).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.col-12.p-0.border-top"))
                )
                article_cards = driver.find_elements(By.CSS_SELECTOR, "div.col-12.mb-3")

                try:
                    # # Build file path first
                    # yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%d %b %Y")
                    # excel_file = os.path.join(excel_path, f"{yesterday_str}_DailyExpress.xlsx")

                    # # Read existing links if file exists
                    # existing_links = set()
                    # existing_df = pd.DataFrame(columns=columns)
                    
                    # # Read existing links if file exists
                    # if os.path.exists(excel_file):
                    #     try:
                    #         existing_df = pd.read_excel(excel_file)
                    #         if "Links" in existing_df.columns:
                    #             existing_links = set(existing_df["Links"].dropna().astype(str))
                    #     except Exception as e:
                    #         print(f"⚠️ Could not read existing Excel: {e}")
                    
                    for card in article_cards:
                        try:
                            title_el = card.find_element(By.CSS_SELECTOR, "div.title.titlesubheader a")
                            href = title_el.get_attribute("href")
                            title = title_el.text.strip()
                        except:
                            continue

                        if not href:
                            continue

                        if href.startswith("http"):
                            full_url = href
                        else:
                            full_url = f"https://www.dailyexpress.com.my{href}"

                        if full_url in master_links or full_url in temp_links:
                                print(f"⏭️ Skipping duplicate before opening: {full_url}")
                                continue

                        #Extract data
                        badge_elements = card.find_elements(By.CSS_SELECTOR, "span.badge")
                        date_obj = None
                        category = ""

                        for badge in badge_elements:
                            text = badge.text.strip()
                            if "," in text:
                                try:
                                    date_obj = datetime.strptime(text, "%B %d, %Y").date()
                                except:
                                    date_obj = None
                            elif text.title() in allowed_categories:
                                category = text.title()

                        if not category or category not in allowed_categories:
                            print(f"Category mismatch: '{category}'")
                            continue

                        if not date_obj:
                            print("No date found.")
                            continue

                        if date_obj > current_date:
                            print(f"Skipping article from {date_obj} (after {current_date})")
                            continue
                        elif date_obj < current_date:
                            print(f"Article: {date_obj} (before {current_date}).")
                            skip_to_next_keyword = True
                            break

                        #Skip duplicates based on the links in searched page/tab
                        # cursor.execute("SELECT 1 FROM automation_table WHERE Links = %s", (full_url,))
                        # if cursor.fetchone():
                        #     print("Duplicate article")
                        #     continue

                        #Open the valid article
                        existing_tabs = set(driver.window_handles)
                        driver.execute_script("window.open(arguments[0]);", full_url)
                        WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > len(existing_tabs))
                        new_tab = list(set(driver.window_handles) - existing_tabs)[0]
                        
                        main_tab = driver.current_window_handle
                        driver.switch_to.window(new_tab)

                        try:
                            # Wait until the container exists
                            WebDriverWait(driver, 20).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, "div.newsContent"))
                            )
                            article_container = driver.find_element(By.CSS_SELECTOR, "div.newsContent")

                            # Clean up unwanted elements first (ads, ins, script, etc.)
                            driver.execute_script("""
                                const container = arguments[0];
                                container.querySelectorAll('script, style, ins, .sponsorcard, #gpt-passback').forEach(el => el.remove());
                            """, article_container)

                            # Wait for visible text to appear
                            WebDriverWait(driver, 10).until(
                                lambda d: article_container.text.strip() != ""
                            )

                            article_text = extract_article_text_with_retry(driver, full_url, retries=1) 
                            print(f"\nTitle: {title}\nDate: {date_obj}\nText: {article_text[:300]}...\n")
                        
                        except Exception as e:
                            print("Failed to extract article text:", e)
                            article_text = ""


                        # pdf_id = str(uuid.uuid4())
                        row = {
                            "Subject": "",
                            "Type": "",
                            "Category": keyword,
                            "Media Source": category,
                            "Country": detect_country_from_text(article_text),
                            "Date": date_obj.strftime("%d %b %Y"),
                            "Links": full_url,
                            "Publication": "Daily Express",
                            "Title": title,
                            "Article Text": article_text,
                            # "PDF_ID": None, #pdf_id,
                            "Status": "1"
                        }

                        #Save screenshot to pdf
                        # pdf_filename = f"{pdf_id}.pdf"
                        # pdf_output_path = os.path.join(pdf_path, pdf_filename)
                        # print(f"Generating PDF:")
                        # try:
                        #     scroll_and_capture(driver, pdf_id, pdf_output_path, title, date_obj, current_source, full_url)
                        # except Exception as e:
                        #     print(f"Failed to generate PDF: {e}")
                        # Skip screenshot/PDF generation
                        # print("Skipping PDF generation for:", title)

                        # success = insert_row(row, conn, cursor)

                        # if success:
                        #     print("Inserted the article into db")
                        #     found_any = True
                        # else:
                        #     print("Insert timeout or error. Retrying keyword on same date...")
                        #     driver.close()
                        #     driver.switch_to.window(driver.window_handles[0])
                        #     break  

                        # Only save if article text was successfully extracted
                        try:
                            if not article_text or len(article_text.strip()) < 50:  # adjust threshold if needed
                                print(f"⚠️ Skipping save because article text is empty or too short for: {full_url}")
                            elif row["Links"] in master_links or row["Links"] in temp_links:
                                print(f"⏩ Duplicate found, skipping: {row['Links']}")
                            else:
                                df_row = pd.DataFrame([row], columns=columns)
                                df_temp = pd.concat([df_temp, df_row], ignore_index=True)
                                temp_links.add(row["Links"])

                                df_temp.to_excel(temp_file, index=False)
                                print("✅ Wrote 1 entry to TEMP Daily Express file")
                        except Exception as e:
                            print(f"❌ Failed to write to temp Excel: {e}")
                        
                        finally:
                            # ✅ This ALWAYS runs, even on errors
                            driver.close()
                            driver.switch_to.window(main_tab)
                
                except Exception as e:
                    print(f"❌ Failed during scraping: {e}")
                
                if skip_to_next_keyword:
                    keyword_index += 1
                    keyword_attempts = 0
                    continue

                #Move to next keyword after processing all articles for current one
                keyword_index += 1
                keyword_attempts = 0

            except Exception as e:
                # Old code: a localhost timeout retried this keyword forever, and ANY other
                # error fell through and retried it at once with no pause or limit
                # (12 Nov: 212x "Searching for: 'Abuse'" in 0.2 s, then a hang).
                keyword_attempts += 1
                print(f"Error on keyword '{keyword}' on {current_date} (attempt {keyword_attempts}/{MAX_KEYWORD_ATTEMPTS}): {e}")

                # Close stray article tabs
                try:
                    handles = driver.window_handles
                    if len(handles) > 1:
                        main_tab = handles[0]
                        for tab in [h for h in handles if h != main_tab]:
                            try:
                                driver.switch_to.window(tab)
                                driver.close()
                            except Exception as tab_err:
                                print(f"Failed to close tab {tab}: {tab_err}")
                        driver.switch_to.window(main_tab)
                except Exception as tab_err:
                    print(f"Error while cleaning up tabs: {tab_err}")

                if keyword_attempts >= MAX_KEYWORD_ATTEMPTS:
                    print(f"Skipping keyword '{keyword}' on {current_date} after {MAX_KEYWORD_ATTEMPTS} attempts")
                    keyword_index += 1
                    keyword_attempts = 0

                time.sleep(5)
                # Get back to a clean search form; on a hung/dead browser, restart it.
                try:
                    open_search_form()
                except Exception as reload_err:
                    print(f"Search form reload failed, restarting driver: {reload_err}")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = new_driver()
                    open_search_form()  # if this fails too, the outer handler moves to the next date
                continue

    except Exception as e:
        print(f"Fatal error, retrying: {e}")
        time.sleep(3)
        continue

    # if found_any:
    #     print(f"Completed all keywords for {current_date}")
    #     backtrack_days = 0
    #     current_date -= timedelta(days=1)
    # else:
    #     print(f"No articles found for {current_date}.")
    #     backtrack_days += 1
    #     if backtrack_days >= reset_limit:
    #         print("No articles found in last 30 days. Stopping.")
    #         break
    #     current_date -= timedelta(days=1)

# Cleanup
print("Transferring scraped data into master file...")

# Reload master in case it changed
if os.path.exists(master_file):
    df_master = pd.read_excel(master_file)

df_master = pd.concat([df_master, df_temp], ignore_index=True)
df_master.drop_duplicates(subset=["Links"], keep="first", inplace=True)

df_master.to_excel(master_file, index=False)
print(f"Transfer complete. {len(df_temp)} rows added to {master_file}")

#✅ Insert df_temp into PostgreSQL

conn = psycopg2.connect(host="192.168.1.132", database="adverse_media", user="postgres", password="Verity@456")
cursor = conn.cursor()

if not df_temp.empty:
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
            row["Date"],             # Date
            row["Category"],         # Category
            row["Media Source"],     # Media Source
            row["Country"],          # Country
            row["Links"],            # Links
            row["Publication"],      # Publication
            row["Title"],            # Title
            row["Article Text"],     # Article Text
            row["Subject"],          # Subject
            row["Status"],           # Status
            row["Type"],             # Type
        )
        for _, row in df_temp.iterrows()
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

print("✅ Scraping completed.")

