from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import uuid
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
import threading
import google.generativeai as genai
import json
import time
import os
import psycopg2
import requests

# DAG defaults
default_args = {
    'owner': 'airflow',
    'start_date': datetime(2024, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'gemini_etl',
    default_args=default_args,
    description='ETL using Gemini',
    schedule_interval='*/5 * * * *',  # every 10 minutes
    catchup=False,
)

# Global
MAX_RETRIES = 5
RETRY_WAIT_BASE = 30
GEMINI_KEYS = {
    'bot1': os.getenv("GEMINI_API_KEY_1"),
    'bot2': os.getenv("GEMINI_API_KEY_2"),
    'bot3': os.getenv("GEMINI_API_KEY_3"),
}
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GENERIC_TERMS = {
    "husband", "wife", "man", "woman", "child", "suspect", "suspects", 
    "police", "officer", "drug dealer", "businessman", "driver", "worker",
    "individual", "employee", "foreigner", "agent", "mother", "father"
}

def get_cursor():
    conn = psycopg2.connect(host="192.168.1.132", database="adverse_media", user="postgres", password="Verity@456")
    cursor = conn.cursor()
    return conn, cursor

def safe_parse_first_json(text):
    text = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    match = re.search(r'\{.*?\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception as e:
            return {"subject": f"Error: {e}"}
    return {"subject": "Error: Invalid JSON"}

def clean_subject_names(subject_json_str):
    try:
        data = json.loads(subject_json_str)
        names = [name.strip() for name in data.get("subject", "").split(",") if name.strip()]
        cleaned = [n for n in names if n.lower() not in GENERIC_TERMS]
        return {"subject": ", ".join(cleaned)} if cleaned else {"subject": "No accused found"}
    except Exception:
        return {"subject": "No accused found"}
    
def deepseek_generate(prompt):
    response = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0
        },
        timeout=60
    )
    return response.json()["choices"][0]["message"]["content"]


# Task 1: Fetch unprocessed rows
def fetch_data():
    conn, cursor = get_cursor()
    
    # Step 1: Update Status = 1 only for rows where Status is NULL
    cursor.execute("""
        UPDATE raw_input_table
        SET "Status" = 1
        WHERE "Status" IS NULL
    """)
    updated_count = cursor.rowcount
    print(f"✅ Updated Status=1 for {updated_count} rows")
    
    # Step 2: Fetch rows with empty Audit_Status
    cursor.execute("""
        SELECT * FROM raw_input_table
        WHERE "Audit_Status" IS NULL
    """)
    rows = cursor.fetchall()
    print(f"✅ Fetched {len(rows)} unprocessed records")
    
    cursor.close()
    conn.close()
    
    return rows

