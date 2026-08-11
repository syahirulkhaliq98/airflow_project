import time
from datetime import datetime, timedelta
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import os, time, uuid, re, json, io, pickle
from fpdf import FPDF
from bs4 import BeautifulSoup
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
import undetected_chromedriver as uc
from urllib.parse import urlparse

BASE_URL = 'https://www.thestar.com.my'
FOLDER_NAME="The Star"
EXCEL_FILE = r"/home/khaliq/airflow_project/airflow/output/The Star"
LOCATIONS = r"/home/khaliq/airflow_project/airflow/dags/resources/countries.json"
KEYWORDS = r"/home/khaliq/airflow_project/airflow/dags/resources/keywords.json"
CATEGORY_FILTER = r"/home/khaliq/airflow_project/airflow/dags/resources/categories.json"
GOOGLE_EMAIL = "instacheck2020@gmail.com"
GOOGLE_PASSWORD = "instacheck2010@123"

columns = [
    "Subject", "Type", "Category", "Media Source", "Country", "Date",
    "Links", "Publication", "Title", "Article Text", "Status"
]
master_links = set()  # All saved links across runs (loaded from Excel in saveResult)
temp_links = set()    # Links collected in this run only

# YESTERDAY = (datetime.now() - timedelta(days=1)).date()
# DAY_BEFORE = (datetime.now() - timedelta(days=2)).date()
# ALLOWED_DATES = {YESTERDAY, DAY_BEFORE}
# yesterday_str = YESTERDAY.strftime("%d %B %Y")
# day_before_str = DAY_BEFORE.strftime("%d %B %Y")

end_date = (datetime.now() - timedelta(days=1)).date()
start_date = (datetime.now() - timedelta(days=5)).date()
# start_date = datetime(2026, 3, 8).date()
# end_date   = datetime(2026, 3, 1).date()

# Generate all dates in the range
ALLOWED_DATES = {
    (start_date + timedelta(days=i))
    for i in range((end_date - start_date).days + 1)
}
start_date_str = start_date.strftime("%d %B %Y")
end_date_str = end_date.strftime("%d %B %Y")
master_file = os.path.join(FOLDER_NAME, "Master_The_Star.xlsx")
temp_file   = os.path.join(FOLDER_NAME, f"{start_date_str}_{end_date_str}_The_Star.xlsx")

# --- Setup driver ---

