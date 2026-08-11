import time
import os
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
import dateparser
import random
import logging
import tempfile
from datetime import timedelta
import psycopg2
from psycopg2.extras import execute_values
import undetected_chromedriver as uc

# ---------- CONFIG ----------
categories = [
    "https://www.theedgesingapore.com/flash-categories/1mdb-watch",
    "https://www.theedgesingapore.com/flash-categories/fake-news",
    "https://www.theedgesingapore.com/flash-categories/corruption-probes",
    "https://www.theedgesingapore.com/flash-categories/anti-money-laundering",
    "https://www.theedgesingapore.com/flash-categories/singapore-news"        
]

#conn = psycopg2.connect(host="192.168.1.132", database="adverse_media", user="postgres", password="Verity@456")
#cursor = conn.cursor()

email= "instacheck2020@gmail.com"
password = "instacheck2010@123"
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("The_Edge_SG_scraper")
excel_path = r"/home/khaliq/airflow_project/airflow/output/The Edge Singapore"

os.makedirs(excel_path, exist_ok=True)

WINDOW_SIZE = "1024,900"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36")

# Date range (inclusive)

end_date = (datetime.now() - timedelta(days=1)).date()
start_date = (datetime.now() - timedelta(days=8)).date()
start_date_str = start_date.strftime("%Y-%m-%d")
end_date_str = end_date.strftime("%Y-%m-%d")
temp_file = os.path.join(excel_path, f"{start_date_str}_{end_date_str}_TheEdgeSG.xlsx")
master_file = os.path.join(excel_path, f"master_file_TheEdgeSG.xlsx")
columns = ["Subject", "Type","Media Source", "Country", "Date", "Links", "Publication", "Category", "Title", "Article Text","Status"]

# Keywords used to flag articles (same as you had)
KEYWORDS = [
    'Abuse','Acquitted','Alleged','Allegedly','Animal Cruelty','Blackmail and Threats',
    'Breach','Causing Injury','CBT (Criminal Breach of Trust)','Charge','Charged','Cheating',
    'Civil Suit','Convicted','Corruption','Counterfeited','Crime','Defamation & Insult','Drug',
    'Employment Act','Environmental Offences','Fake','Fined','Fraud','Gambling','Graft','Guilty',
    'Harassment','Harbouring','Illegal Financial Activities','Immigration Offence','Jail','Kidnap',
    'Money Laundering','Murder','Obstructing Officer','Organised Crime','Penal Code','Pollution',
    'Prosecute','Prosecuted','Prostitution','Rape','Remand','Remanded','Robbery','Scam','Sedition',
    'Sexual Offences','Snatch','Stalk','Steal','Sue','Sued','Theft','Traffic Offence','Trafficking',
    'Trespassing','Unlicensed Business','Violence','Wanted Persons','Wildlife Act'
]
# ---------- LOAD EXISTING LINKS ----------

def parse_article_date(date_raw):
    """
    Parse both absolute and relative dates, return a datetime object.
    If parsing fails, returns None.
    """
    if not date_raw:
        return None

    # Use dateparser with relative date support
    parsed = dateparser.parse(
        date_raw,
        settings={
            'PREFER_DATES_FROM': 'past',   # for relative dates like "1 day ago"
            'RELATIVE_BASE': datetime.now(), # base for relative times
            'RETURN_AS_TIMEZONE_AWARE': False
        },
        languages=['en']
    )
    return parsed

def load_existing_links():
    try:
        df_master = pd.read_excel(master_file)
    except FileNotFoundError:
        df_master = pd.DataFrame(columns=columns)
    try:
        df_temp = pd.read_excel(temp_file)
    except FileNotFoundError:
        df_temp = pd.DataFrame(columns=columns)
    
    existing_links = set(df_master['Links']).union(set(df_temp['Links']))
    return df_master, df_temp, existing_links

df_master, df_temp, existing_links = load_existing_links()

def is_captcha_present(driver):
    """
    Best-effort detection of common blocking messages/strings.
    Add more phrases or DOM checks if you see different blocks.
    """
    try:
        page_source = driver.page_source.lower()
    except Exception:
        return False

    checks = [
        "verify you are human",
        "verify you are not a robot",
        "checking your browser",
        "please complete the security check",
        "one more step",
        "are you a robot",
        "press and hold",
        "human verification",
        "please verify",
    ]
    if any(chk in page_source for chk in checks):
        return True

    # small DOM heuristics: presence of common captcha widget text or iframe hints
    try:
        if driver.find_elements(By.XPATH, "//iframe[contains(@src,'recaptcha') or contains(@title,'captcha')]"):
            return True
    except Exception:
        pass

    return False


