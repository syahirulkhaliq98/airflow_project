import pandas as pd
import os, time, uuid, re, json, io, random
import fitz  
from PIL import Image
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from datetime import timedelta
from urllib.parse import urlparse
import psycopg2
from fpdf import FPDF
from PIL import Image
from io import BytesIO
import undetected_chromedriver as uc
 
# --- Config ---
BASE_DIR = Path(__file__).resolve().parents[1]
RESOURCES_DIR = BASE_DIR / "dags" / "resources"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
OUTPUT_DIR = BASE_DIR / "output"

pdf_path = str(Path(os.getenv("PDF_PATH", SCREENSHOTS_DIR / "The Edge")))
category_path = str(Path(os.getenv("CATEGORY_PATH", RESOURCES_DIR / "categories.json")))
keyword_path = str(Path(os.getenv("KEYWORD_PATH", RESOURCES_DIR / "keywords.json")))
countries_path = str(Path(os.getenv("COUNTRIES_PATH", RESOURCES_DIR / "countries.json")))
excel_path = str(Path(os.getenv("OUTPUT_PATH", OUTPUT_DIR / "The Edge")))
url = "https://theedgemalaysia.com/"
# conn = psycopg2.connect(host="localhost", database="adverse_media", user="postgres", password="Verity@456")
# cursor = conn.cursor()
os.makedirs(pdf_path, exist_ok=True)
os.makedirs(excel_path, exist_ok=True)
# os.makedirs(PDF_FOLDER, exist_ok=True)


# Load categories
with open(category_path, "r", encoding="utf-8") as f:
    publication_data = json.load(f)

publication_list = publication_data["publication"][0]
source_category_map = {
    entry["source"]: entry["category"]
    for entry in publication_list.values()
}
domain = urlparse(url).netloc
current_source = "theedgemalaysia" if "theedgemalaysia.com" in domain else None
allowed_categories = source_category_map.get(current_source, [])

#Keywords
with open(keyword_path, "r", encoding="utf-8") as f:
    data = json.load(f)

languages = data["language"][0]
english_keywords = languages.get("English", {}).get("keywords", [])
all_keywords = english_keywords

# --- Load countries and build token map ---
with open(countries_path, "r", encoding="utf-8") as f:
    countries_data = json.load(f)

token_to_country = {}
for country, tokens in countries_data.items():
    for t in tokens:
        token_to_country[str(t).upper()] = country

import re

def detect_country(text: str) -> str:
    """Detect country only from the leading article location pattern.

    Expected patterns (examples):
    - "NEW DELHI (July 31): ..."
    - "YANGON, Myanmar (July 31): ..."
    - "SINGAPORE (Aug 14): ..."

    If no match is found in the leading location (before '(' or ':'), return an empty string.
    """
    if not text:
        return ""

    # Extract leading location (text before first '(' or ':')
    leading = re.split(r"\(|:", text, 1)[0].strip().strip('"\'')
    if not leading:
        return ""

    # Split on comma to handle "CITY, Country" formats
    parts = [p.strip() for p in leading.split(",") if p.strip()]

    # Prefer the last part (likely the country) then the first (city)
    candidates = []
    if len(parts) > 1:
        candidates.append(parts[-1])
        candidates.append(parts[0])
    else:
        candidates.append(parts[0])

    for cand in candidates:
        c_up = cand.upper()
        # exact country name match
        for country in countries_data:
            if c_up == country.upper():
                return country
        # token map match (city or token mapped to country)
        if c_up in token_to_country:
            return token_to_country[c_up]

    # No match from the leading pattern -> return empty
    return ""
def close_mk_news_popup(driver):
    try:
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located(
                (By.XPATH, "//h1[contains(text(), \"Catch up with Malaysiakini's latest news!\")]")
            )
        )
        print("⚠️ Malaysiakini news popup detected.")
 
        no_thanks = driver.find_element(
            By.XPATH, "//a[contains(text(), 'No Thanks')]"
        )
        no_thanks.click()
        print("✅ Closed Malaysiakini popup.")
        time.sleep(1)
 
    except Exception:
        print("✅ No popup detected.")

def is_captcha_present(driver):
    page_source = driver.page_source.lower()
    return "verify you are human" in page_source or "checking your browser" in page_source
 