def init_driver():
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument("--disable-features=ChromeSignin,AccountConsistency,UnifiedConsent")
    chrome_options.add_argument("--disable-sync")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--incognito")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-features=PreloadMediaEngagementData,MediaEngagementBypassAutoplayPolicies")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-features=SigninInterception")
    chrome_options.add_argument("--disable-features=ChromeWhatsNewUI,ChromeSigninIntercept")
    driver = uc.Chrome(version_main=144, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.set_page_load_timeout(120)
    wait = WebDriverWait(driver, 20)
    return driver

driver = init_driver()
driver.set_page_load_timeout(120)
wait = WebDriverWait(driver, 20)
# Create folder for screenshots
os.makedirs(FOLDER_NAME, exist_ok=True)

results = []

# Load master file once
if os.path.exists(master_file):
    try:
        df_master = pd.read_excel(master_file)
        if "Links" in df_master.columns:
            master_links.update(df_master["Links"].dropna().astype(str))
        print(f"Loaded {len(master_links)} master links from {master_file}")
    except Exception as e:
        print(f"⚠️ Could not read master file: {e}")

# Load temp file once
if os.path.exists(temp_file):
    try:
        df_temp = pd.read_excel(temp_file)
        if "Links" in df_temp.columns:
            temp_links.update(df_temp["Links"].dropna().astype(str))
        print(f"Loaded {len(temp_links)} temp links from {temp_file}")
    except Exception as e:
        print(f"⚠️ Could not read temp file: {e}")

with open(CATEGORY_FILTER, "r", encoding="utf-8") as f:
    publication_data = json.load(f)

publication_list = publication_data["publication"][0]
source_category_map = {
    entry["source"]: entry["category"]
    for entry in publication_list.values()
}
domain = urlparse(BASE_URL).netloc
if "thestar.com.my" in domain:
    current_source = "theStar"
else:
    current_source = None
allowed_categories = source_category_map.get(current_source, [])

# Load country map
with open(LOCATIONS, "r", encoding="utf-8") as f:
    raw_country_map = json.load(f)

country_map = {
    country: set(loc.lower() for loc in locations)
    for country, locations in raw_country_map.items()
}

with open(KEYWORDS, "r", encoding="utf-8") as f:
    data = json.load(f)

languages = data["language"][0]
english_keywords = languages.get("English", {}).get("keywords", [])
all_keywords = english_keywords 

def detect_country_from_text(text, country_map):
    if not text:
        return ""
    first_part = re.split(r'[:\-]', text, maxsplit=1)[0].strip()
    first_part = re.sub(r'\(.*?\)', '', first_part).strip().rstrip(',').lower()
    if not first_part:
        return ""
    for country, locations in country_map.items():
        if first_part in locations:
            return country
    return first_part.title()

# --- Google Login ---
class TheStarGoogleLogin:
    def __init__(self, driver,wait, email, password):
        self.driver = driver
        self.wait = wait
        self.email = email
        self.password = password
    
    def login_with_google(self):
        """
        Login to The Star using Google authentication
        
        Args:
            email: instacheck2020@gmail.com
            password: instacheck2010@123
        """
        try:
            print("Opening The Star website...")
            self.driver.get("https://www.thestar.com.my")
            handle_ads(driver)
            
            # Wait for page to load
            time.sleep(3)
            
            # Look for login/sign in button (may vary based on current site design)
            login_selectors = [
                "//a[contains(text(), 'Sign In')]",
                "//a[contains(text(), 'Login')]", 
                "//button[contains(text(), 'Sign In')]",
                "//button[contains(text(), 'Login')]",
                ".login-btn",
                ".sign-in-btn",
                "#login-button"
            ]
            
            login_button = None
            login_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, "/html/body/header/div/div/ul/li[2]/a")))
            
            if not login_button:
                print("Could not find login button. Please check the website structure.")
                return False
            
            print("Clicking login button...")
            login_button.click()
            
            # Wait for login options to appear
            time.sleep(2)
            
            # Look for Google login button
            google_selectors = [
                "//button[contains(text(), 'Google')]",
                "//a[contains(text(), 'Google')]",
                "//button[contains(@class, 'google')]",
                "//a[contains(@class, 'google')]",
                ".google-login-btn",
                "#google-login"
            ]
            
            try:
    # Wait for the Google button to be clickable
                google_button = wait.until(EC.element_to_be_clickable((
                    By.XPATH,
                    "/html/body/div[1]/div/div[1]/div[6]/div[2]/ul/li[1]/button"
                )))
                print("✅ Google login button found.")
                google_button.click()
                print("🖱️ Clicked Google login button.")
            except Exception as e:
                print("❌ Google login button not found or failed to click.")
                driver.save_screenshot("google_button_error.png")
                print("Exception:", e)
                return False

            print("All window handles:", driver.window_handles)
            print("Current window title:", driver.title)
            print("Current URL:", driver.current_url)
            print("Current page source (truncated):")
            print(driver.page_source[:1000])

            # Switch to Google login window/tab if opened in new window
            
            # Enter email
            print("Entering email...")
            email_selectors = [
                "input[type='email']",
                "#identifierId",
                "input[name='email']"
            ]

            try:
                email_input = None
                email_input = self.wait.until(EC.presence_of_element_located(( By.ID, "identifierId")))
                
                email_input.clear()
                email_input.send_keys(self.email)
            except Exception as e:
                print("❌ Failed to locate or fill email input.")
                print("Exception:", type(e).__name__, "-", str(e))
                driver.save_screenshot("error_email_input.png")  # Save screenshot for debug
                print("📸 Screenshot saved as error_email_input.png")
                return False
            
            # Click Next button
            next_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='Next']]")))
            next_button.click()
            
            # Wait for password field
            time.sleep(2)
            
            print("Entering password...")
            password_input = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='password']")))
            password_input.clear()
            password_input.send_keys(self.password)
            
            # Click Next button for password
            password_next = self.wait.until(EC.element_to_be_clickable((By.ID, "passwordNext")))
            password_next.click()            
            # Wait for login to complete and redirect
            print("Waiting for login to complete...")
            time.sleep(5)

            try:
                # Wait for the modal to appear (you can adjust timeout)
                self.wait.until(
                    EC.presence_of_element_located((By.CLASS_NAME, "modal-dialog"))
                )
                
                # Click the "Continue here" button
                continue_button = self.wait.until(EC.element_to_be_clickable((By.ID, "logout")))
                continue_button.click()

            except Exception as e:
                print("Modal not found or error occurred:", e)
            
            # Switch back to original window if needed
            if len(self.driver.window_handles) > 1:
                self.driver.switch_to.window(self.driver.window_handles[0])
                print("window switch ")
            
            # Check if login was successful
            time.sleep(3)
            print(self.driver.current_url)
            
            # Look for signs of successful login
            
            login_successful = False
            try:
                self.wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "li#login_menu ul.dropdown-menu")))
                print("✅ Login successful — user menu detected.")
                login_successful = True
            except:
                print("❌ Login may have failed or dropdown menu not found.")
                login_successful = False

            if login_successful:
                    print("✅ Login successful!")
                    return True
            else:
                print("❌ Login may have failed or page structure changed.")
                return False
                
        except Exception as e:
            raise RuntimeError(f"❌ Error during login: {e}") from e
            return False
        