def simulate_human_interaction(driver):
    """
    Do small randomized scrolls and mouse moves to mimic a human.
    This is non-blocking and wrapped in try/except.
    """
    try:
        scroll_steps = random.randint(2, 6)
        for _ in range(scroll_steps):
            driver.execute_script("window.scrollBy(0, arguments[0]);", random.randint(100, 350))
            time.sleep(random.uniform(0.25, 0.9))

        # small mouse move
        action = ActionChains(driver)
        try:
            action.move_by_offset(random.randint(5, 120), random.randint(5, 120)).perform()
        except Exception:
            # fallback: move to body with offset
            try:
                body = driver.find_element(By.TAG_NAME, "body")
                action.move_to_element_with_offset(body, random.randint(10, 200), random.randint(10, 400)).perform()
            except Exception:
                pass

        time.sleep(random.uniform(0.5, 1.6))
    except Exception:
        # never propagate simulation errors
        pass

# ---------- SELENIUM SETUP ----------
def clear_browser_data(driver):
    """Clear cookies, localStorage, sessionStorage, and cache."""
    try:
        driver.delete_all_cookies()
        driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
    except Exception:
        pass
    try:
        driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
        driver.execute_cdp_cmd("Network.clearBrowserCache", {})
    except Exception:
        pass


def make_driver(headless=False, clear_cache=False):
    # Use a temporary profile to reduce fingerprint tracking
    temp_dir = tempfile.mkdtemp(prefix="uc_profile_")

    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-popup-blocking")
    options.add_argument(f"--window-size={WINDOW_SIZE}")
    options.add_argument("--incognito")  # optional
    options.add_argument(f"user-agent={USER_AGENT}")
    options.add_argument(f"--user-data-dir={temp_dir}")

    if headless:
        options.add_argument("--headless=new")

    # Start undetected Chrome (no version_main needed)
    driver = uc.Chrome(options=options, version_main=143)
    driver.set_page_load_timeout(30)

    # Optionally clear all storage right after launch
    if clear_cache:
        clear_browser_data(driver)

    # Cleanup on exit
    driver._temp_profile = temp_dir
    return driver


def login_to_the_edge_sg(driver, email, password):
    """
    Log in to The Edge Singapore using Google authentication.
    Handles CAPTCHA, Google login, password entry, and optional 'Continue' button.
    """
    login_url = "https://www.theedgesingapore.com/user?destination="
    log.info(f"🌐 Navigating to login page: {login_url}")
    driver.get(login_url)

    # Handle CAPTCHA if detected
    if is_captcha_present(driver):
        log.info(f"⚠️ Possible CAPTCHA detected for {login_url} — verifying...")
        time.sleep(4)

        if not is_captcha_present(driver):
            log.info(f"✅ CAPTCHA auto-bypassed for {login_url}")
        else:
            log.warning(f"🧱 CAPTCHA confirmed for {login_url} — attempting manual interaction")
            simulate_human_interaction(driver)
            time.sleep(random.uniform(2.0, 4.0))

    try:
        # Click "Google" button
        google_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Google')]"))
        )
        google_button.click()
        log.info("➡️ Clicked 'Login with Google' button.")
    except Exception as e:
        log.error("❌ Failed to click Google login button: %s", e)
        driver.save_screenshot("error_google_button.png")
        return False

    # Handle potential popup/tab switch (Google login sometimes opens new window)
    time.sleep(3)
    main_window = driver.current_window_handle
    all_windows = driver.window_handles
    if len(all_windows) > 1:
        for handle in all_windows:
            if handle != main_window:
                driver.switch_to.window(handle)
                log.info("🔄 Switched to Google login popup window.")
                break

    wait = WebDriverWait(driver, 30)

    # Step 1: Email input
    try:
        email_input = wait.until(EC.presence_of_element_located((By.ID, "identifierId")))
        email_input.clear()
        email_input.send_keys(email)
        log.info("✅ Email entered.")
    except Exception as e:
        log.error("❌ Failed to locate or fill email input: %s", e)
        driver.save_screenshot("error_email_input.png")
        return False

    # Step 2: Click "Next" after email
    try:
        next_button = wait.until(EC.element_to_be_clickable((By.ID, "identifierNext")))
        next_button.click()
        log.info("➡️ Clicked email 'Next' button.")
    except Exception as e:
        log.error("❌ Failed to click email Next: %s", e)
        driver.save_screenshot("error_next_click.png")
        return False

    # Step 3: Enter password and click next
    try:
        log.info("🔐 Waiting for password field...")
        password_input = wait.until(
            EC.presence_of_element_located((By.XPATH, "//input[@name='Passwd']"))
        )
        time.sleep(1)
        password_input.clear()
        password_input.send_keys(password)
        log.info("✅ Password entered.")

        password_next = wait.until(EC.element_to_be_clickable((By.ID, "passwordNext")))
        password_next.click()
        log.info("➡️ Clicked password 'Next' button.")
    except Exception as e:
        log.error("❌ Failed to input password: %s", e)
        driver.save_screenshot("error_password_input.png")
        return False

    # Step 4: Optional 'Continue' button
    try:
        continue_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='Continue']]"))
        )
        continue_button.click()
        log.info("➡️ Clicked 'Continue' button.")
        time.sleep(7)
    except TimeoutException:
        log.info("ℹ️ 'Continue' button not found — skipping.")
    except Exception as e:
        log.error("❌ Error while handling 'Continue' button: %s", e)

    # Step 5: Switch back to main site window if popup was used
    try:
        if driver.current_window_handle != main_window:
            driver.switch_to.window(main_window)
            log.info("↩️ Switched back to main site window.")
    except Exception:
        pass

    log.info("🎉 Login process completed successfully.")
    return True