def simulate_human_interaction(driver):
    scroll_steps = random.randint(2, 6)
    for _ in range(scroll_steps):
        driver.execute_script("window.scrollBy(0, arguments[0]);", random.randint(100, 300))
        time.sleep(random.uniform(0.2, 0.6))
    try:
        action = webdriver.ActionChains(driver)
        action.move_by_offset(random.randint(10, 50), random.randint(10, 50)).perform()
    except:
        pass
    time.sleep(random.uniform(0.2, 0.5))
 
# === Malaysiakini Google Login (Code 2) ===
# class MKiniGoogleLogin:
#     def __init__(self, driver, wait, email, password):
#         self.driver = driver
#         self.wait = wait
#         self.email = email
#         self.password = password
 
#     def login_with_google(self):
#         """
#         Login to Malaysiakini using Google authentication
#         """
#         try:
#             print("Opening Malaysiakini login page...")
#             self.driver.get("https://membership.malaysiakini.com/auth/login?lang=en&redirectUrl=https://m.malaysiakini.com/")
           
#             google_login_button = self.wait.until(
#                 EC.element_to_be_clickable((By.CSS_SELECTOR, "a.button-large-icon[href*='auth/google']"))
#             )
#             google_login_button.click()
#             print("✅ Clicked Google login button")
 
#             # Switch to Google login screen
#             try:
#                 email_input = self.wait.until(EC.presence_of_element_located((By.ID, "identifierId")))
#                 email_input.clear()
#                 email_input.send_keys(self.email)
#                 print("✅ Email entered")
#             except Exception as e:
#                 print("❌ Failed to locate or fill email input.", e)
#                 self.driver.save_screenshot("error_email_input.png")
#                 return False
 
#             next_button = self.wait.until(EC.element_to_be_clickable((By.ID, "identifierNext")))
#             next_button.click()
#             print("➡️ Clicked email Next")
 
#             # Wait for password field and enter password
#             try:
#                 print("🔐 Waiting for password field...")
#                 password_input = self.wait.until(
#                     EC.presence_of_element_located((By.XPATH, "//input[@name='Passwd']"))
#                 )
#                 time.sleep(1)  # slight delay to mimic human behavior
#                 password_input.clear()
#                 password_input.send_keys(self.password)
#                 print("✅ Password entered.")
 
#                 # Click "Next" button
#                 password_next = self.wait.until(
#                     EC.element_to_be_clickable((By.ID, "passwordNext"))
#                 )
#                 password_next.click()
#             except Exception as e:
#                 print("❌ Failed to input password.")
#                 print("Exception:", type(e).__name__, "-", str(e))
#                 self.driver.save_screenshot("error_password_input.png")
#                 return False
 
#             # password_next = self.wait.until(EC.element_to_be_clickable((By.ID, "passwordNext")))
#             # password_next.click()
#             # print("➡️ Clicked password Next")
 
#             time.sleep(30)
 
#             # # Attempt to handle post-login modal (if any)
#             # try:
#             #     self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "modal-dialog")))
#             #     continue_button = self.wait.until(EC.element_to_be_clickable((By.ID, "logout")))
#             #     continue_button.click()
#             #     print("✅ Clicked continue/logout modal")
#             # except Exception as e:
#             #     print("ℹ️ No modal detected or skipped:", e)
 
#             # Switch back to main window
#             if len(self.driver.window_handles) > 1:
#                 self.driver.switch_to.window(self.driver.window_handles[0])
#                 print("🔄 Switched back to main tab")
 
#             print("✅ Login process completed (no verification)")
#             return True
 
#         except Exception as e:
#             print(f"❌ Login failed: {e}")
#             self.driver.save_screenshot("mkini_login_error.png")
#             return False
 
#             # Navigate to homepage after login
#             # self.driver.get("https://m.malaysiakini.com/")
#             # time.sleep(2)
 
#             # try:
#             #     # Step 1: Click hamburger menu (SVG 3-line icon)
#             #     print("🔍 Looking for hamburger menu...")
#             #     hamburger_button = wait.until(
#             #         EC.element_to_be_clickable((By.XPATH, "//button[.//svg[contains(@class, 'h-6') and contains(@class, 'w-6')]]"))
#             #     )
#             #     hamburger_button.click()
 
