from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from datetime import datetime
import os
import psutil
import subprocess
import signal

default_args = {
    'start_date': datetime(2024, 1, 1),
}

with DAG(
    dag_id='AM_Kompas',
    default_args=default_args,
    schedule_interval='@daily',
    catchup=False,
) as dag:

    run_script = BashOperator(
        task_id='Run_Kompas',
        bash_command='python /home/khaliq/airflow_project/airflow/scripts/Kompas.py'
    )

run_script
