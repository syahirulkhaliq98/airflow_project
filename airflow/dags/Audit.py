from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import time
import psycopg2
from openai import OpenAI
import pandas as pd
from psycopg2.extras import execute_values
import openpyxl
import os

# OpenAI setup
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
# PostgreSQL connection details
DB_CONFIG = {
    "host": "192.168.1.132",
    "database": "adverse_media",
    "user": "postgres",
    "password": "Verity@456"
}

# -------------------------
# Step 1: Filter + deduplicate relevant audit rows
# -------------------------
def filter_and_deduplicate():
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    # Load rows
    cursor.execute("""
        SELECT * FROM ml_expanded_output_table
        WHERE "Status" = 2 AND COALESCE("Audit_Status", '') = ''
    """)
    rows = cursor.fetchall()
    colnames = [desc[0] for desc in cursor.description]
    df = pd.DataFrame(rows, columns=colnames)

    # Filter + dedupe
    df = df[~df['Subject'].astype(str).str.strip().str.lower().eq('no accused found')].copy()
    df_deduped = df.drop_duplicates(subset=["pdf_uuid", "Subject"])
    print(f"✅ Filtered {len(df)} → Deduplicated to {len(df_deduped)} rows.")

    # Drop + recreate working table with same structure
    cursor.execute("DROP TABLE IF EXISTS audit_articles_working")
    cursor.execute("""
        CREATE TABLE audit_articles_working AS
        SELECT * FROM ml_expanded_output_table WHERE 1=0
    """)

    # Insert deduped rows
    if not df_deduped.empty:
        df_deduped_columns = ', '.join([f'"{c}"' for c in df_deduped.columns])
        execute_values(
            cursor,
            f"INSERT INTO audit_articles_working ({df_deduped_columns}) VALUES %s",
            df_deduped.values.tolist()
        )

    conn.commit()
    cursor.close()
    conn.close()



# -------------------------
# Step 2: Classify with OpenAI and update original table
# -------------------------
def classify_audit_status(subject, article_text, category):
    prompt = f"""
You are an audit assistant. Your task is to determine if the subject is correctly identified as being involved in commiting the offence **relevant to the category provided**.

- Focus only on individuals or entities accused, suspected, or responsible for commiting the offence.
- Ignore journalists, reporters, investigators, or authorities unless they are **the ones involved** in commiting the offence.
- The offense must be clearly associated with the category and the offender (subject) **within the context of the provided category** (e.g., fraud in financial news, abuse in legal cases, etc.).

Subject: "{subject}"
Category: "{category}"

Article Text:
\"\"\"{article_text}\"\"\"

If the subject is clearly identified as involved in commiting the offence described in the article and matching the category, respond with:
Approved

If the subject is **not** clearly implicated in commiting the offence relevant to the category, respond with:
KIV

If the subject is labelled as 'Error: Invalid JSON', respond with:
KIV

Respond with only one word: Approved or KIV.
"""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error: {e}")
        return "Error"