#             #     print("🍔 Clicked hamburger menu.")
 
#             #     # Step 2: Wait for 'Sign Out' link to appear
#             #     signout_link = self.wait.until(
#             #         EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'logout')]"))
#             #     )
#             #     print("✅ Login successful — Sign Out link detected.")
#             #     return True
 
#             # except Exception as e:
#             #     print("❌ Login verification failed — could not find Sign Out link.")
#             #     self.driver.save_screenshot("login_verification_failed.png")
#             #     return False
 
#         # except Exception as e:
#         #     print(f"❌ Google login failed: {e}")
#         #     return False
 
# === Main Article Loop ===

today = datetime.today()
end_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")

print("Start_date =", start_date)
print("End_date =", end_date)

# === File Paths ===
master_file = os.path.join(excel_path, "Master_TheEdge.xlsx")
temp_file = EXCEL_FILE = os.path.join(excel_path, f"{start_date}_{end_date}_TheEdge.xlsx")

columns = [
    "Subject", "Type", "Category", "Media Source", "Country", "Date",
    "Links", "Publication", "Title", "Article Text", "Status"
]

# === Load Existing Master Data ===
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

scraped_rows = []

def run_article_scraper(driver, wait):
    global df_master, df_temp, master_links, temp_links, scraped_rows

    try:
        for keyword in all_keywords:
            print(f"🔍 Searching for {keyword} between {start_date} and {end_date}")
            search_url = f"https://theedgemalaysia.com/news-search-results?keywords={keyword}&from={start_date}&to={end_date}&language=english&offset=0"
            driver.get(search_url)

            try:
                wait.until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.NewsList_newsListItemWrap__XovMP"))
                )

                main_tab = driver.current_window_handle
                article_blocks = driver.find_elements(By.CSS_SELECTOR, "div.NewsList_newsListItemWrap__XovMP")
                num_articles = len(article_blocks)

                if not article_blocks:
                    print(f"ℹ️ No results found for keyword: {keyword}")
                    continue

                print(f"📰 Found {num_articles} articles for keyword '{keyword}'")

                # === Loop through each article block ===
                for i in range(num_articles):
                    try:
                        # Re-fetch each loop to avoid stale elements
                        article_blocks = driver.find_elements(By.CSS_SELECTOR, "div.NewsList_newsListItemWrap__XovMP")
                        if i >= len(article_blocks):
                            break
                        block = article_blocks[i]

                        # ===== Title =====
                        try:
                            title = block.find_element(By.CSS_SELECTOR, "span.NewsList_newsListItemHead__dg7eK").text.strip()
                        except:
                            print("Title not found")
                            title = ""

                        # ===== Date =====
                        try:
                            date_raw = block.find_element(By.CSS_SELECTOR, ".NewsList_infoNewsListSub__Ui2_Z span").text.strip()
                            try:
                                date = datetime.strptime(date_raw.split(",")[0].strip(), "%d %b %Y").strftime("%Y-%m-%d")
                            except ValueError:
                                date = date_raw
                        except:
                            print("Date not found")
                            date = ""

                        # ===== URL =====
                        try:
                            href_el = block.find_element(By.CSS_SELECTOR, "a[target='_blank']")
                            href = href_el.get_attribute("href")
                            if not href:
                                print("Empty href")
                                continue
                            full_url = href if href.startswith("http") else f"https://theedgemalaysia.com{href}"

                            if full_url in master_links or full_url in temp_links:
                                print(f"⏭️ Skipping duplicate before opening: {full_url}")
                                continue
                        except:
                            print("URL not found")
                            continue

                        # ===== Open Article Tab =====
                        try:
                            existing_tabs = set(driver.window_handles)
                            driver.execute_script("window.open(arguments[0]);", full_url)
                            WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > len(existing_tabs))
                            new_tab = list(set(driver.window_handles) - existing_tabs)[0]
                            driver.switch_to.window(new_tab)
                            driver.set_page_load_timeout(60)
                        except Exception as e:
                            print(f"❌ Failed to open article tab: {e}")
                            continue

                        # ===== Scrape Article =====
                        try:
                            WebDriverWait(driver, 25).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, "div.newsTextDataWrapInner"))
                            )

                            # --- Category check ---
                            category_buttons = driver.find_elements(By.CSS_SELECTOR, "div.news-detail_newsdetailsButtonsWrap__gXx8s span")
                            category_list = [c.text.strip() for c in category_buttons if c.text.strip()]
                            valid_categories = [c for c in category_list if c in allowed_categories]
                            category = valid_categories[0] if valid_categories else ""

                            print(f"Category found: {category_list} | Allowed: {valid_categories} | Final: {category}")

                            if not category:
                                print(f"❌ No allowed category, skipping '{title}'")
                                driver.close()
                                # Safely return to main tab
                                if main_tab in driver.window_handles:
                                    driver.switch_to.window(main_tab)
                                else:
                                    driver.switch_to.window(driver.window_handles[0])
                                continue

                            # --- Article text extraction ---
                            paragraphs = driver.find_elements(By.CSS_SELECTOR, "div.newsTextDataWrapInner p")
                            article = "\n\n".join([p.text.strip() for p in paragraphs if p.text.strip()])
                            print("✅ Captured Article Text")

                            # --- Save row ---
                            # Detect country from the article leading pattern only
                            country = detect_country(article or "")
                            row = {
                                "Subject": "",
                                "Type": "",
                                "Category": keyword,
                                "Media Source": "News",
                                "Country": country,
                                "Date": date,
                                "Links": full_url,
                                "Publication": "The Edge",
                                "Title": title,
                                "Article Text": article,
                                "Status": "1"
                            }

                            try:
                                df_temp = pd.concat([df_temp, pd.DataFrame([row])], ignore_index=True)
                                df_temp.to_excel(temp_file, index=False)
                                temp_links.add(full_url)
                                scraped_rows.append(row)
                                print(f"💾 Saved to daily file: {title[:60]}")
                            except Exception as e:
                                print(f"⚠️ Could not save to daily Excel: {e}")

                            print(f"✅ Scraped: {title[:60]}")

                        except Exception as e:
                            print(f"⚠️ Error scraping article: {e}")

                        finally:
                            # ✅ Close only the article tab if it's still open
                            try:
                                if len(driver.window_handles) > 1:
                                    current_tab = driver.current_window_handle
                                    if current_tab != main_tab:
                                        driver.close()
                            except:
                                pass

                            # ✅ Safely return to the main tab
                            try:
                                if main_tab in driver.window_handles:
                                    driver.switch_to.window(main_tab)
                                else:
                                    driver.switch_to.window(driver.window_handles[0])
                            except Exception as e:
                                print(f"⚠️ Failed to return to main tab: {e}")

                    except Exception as e:
                        print(f"⚠️ Error on article {i}: {e}")
                        try:
                            if main_tab in driver.window_handles:
                                driver.switch_to.window(main_tab)
                            else:
                                driver.switch_to.window(driver.window_handles[0])
                        except:
                            pass
                        continue

            except Exception as e:
                print(f"⚠️ Error extracting for {keyword}: {e}")
                continue

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        driver.quit()

    # === Once all scraping done ===
    if not df_temp.empty:
        print(f"📦 Preparing to merge {len(df_temp)} new rows into master file...")
        try:
            df_master = pd.concat([df_master, df_temp], ignore_index=True)
            df_master.drop_duplicates(subset=["Links"], inplace=True)
            df_master.to_excel(master_file, index=False)
            print(f"💾 Master file updated with {len(df_temp)} new entries.")
        except Exception as e:
            print(f"⚠️ Could not update master file: {e}")



 
# === Entry Point ===
if __name__ == "__main__":
   
    chrome_options = Options()
    chrome_options.add_argument("--disable-features=ChromeSignin,AccountConsistency,UnifiedConsent")
    chrome_options.add_argument("--disable-sync")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-features=PreloadMediaEngagementData,MediaEngagementBypassAutoplayPolicies")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-features=SigninInterception")
    chrome_options.add_argument("--disable-features=ChromeWhatsNewUI,ChromeSigninIntercept")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--ignore-ssl-errors=yes")
    chrome_options.add_argument("--window-size=1920,3000")
 
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    wait = WebDriverWait(driver, 10)
 
    try:
        run_article_scraper(driver, wait) 
    except KeyboardInterrupt:
        print("\n⛔ Interrupted by user.")
 
    print(f"✅ All done!")
    driver.quit()

 