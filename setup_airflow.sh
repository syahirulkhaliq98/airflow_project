#!/bin/bash
set -e

PROJECT_DIR=$HOME/airflow_project
VENV_DIR=$PROJECT_DIR/venv
AIRFLOW_HOME=$PROJECT_DIR/airflow

echo "📁 Creating directories..."
mkdir -p $AIRFLOW_HOME

echo "🐍 Creating virtual environment..."
python3 -m venv $VENV_DIR

source $VENV_DIR/bin/activate

echo "⬆️ Upgrading pip..."
pip install --upgrade pip

echo "📦 Installing Python dependencies..."
pip install -r $PROJECT_DIR/requirements.txt

echo "🛠 Initializing Airflow..."
export AIRFLOW_HOME=$AIRFLOW_HOME
airflow db init

echo "👤 Creating Airflow admin user..."
airflow users create \
  --username admin \
  --password admin \
  --firstname Admin \
  --lastname User \
  --role Admin \
  --email admin@example.com

echo "✅ Airflow setup completed successfully"