def search():
    
    search_icon = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="page-header"]/div/div/ul/li[4]/label/div')))
    search_icon.click()
    time.sleep(20)
    search_box = wait.until(EC.visibility_of_element_located((By.ID, "queryly_query")))
    search_box.clear()
    search_box.send_keys(keyword)
    time.sleep(2)
    search_comfirm = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="advanced_searchbutton"]')))
    search_comfirm.click()
    time.sleep(10)

def orderByFilter():
    
    try:
        WebDriverWait(driver,10).until(EC.presence_of_element_located((By.ID, "sortby")))
        sort_dropdown = driver.find_element(By.ID, "sortby")
        sort_dropdown.click()
        time.sleep(1)
        newest_option = driver.find_element(By.XPATH, '//*[@id="sortby"]/option[2]')
        newest_option.click()
        time.sleep(3)
    except Exception as e:
        print(f"[orderByFilter] Unable to find sort dropdown: {e}")

class PDF(FPDF):
    def header(self):
        self.set_font("Arial", size=10)
        self.cell(0, 10, "Free Malaysia Today Article", ln=True, align="C")

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", size=8)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    def add_screenshot(self, image_path):
        self.add_page()
        self.image(image_path, x=10, y=20, w=190)

def create_pdf(article_id, screenshot_paths, pdf_folder):

    if not screenshot_paths:
        print(f"❌ No screenshots to create PDF for article: {article_id}")
        return None
    
    pdf = PDF()
    for img_path in screenshot_paths:
        pdf.add_screenshot(img_path)

    os.makedirs(pdf_folder, exist_ok=True)
    pdf_filename = f"{article_id}.pdf"
    pdf_path = os.path.join(pdf_folder, pdf_filename)
    pdf.output(pdf_path)

    # Cleanup: Delete screenshots after PDF creation
    return pdf_filename

def scroll_and_capture(driver, article_id, folder):
    total_height = driver.execute_script("return document.body.scrollHeight")
    viewport_height = driver.execute_script("return window.innerHeight")
    scroll = 0
    screenshot_paths = []

    i = 0

    ad_removal_script = """
        const selectors = [
            '.freeModal',
            '.modal', 
            '.popup', 
            '.ads', 
            '[id*="ad"]', 
            '[class*="ad"]',
            'section.Inline.Ads-slot',
            'div.ads',
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
        selectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(el => el.remove());
        });
    """

    while scroll < total_height:
        driver.execute_script(f"window.scrollTo(0, {scroll});")
        time.sleep(1)
        driver.execute_script(ad_removal_script)
        filename = os.path.join(folder, f"{article_id}_ss{i}.png")
        driver.save_screenshot(filename)
        screenshot_paths.append(filename)
        scroll += viewport_height
        i += 1
        total_height = driver.execute_script("return document.body.scrollHeight")

    return screenshot_paths

def nextPage():
    next_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="resultdata"]/a')))
            
    if 'disabled' in next_btn.get_attribute('class').lower():
        print("No more pages. Ending loop.")
    
    next_btn.click()
    print("click next page")
    time.sleep(3)