def audit_articles_postgres():
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    # Ensure audited_input_table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audited_input_table
        (LIKE ml_expanded_output_table INCLUDING ALL)
    """)
    conn.commit()

    # Fetch filtered + deduplicated working table
    cursor.execute('SELECT "pdf_uuid", "Subject", "Article Text", "Category", "Title" FROM audit_articles_working')
    rows = cursor.fetchall()

    kiv_rows = []  # Collect KIV rows for Excel

    for row in rows:
        pdf_uuid, subject, article_text, category, title = row
        audit_status = classify_audit_status(subject, article_text, category)
        print(f"PDF {pdf_uuid} / Subject='{subject}' => Audit_Status='{audit_status}'")

        if audit_status in ("Approved", "KIV"):
            # ✅ Update Status = 4 in ml_expanded_output_table
            cursor.execute("""
                UPDATE ml_expanded_output_table
                SET "Status" = 4
                WHERE "pdf_uuid" = %s AND "Subject" = %s
            """, (pdf_uuid, subject))

            # ✅ Insert or update in audited_input_table with classification
            cursor.execute(f"""
                INSERT INTO audited_input_table (
                    "pdf_uuid", "Subject", "Date", "Category", "Media Source", "Country",
                    "Links", "Publication", "Title", "Article Text", "Status", "Type", "Audit_Status"
                )
                SELECT
                    "pdf_uuid", "Subject", "Date", "Category", "Media Source", "Country",
                    "Links", "Publication", "Title", "Article Text", "Status", "Type", %s
                FROM ml_expanded_output_table
                WHERE "pdf_uuid" = %s AND "Subject" = %s
                ON CONFLICT ("pdf_uuid", "Subject") DO UPDATE
                SET
                    "Audit_Status" = EXCLUDED."Audit_Status",
                    "Status" = 4,
                    "Article Text" = EXCLUDED."Article Text",
                    "Category" = EXCLUDED."Category",
                    "Title" = EXCLUDED."Title";
            """, (audit_status, pdf_uuid, subject))

            # ✅ Then update the classification in audited_input_table
            cursor.execute("""
                UPDATE audited_input_table
                SET "Audit_Status" = %s, "Status" = 4
                WHERE "pdf_uuid" = %s AND "Subject" = %s
            """, (audit_status, pdf_uuid, subject))

            # ✅ If KIV, collect row for Excel
            if audit_status == "KIV":
                cursor.execute("""
                    SELECT * FROM audited_input_table
                    WHERE "pdf_uuid" = %s AND "Subject" = %s
                """, (pdf_uuid, subject))
                kiv_row = cursor.fetchone()
                colnames = [desc[0] for desc in cursor.description]
                kiv_rows.append(dict(zip(colnames, kiv_row)))

        else:
            # Error case: keep original status = 2 in ml_expanded_output_table
            cursor.execute("""
                UPDATE ml_expanded_output_table
                SET "Status" = 2
                WHERE "pdf_uuid" = %s AND "Subject" = %s
            """, (pdf_uuid, subject))

        conn.commit()
        time.sleep(1)

    # ✅ Export all KIV rows to Excel
    if kiv_rows:
        df_kiv_new = pd.DataFrame(kiv_rows)
        kiv_dir = "/home/khaliq/airflow_project/airflow/output/KIV_data"
        os.makedirs(kiv_dir, exist_ok=True)

    # Generate filename based on today's date
        kiv_filename = f"KIV_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
        kiv_filepath = os.path.join(kiv_dir, kiv_filename)

        if os.path.exists(kiv_filepath):
            # ✅ File exists → Append new data, avoiding duplicate pdf_uuid+Subject
            df_existing = pd.read_excel(kiv_filepath)

            # Combine and drop duplicates by key columns
            df_combined = pd.concat([df_existing, df_kiv_new], ignore_index=True)
            if "pdf_uuid" in df_combined.columns and "Subject" in df_combined.columns:
                df_combined.drop_duplicates(subset=["pdf_uuid", "Subject"], inplace=True)

            df_combined.to_excel(kiv_filepath, index=False)
            print(f"✅ Appended {len(df_kiv_new)} new KIV rows to existing file: {kiv_filepath}")

        else:
            # ✅ File doesn't exist → Create new file
            df_kiv_new.to_excel(kiv_filepath, index=False)
            print(f"✅ Created new KIV Excel file: {kiv_filepath} with {len(df_kiv_new)} rows")

    cursor.close()
    conn.close()
    print("✅ Classification complete: Approved & KIV stored in audited_input_table, status updated in both tables.")


# -------------------------
# DAG setup
# -------------------------
default_args = {
    'owner': 'airflow',
    'start_date': datetime(2025, 7, 7),
    'retries': 0,
}

with DAG(
    dag_id='audit_classification_postgres_dag',
    default_args=default_args,
    schedule_interval='*/10 * * * *',
    catchup=False,
    tags=['audit', 'postgres', 'openai'],
) as dag:

    step1_filter_dedupe = PythonOperator(
        task_id='filter_and_deduplicate',
        python_callable=filter_and_deduplicate
    )

    step2_audit = PythonOperator(
        task_id='classify_and_update_audit_status',
        python_callable=audit_articles_postgres
    )

    step1_filter_dedupe >> step2_audit