driver = make_driver()
wait = WebDriverWait(driver, 30)
success = login_to_the_edge_sg(driver, email, password)

# ---------- LOOP THROUGH CATEGORIES ----------
for url in categories:
    print(f"\n🔍 Scraping category: {url}")
    driver.get(url)
    time.sleep(5)

    stop_scraping = False
    last_loaded_count = 0

    while not stop_scraping:
        time.sleep(3)
        articles = driver.find_elements(By.CSS_SELECTOR, "div[data-testid='teaser-type-1']")

        for a in articles[last_loaded_count:]:
            try:
                title_el = a.find_element(By.CSS_SELECTOR, "h3 a")
                title = title_el.text.strip()
                link = title_el.get_attribute("href")
            except:
                continue

            try:
                category_el = a.find_element(By.CSS_SELECTOR, "div[data-testid='flash_category']")
                category = category_el.text.strip()
            except:
                category = None

            # Skip duplicates
            if link in existing_links:
                print("Skipping duplicated link")
                continue

            # Extract and parse date
            try:
                meta_el = a.find_element(By.CSS_SELECTOR, ".resizer_see_also_desktop_article_meta")
                meta_el = a.find_element(By.CSS_SELECTOR, ".resizer_see_also_desktop_article_meta")
                meta_text = meta_el.text.strip()  # "by Hugo Miller / Bloomberg • 2 minutes ago"

                # Split by "•" and take the last part
                if "•" in meta_text:
                    date_raw = meta_text.split("•")[-1].strip()  # "2 minutes ago"
                else:
                    date_raw = meta_text.strip()
                print(f"{date_raw}")
                parsed_date = parse_article_date(date_raw)
                if parsed_date:
                    parsed_date = parsed_date.date() 
                if not parsed_date:
                    print(f"⚠️ Could not parse date: {date_raw}, skipping article")
                    continue
            except:
                parsed_date = None

            # Date range check
            if parsed_date is None:
                print(f"⚠️ Could not parse date for article: {title}, skipping...")
                continue  # skip this article
            if parsed_date > end_date:
                print(f"Article too recent, skipping: {title}")
                continue
            elif parsed_date < start_date:
                stop_scraping = True
                print(f"🛑 Reached older article ({parsed_date}) — stopping for {url}")
                break
            else:
                print(f"✅ Article within date range: {title} ({parsed_date})")

            article_text = ""

            if link:
                try:
                    # Open in new window
                    driver.execute_script("window.open(arguments[0]);", link)
                    driver.switch_to.window(driver.window_handles[-1])

                    paragraphs = driver.find_elements(By.CSS_SELECTOR, "p.resizer_article_body")
                    article_text = "\n".join(p.text for p in paragraphs if p.text.strip())
                    print("\n📰 Article content preview:\n", article_text[:400])
                except Exception as e:
                    print(f"⚠️ Error reading article: {e}")
                finally:
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

    # ---------- KEYWORD CHECK ----------
            found_keyword = None
            for keyword in KEYWORDS:
                if keyword.lower() in article_text.lower():
                    found_keyword = keyword
                    break

            if not found_keyword:
                print(f"❌ No keyword found, skipping article: {title}")
                continue  # skip saving
            else:
                print(f"✅ Keyword '{found_keyword}' found, saving article: {title}")

        # Save immediately to temp file
                new_row = {
                    "Subject": "",
                    "Type": "",
                    "Media Source": url.split("/")[-1],
                    "Country": "Singapore",
                    "Date": parsed_date.strftime("%Y-%m-%d"),
                    "Links": link,
                    "Publication": "The Edge Singapore",
                    "Category": found_keyword,
                    "Title": title,
                    "Article Text": article_text,
                    "Status": 1
                }

                df_temp = pd.concat([df_temp, pd.DataFrame([new_row])], ignore_index=True)
                df_temp.to_excel(temp_file, index=False)
                existing_links.add(link)
                print(f"✅ Saved to temp file: {title}")

        last_loaded_count = len(articles)

        # Click Load More button if it exists
        try:
            load_more = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Load more stories')]")))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", load_more)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", load_more)
            print("🖱 Clicked 'Load more'...")

        except (NoSuchElementException, ElementClickInterceptedException, TimeoutException):
            print("🚫 No more 'Load more' button or failed to click.")
            break

driver.quit()

# ---------- UPDATE MASTER FILE ----------
if os.path.exists(master_file):
    df_master = pd.read_excel(master_file)
    combined = pd.concat([df_master, df_temp], ignore_index=True)
    combined.drop_duplicates(subset=["Links"], inplace=True)
    combined.to_excel(master_file, index=False)
else:
    df_temp.to_excel(master_file, index=False)

print(f"✅ Master file updated: {master_file}")

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