def saveResult():
    global master_links, temp_links
    if not results:
        print(f"No articles found for keyword '{keyword}'")
        return

    try:
        start_date = (datetime.now() - timedelta(days=7)).date()
        end_date = (datetime.now() - timedelta(days=1)).date()
        valid_dates = {
            (start_date + timedelta(days=i))
            for i in range((end_date - start_date).days + 1)
        }

        # load existing temp file for merging
        existing_df = pd.DataFrame()
        if os.path.exists(temp_file):
            try:
                existing_df = pd.read_excel(temp_file)
            except Exception as e:
                print(f"⚠️ Could not read {temp_file}: {e}")

        # filter results
        new_rows = []
        for row in results:
            try:
                article_date = pd.to_datetime(row["Date"]).date()
            except Exception:
                print(f"⚠️ Could not parse date for {row['Links']}")
                continue

            if article_date not in valid_dates:
                print(f"⏩ Skipping {row['Links']} (not in allowed dates)")
                continue

            if row["Links"] in master_links:
                print(f"⚠️ Already in master: {row['Links']}")
                continue

            new_rows.append(row)

        if not new_rows:
            print("ℹ️ Nothing new to save.")
            return

        # save combined to temp
        new_df = pd.DataFrame(new_rows)
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        combined_df.drop_duplicates(subset=["Links"], inplace=True)
        combined_df.to_excel(temp_file, index=False)
        print(f"✅ Saved {len(new_rows)} new rows to {temp_file}")

        # also update master file
        if os.path.exists(master_file):
            df_master = pd.read_excel(master_file)
        else:
            df_master = pd.DataFrame()
        combined_master = pd.concat([df_master, new_df], ignore_index=True)
        combined_master.drop_duplicates(subset=["Links"], inplace=True)
        combined_master.to_excel(master_file, index=False)
        print(f"✅ Updated master file with {len(new_rows)} rows")

        # update global sets
        for row in new_rows:
            master_links.add(row["Links"])
            temp_links.add(row["Links"])

    except Exception as e:
        print(f"❌ Failed to save results: {e}")

# def saveResult():
#     global seen_links
#     if not results:
#         print(f"No articles found for keyword '{keyword}'")
#         return

#     try:
#         # --- Build file path for yesterday ---
#         excel_date = YESTERDAY.strftime("%d %b %Y")
#         safe_keyword = keyword.replace(" ", "_").replace("/", "_")
#         filename = os.path.join(FOLDER_NAME, f"{excel_date}_The_Star.xlsx")

#         # --- Load existing Excel if exists ---
#         existing_df = pd.DataFrame()
#         if os.path.exists(filename):
#             try:
#                 existing_df = pd.read_excel(filename)
#                 if "Links" in existing_df.columns:
#                     seen_links.update(existing_df["Links"].dropna().astype(str))
#                 print(f"{len(existing_df)} existing rows from {filename}")
#             except Exception as e:
#                 print(f"⚠️ Could not read existing Excel file: {e}")

#         # --- Filter new results (avoid duplicates by Links) ---
#         new_rows = []
#         for row in results:
#             if row["Links"] in seen_links:
#                 print(f"⚠️ Skipping duplicate: {row['Links']}")
#             else:
#                 new_rows.append(row)

#         if not new_rows:
#             print("ℹ️ No new articles to save (all duplicates).")
#             return

#         # --- Merge and save ---
#         new_df = pd.DataFrame(new_rows)
#         combined_df = pd.concat([existing_df, new_df], ignore_index=True)
#         combined_df.drop_duplicates(subset=["Links"], keep="first", inplace=True)

#         combined_df.to_excel(filename, index=False)
#         print(f"✅ Wrote {len(new_rows)} new entries to {filename}")

#         for row in new_rows:
#             seen_links.add(row["Links"])

#     except Exception as e:
#         print(f"❌ Failed to save results: {e}")

def handle_ads(driver):
    try:
        # Wait max 5s for the ad to appear
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "desktop-interstitial-v2"))
        )

        # Try direct removal first
        driver.execute_script("""
            var ad = document.getElementById("desktop-interstitial-v2");
            if (ad) {
                ad.remove();
            }
        """)
        print("✅ Ad removed via script")

    except:
        try:
            # If removal fails, try clicking the close button
            close_btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".mediabox-close-btn"))
            )
            close_btn.click()
            print("✅ Ad closed via button")
        except:
            print("⚠️ No ad found or already closed")

