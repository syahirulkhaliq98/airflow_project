from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from datetime import datetime
import os
import psutil
import subprocess
import signal

def cleanup_chrome_processes():
    """
    Kill all Chrome/Chromedriver processes safely for Airflow tasks.
    
    Works in WSL/Linux, avoids zombie tasks, and completes quickly.

    Matches exact process names only. The old substring match ('chrome' in name)
    also hit this task's own Airflow process, whose title contains "cleanup_chrome",
    so the task SIGKILLed itself (return code -9 / zombie job).
    """
    chrome_names = {
        'chrome', 'chromium', 'chromium-browser', 'chromedriver', 'google-chrome',
        'chrome_crashpad_handler', 'chrome_crashpad',
    }

    try:
        # Never touch this process or anything above it (task runner, supervisor, scheduler)
        protected_pids = {os.getpid()}
        try:
            protected_pids.update(p.pid for p in psutil.Process().parents())
        except psutil.Error:
            pass
        current_user = psutil.Process().username()

        # Collect all Chrome-related PIDs owned by this user
        chrome_pids = [
            proc.info['pid'] for proc in psutil.process_iter(['pid', 'name', 'username'])
            if proc.info['name'] and proc.info['name'].lower() in chrome_names
            and proc.info['username'] == current_user
            and proc.info['pid'] not in protected_pids
        ]

        # Kill processes quickly without waiting
        for pid in chrome_pids:
            try:
                os.kill(pid, signal.SIGKILL)  # Force kill
            except (ProcessLookupError, PermissionError):
                pass

        print(f"✅ Cleaned up {len(chrome_pids)} Chrome/Chromedriver processes.")

    except Exception as e:
        print(f"⚠️ Error cleaning up Chrome processes: {e}")

default_args = {
    'start_date': datetime(2024, 1, 1),
}

with DAG(
    dag_id='AM_The_Straits_Times',
    default_args=default_args,
    schedule_interval='@daily',
    catchup=False,
) as dag:

    run_script = BashOperator(
        task_id='Run_The_Straits_Times',
        bash_command='python /home/khaliq/airflow_project/airflow/scripts/TheStraitsTimes.py'
    )

    cleanup_task = PythonOperator(
        task_id='cleanup_chrome',
        python_callable=cleanup_chrome_processes
    )

run_script >> cleanup_task
