import time
import os
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import execute_values
import dateparser
import uuid

# ---------- CONFIG ----------
categories = [
    "https://www.straitstimes.com/singapore/politics",
    "https://www.straitstimes.com/singapore/courts-crime"
]

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "output"
excel_path = str(Path(os.getenv("OUTPUT_PATH", OUTPUT_DIR / "The Straits Times")))
#conn = psycopg2.connect(host="192.168.1.132", database="adverse_media", user="postgres", password="Verity@456")
#cursor = conn.cursor()
WINDOW_SIZE = "1024,900"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36")

os.makedirs(excel_path, exist_ok=True)

# Date range (inclusive)
start_date = (datetime.now() - timedelta(days=3)).date()
end_date = (datetime.now() - timedelta(days=1)).date()
start_date_str = start_date.strftime("%Y-%m-%d")
end_date_str = end_date.strftime("%Y-%m-%d")
temp_file = os.path.join(excel_path,f"{start_date_str}_{end_date_str}_The_Straits_Times.xlsx")
master_file = os.path.join(excel_path,"Master_File_The_Straits_Times.xlsx")

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

# ---------- SELENIUM SETUP ----------
options = Options()
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--start-maximized")
options.add_argument("--disable-notifications")
options.add_argument("--ignore-certificate-errors")
options.add_argument("--disable-popup-blocking")
options.add_argument(f"--window-size={WINDOW_SIZE}")
options.add_argument("--incognito")

options.binary_location = "/usr/bin/google-chrome"

# Only needed if chromedriver is not in PATH
driver = webdriver.Chrome(
    service=Service("/usr/local/bin/chromedriver"),
    options=options
)

# ---------- LOOP THROUGH CATEGORIES ----------
for url in categories:
    print(f"\n🔍 Scraping category: {url}")
    driver.get(url)
    time.sleep(5)

    stop_scraping = False
    last_loaded_count = 0

    while not stop_scraping:
        time.sleep(3)
        articles = driver.find_elements(By.CSS_SELECTOR, "a[data-testid='custom-link']")

        for a in articles[last_loaded_count:]:
            try:
                title_tag = a.find_element(By.CSS_SELECTOR, "h4[data-testid='heading-test-id']")
                title = title_tag.text.strip()
            except:
                continue

            link = a.get_attribute("href")
            if not link:
                continue
            if link.startswith("/"):
                link = "https://www.straitstimes.com" + link            

            # Extract and parse date
            try:
                date_text = a.find_element(By.CSS_SELECTOR, "p[data-testid='paragraph-test-id']").text.strip()
                parsed_date = dateparser.parse(date_text, settings={'PREFER_DATES_FROM': 'past','RELATIVE_BASE':datetime.now()})
            except:
                continue

            if not parsed_date:
                continue

            article_date = parsed_date.date()

            # Date range check
            if article_date > end_date:
                print(f"Article too recent, skipping: {title}")
                continue
            elif article_date < start_date:
                stop_scraping = True
                print(f"🛑 Reached older article ({parsed_date.date()}) — stopping for {url}")
                break
            else:
                print(f"✅ Article within date range: {title} ({parsed_date.date()})")

            if link in existing_links:
                print("Skipping duplicated link")
                continue

            article_text = ""

            if link:
                try:
                    # Open in new window
                    driver.execute_script("window.open(arguments[0]);", link)
                    driver.switch_to.window(driver.window_handles[-1])

                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="article-paragraph-annotation-test-id"]'))
                    )

                    paragraphs = driver.find_elements(By.CSS_SELECTOR, '[data-testid="article-paragraph-annotation-test-id"]')
                    article_text = "\n".join([p.text.strip() for p in paragraphs if p.text.strip()])
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
                    "Date": article_date.strftime("%Y-%m-%d"),
                    "Links": link,
                    "Publication": "The Straits Times Singapore",
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
            load_more = driver.find_element(By.CSS_SELECTOR, "button[aria-label='button for Load more']")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", load_more)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", load_more)
            print("🖱 Clicked 'Load more'...")

            if "onboarding" in driver.current_url:
                print("⚠ Redirected to onboarding page! Going back...")
                driver.back()
                time.sleep(3)

        except (NoSuchElementException, ElementClickInterceptedException):
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

# ✅ Insert df_temp into PostgreSQL
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