def getArticle():
    articles = driver.find_elements(By.XPATH, '//div[contains(@class, "queryly_item_container")]')
    print(f"{len(articles)} articles found on page")
    stop = False
    
    for i in range(len(articles)):
        try:
            articles = driver.find_elements(By.XPATH, '//div[contains(@class, "queryly_item_container")]')
            article = articles[i]

            title_el = article.find_element(By.XPATH, './/h2[@class="f18"]/a')
            title = title_el.text.strip()
            url = title_el.get_attribute('href')
            print(title)
            print(url)

            # Skip duplicates early
            if url in master_links or url in temp_links:
                print(f"⏩ Skipping duplicate {url}")
                continue

            temp_links.add(url)

            cat_el = article.find_element(By.CLASS_NAME, "kicker")
            category = cat_el.text.strip()
            print(category)

            # Date
            date_el = article.find_element(By.CLASS_NAME, "timestamp")
            full_date = date_el.text.strip()  # "Monday, 04 Aug 2025"
            date = full_date.split("|")[0].strip()  # "04 Aug 2025"
            date = date.replace("Sept", "Sep")
            try:
                article_date = datetime.strptime(date, "%d %b %Y").date()  # abbreviated
            except ValueError:
                article_date = datetime.strptime(date, "%d %B %Y").date()  # full month

            print(article_date)

            # inside your getArticle loop:
            # if article_date > YESTERDAY:
            #     print("Article is newer than yesterday → skip just this article")
            #     continue  

            # elif article_date < YESTERDAY:
            #     print("Article is older yesterday → stop this keyword")
            #     stop = True
            #     break  

            if article_date not in ALLOWED_DATES:
                print(f"⏩ Skipping article from {article_date} (not in allowed range)")
                if article_date < min(ALLOWED_DATES):
                    stop = True   # too old → stop this keyword
                    break
                else:
                    continue      # too new → just skip

            # normalize once
            allowed_categories_norm = [c.strip().lower() for c in allowed_categories]

            if category.strip().lower() not in allowed_categories_norm:
                print(f"⚠️ Category '{category}' not in filter for {current_source} → skip")
                continue

            print("Opening article in a new tab")
            driver.execute_script("window.open(arguments[0], '_blank');", url)

            # Visit article page
            # print("Navigating to article")
            # driver.get(url)
            time.sleep(3)

            if "chrome://" in driver.current_url:
                print(f"⚠️ Skipping Chrome internal page: {driver.current_url}")
                driver.back()
                continue

            driver.switch_to.window(driver.window_handles[-1])

            wait.until(EC.presence_of_element_located((By.ID, "story-body")))
            time.sleep(2)

            # print("Getting screenshots")
            # article_id = str(uuid.uuid4())[:8]
            # screenshot_paths = scroll_and_capture(driver, article_id, SCREENSHOT_FOLDER)
            # if not screenshot_paths:
            #     print(f"❌ No screenshots for article {url}, skipping PDF and record.")
            #     driver.back()
            #     continue

            # pdf_id = create_pdf(article_id, screenshot_paths, output_folder)
            # if not pdf_id:
            #     print(f"❌ Failed to create PDF for article {url}, skipping.")
            #     driver.back()
            #     continue

            print("Getting article text ")
            paragraphs = driver.find_elements(By.XPATH, '//div[@id="story-body"]//p')
            full_text = " ".join(p.text for p in paragraphs)

            location = ""
            if paragraphs:
                first_para = paragraphs[0].text.strip()
                match = re.match(r'^([A-Z\s\-]+):', first_para)
                if match:
                    location = match.group(1).title().strip()

            country = detect_country_from_text(location, country_map) if location else detect_country_from_text(full_text, country_map)
            print(f"🌏 Detected country: {country}")
            article_date = datetime.strptime(date, "%d %b %Y").date()
            article_date = article_date.date() if hasattr(article_date, "date") else article_date
            # Save data
            # Save data
            row = {
                "Subject": "",
                "Type": "",
                "Category": keyword,
                "Media Source": category,
                "Country": country,
                "Date": article_date,
                "Links": url,
                "Publication": "The Star",
                "Title": title,
                "Article Text": full_text,
                "Status":"1"
            }

            results.append(row)

            # 💾 Save immediately
            try:
                # Define start and end dates
                start_date = (datetime.now() - timedelta(days=5)).date()
                end_date = (datetime.now() - timedelta(days=1)).date()
                valid_dates = {(start_date + timedelta(days=i)) for i in range((end_date - start_date).days + 1)}

                # Only save if date is valid
                if article_date in valid_dates:
                    new_df = pd.DataFrame([row])

                    # Append to temp file
                    if os.path.exists(temp_file):
                        existing_df = pd.read_excel(temp_file)
                        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                    else:
                        combined_df = new_df

                    combined_df.drop_duplicates(subset=["Links"], inplace=True)
                    combined_df.to_excel(temp_file, index=False)

                    # Append to master file too
                    if os.path.exists(master_file):
                        master_df = pd.read_excel(master_file)
                        combined_master = pd.concat([master_df, new_df], ignore_index=True)
                    else:
                        combined_master = new_df

                    combined_master.drop_duplicates(subset=["Links"], inplace=True)
                    combined_master.to_excel(master_file, index=False)

                    # Update global sets
                    master_links.add(url)
                    temp_links.add(url)

                    print(f"✅ Saved article to Excel: {url}")
                else:
                    print(f"⏩ Not saving {url} (outside allowed date range)")

            except Exception as e:
                print(f"❌ Failed to save article {url}: {e}")

        except Exception as e: print("Error processing article:", e) 
        # Ensure we return to search tab if something fails 
        if len(driver.window_handles) > 1: 
            driver.close() 
            driver.switch_to.window(driver.window_handles[0]) 
            continue
    return stop

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