# MLBot process
def mlbot_process(bot_name, column_name, **kwargs):
    conn, cursor = get_cursor()

    # Step 1: Claim a row atomically
    cursor.execute(f"""
        UPDATE raw_input_table
        SET "Status" = 2
        WHERE ctid = (
            SELECT ctid FROM raw_input_table
            WHERE "Status" = 1 OR "Status" = -1
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING *;
    """)
    row = cursor.fetchone()
    if not row:
        print(f"[{bot_name}] No rows available.")
        conn.commit(); cursor.close(); conn.close()
        return

    colnames = [desc[0] for desc in cursor.description]
    row_dict = dict(zip(colnames, row))
    pdf_uuid_val = row_dict["pdf_uuid"]
    text = row_dict.get(column_name, "")
    category = row_dict.get("Category", "")

    print(f"[{bot_name}] Processing row with pdf_uuid={pdf_uuid_val}")

    # Step 2: Send to Gemini
    genai.configure(api_key=GEMINI_KEYS[bot_name])
    model = genai.GenerativeModel("gemini-2.5-flash")
    retries, subject, status = 0, "", -1
    quota_error = False

    try:
        prompt = f""" 
From the given article text and category context, identify and extract the **full names** of all individuals or companies directly involved in **wrongdoing or criminal activity** based on the provided category. 
- Only include **those responsible or suspected of wrongdoing** (e.g., abuse, corruption, theft, fraud, etc.). 
- **Exclude journalists, investigators, politicial parties or authorities** (e.g., police, MACC officers) unless they are the ones accused. 
- **Do not include vague or generic references** such as "husband", "wife", "a man", "the suspect", "police", "drug dealer", "businessman", or similar non-identifiable labels. 
- Only include **clearly identifiable full names** (e.g., "John Tan Wei Ming", "ABC Holdings Sdn Bhd"). 
- Ensure full names are captured; **titles alone like "Tan Sri" or "Datuk" without full names are insufficient**.
- If no accused parties are mentioned, respond only with "No accused found". 

**Category:** "{category}" 

Return the answer strictly as JSON in this format: 
{{"subject": "Name1, Name2, Name3"}} — all names in a single string, comma-separated. 

Do not include any explanation or commentary.
Return only valid JSON. Do not include any other text. 

Article: \"\"\"{text}\"\"\" 
"""
        response = model.generate_content(prompt)
        # 🧩 Handle prohibited content — Gemini sometimes blocks due to sensitive topics
        if hasattr(response, "prompt_feedback") and response.prompt_feedback:
            feedback = response.prompt_feedback
            if getattr(feedback, "block_reason", "") == "PROHIBITED_CONTENT":
                print(f"[{bot_name}] ⚠️ Gemini blocked content (PROHIBITED_CONTENT) — defaulting to 'No accused found'")
                subject = "No accused found"
                status = 3
            else:
                parsed = safe_parse_first_json(response.text.strip())
                subject_raw = parsed.get("subject", "")
                if subject_raw.startswith("Error: Invalid JSON"):
                    print(f"[{bot_name}] ⚠️ Invalid JSON from Gemini — falling back to DeepSeek")

                    deepseek_resp = deepseek_generate(prompt)
                    print(f"[{bot_name}] DeepSeek raw response: {deepseek_resp}")

                    parsed = safe_parse_first_json(deepseek_resp)
                    subject_raw = parsed.get("subject", "")
                cleaned = clean_subject_names(json.dumps({"subject": subject_raw}))
                subject = cleaned.get("subject", "")
                status = 3
        else:
            parsed = safe_parse_first_json(response.text.strip())
            subject_raw = parsed.get("subject", "")
            cleaned = clean_subject_names(json.dumps({"subject": subject_raw}))
            subject = cleaned.get("subject", "")
            status = 3

    except Exception as e:
        error_msg = str(e)
        print(f"[{bot_name}] ❌ Error: {error_msg}")
        # 🧠 Graceful fallback if prohibited content triggered from exception message
        if "PROHIBITED_CONTENT" in error_msg or "blocked prompt" in error_msg.lower():
            print(f"[{bot_name}] ⚠️ Blocked prompt detected — setting subject='No accused found'")
            subject = "No accused found"
            status = 3
        else:
            subject = f"Error: {error_msg}"
            status = -1
            if "429" in error_msg or "quota" in error_msg.lower() or "rate" in error_msg.lower():
                quota_error = True

    # Step 3: Handle DB updates depending on result
    if quota_error:
        print(f"[{bot_name}] ⚠️ Quota exceeded — reverting changes for pdf_uuid={pdf_uuid_val}")

        # Revert raw_input_table status
        cursor.execute("""
            UPDATE raw_input_table
            SET "Status" = 1
            WHERE "pdf_uuid" = %s
        """, (pdf_uuid_val,))

        # Ensure any previous partial insert is deleted
        cursor.execute("""
            DELETE FROM ml_output_table
            WHERE "pdf_uuid" = %s
        """, (pdf_uuid_val,))

    else:
        # Step 3a: Update status in raw_input_table
        cursor.execute("""
            UPDATE raw_input_table
            SET "Status" = %s
            WHERE "pdf_uuid" = %s
        """, (status, pdf_uuid_val))

        # Step 3b: Insert into ml_output_table
        row_dict["Subject"] = subject
        row_dict.pop("created_dt", None)
        cols = ', '.join(f'"{c}"' for c in row_dict.keys())
        vals = ', '.join(['%s'] * len(row_dict))
        cursor.execute(f"""
            INSERT INTO ml_output_table ({cols}) VALUES ({vals})
        """, list(row_dict.values()))

    conn.commit()
    cursor.close(); conn.close()

    if quota_error:
        print(f"[{bot_name}] 🔁 Row reset for reprocessing (pdf_uuid={pdf_uuid_val})")
    else:
        print(f"[{bot_name}] ✅ Finished row {pdf_uuid_val}")

def explode_subject_rows():
    conn, cursor = get_cursor()
    cursor.execute("""SELECT * FROM ml_output_table""")
    rows = cursor.fetchall()
    colnames = [desc[0] for desc in cursor.description]

    expanded = []
    for row in rows:
        row_dict = dict(zip(colnames, row))
        subjects = [s.strip() for s in str(row_dict["Subject"]).split(",") if s.strip()]
        for s in subjects:
            if s.lower() == "no accused found":
                continue
            new_row = row_dict.copy()
            new_row["Subject"] = s
            expanded.append(new_row)

    if expanded:
        print(f"✅ Preparing to upsert {len(expanded)} rows into ml_expanded_output_table")

        for row in expanded:
            cols = ', '.join(f'"{c}"' for c in row.keys())
            vals = ', '.join(['%s'] * len(row))
            updates = ', '.join(
                [f'"{c}" = EXCLUDED."{c}"' for c in row.keys() if c not in ["pdf_uuid", "Subject", "Status"]]
            )

            # 🔹 Upsert logic: only update if not already approved/audited (Status != 4)
            cursor.execute(f"""
                INSERT INTO ml_expanded_output_table ({cols}) VALUES ({vals})
                ON CONFLICT ("pdf_uuid", "Subject")
                DO UPDATE SET {updates}
                WHERE ml_expanded_output_table."Status" != 4
            """, list(row.values()))

        conn.commit()
        print(f"✅ Upsert complete — audited rows preserved, {len(expanded)} processed.")
    else:
        print("⚠️ No valid subject rows to expand.")

    cursor.close()
    conn.close()


# Tasks
# fetch_task = PythonOperator(task_id='fetch_data', python_callable=fetch_data, do_xcom_push=False, dag=dag)

mlbot1_task = PythonOperator(
    task_id='mlbot1',
    python_callable=mlbot_process,
    op_kwargs={'bot_name': 'bot1', 'column_name': 'Article Text'},
    dag=dag,
)
mlbot2_task = PythonOperator(
    task_id='mlbot2',
    python_callable=mlbot_process,
    op_kwargs={'bot_name': 'bot2', 'column_name': 'Article Text'},
    dag=dag,
)
mlbot3_task = PythonOperator(
    task_id='mlbot3',
    python_callable=mlbot_process,
    op_kwargs={'bot_name': 'bot3', 'column_name': 'Article Text'},
    dag=dag,
)

expand_rows = PythonOperator(task_id='expanding_rows', python_callable=explode_subject_rows, dag=dag)

[mlbot1_task, mlbot2_task, mlbot3_task] >> expand_rows