try:
    # Attempt login
    star_login = TheStarGoogleLogin(driver, wait, GOOGLE_EMAIL, GOOGLE_PASSWORD)
    success = star_login.login_with_google()
    
    if success:
        print("Login completed successfully!")
        handle_ads(driver)

        for keyword in all_keywords:
            print(f"Searching: {keyword}")
            results=[]
            try:
                search_url = f"https://www.thestar.com.my/search?query={keyword}"
                driver.get(search_url)
                time.sleep(5)
            except Exception as e:
                print("Browser session lost. Reinitializing driver...")
                driver.quit()
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service)
                driver.set_page_load_timeout(120)
                wait = WebDriverWait(driver, 10)
                driver.get(search_url)
            # Search
            
            # Filter by 'one week' and "newest"
            try:
                filter_week = driver.find_element(By.CSS_SELECTOR, "div.filter_item[data-filter-value='720'] a")
                filter_week.click()
                time.sleep(1)
            except NoSuchElementException as e:
                continue
            orderByFilter()
            # Loop articles
            while True:
                time.sleep(3)
                print("start loop article ")
                stop_searching = getArticle()
                if stop_searching:
                    print("Older article found. Skipping to the next key word")
                    break
            
                try:
                    # Look for the "Next" button
                    next_btn = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="resultdata"]/a')))
                    
                    # Check if button is disabled
                    if 'disabled' in next_btn.get_attribute('class').lower():
                        print("No more pages. Ending loop.")
                        break
                    
                    # Click via JS to avoid interception
                    driver.execute_script("arguments[0].click();", next_btn)
                    print("Clicked next page")
                    
                    # Wait for new results to load
                    time.sleep(3)

                except Exception as e:
                    print("No next button or error during pagination:", e)
                    break         

except KeyboardInterrupt:
    print("\nProcess interrupted by user.")

if os.path.exists(master_file):
    df_master = pd.read_excel(master_file)

df_master = pd.concat([df_master, df_temp], ignore_index=True)
df_master.drop_duplicates(subset=["Links"], keep="first", inplace=True)

df_master.to_excel(master_file, index=False)
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
#             datetime.strptime(row["Date"], "%d %b %Y").strftime("%Y-%m-%d") if row["Date"] else None,             # Date
#             row["Category"],         # Category
#             row["Media Source"],     # Media Source
#             row["Country"],          # Country
#             row["Links"],            # Links
#             row["Publication"],      # Publication
#             row["Title"],            # Title
#             row["Article Text"],     # Article Text
#             row["Subject"],          # Subject
#             row["Status"],           # Status
#             row["Type"],             # Type
#         )
#         for _, row in df_temp.iterrows()
#     ]
#     execute_values(cursor, insert_sql, rows_to_insert)
#     conn.commit()
#     print(f"✅ Inserted {len(rows_to_insert)} rows into PostgreSQL")
# else:
#     print("⚠️ No new rows to insert into PostgreSQL")

#     # ✅ Close DB connection
# cursor.close()
# conn.close()

print("✅ Scraping completed.")
