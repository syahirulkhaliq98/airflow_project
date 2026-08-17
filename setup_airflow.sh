#!/bin/bash
set -e

PROJECT_DIR="$HOME/airflow_project"
VENV_DIR="$PROJECT_DIR/venv"
AIRFLOW_HOME="$PROJECT_DIR/airflow"

echo "📁 Creating directories..."
mkdir -p "$AIRFLOW_HOME"

echo "🐍 Configuring Python 3.12..."

export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init -)"

pyenv local 3.12.10

echo "Python version:"
python --version

echo "🐍 Creating virtual environment..."

if [ ! -d "$VENV_DIR" ]; then
    python -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Python inside venv:"
python --version

echo "⬆️ Upgrading pip..."
pip install --upgrade pip

echo "📦 Installing Python dependencies..."
pip install -r "$PROJECT_DIR/requirements.txt"

echo "🛠 Initializing Airflow..."

export AIRFLOW_HOME="$AIRFLOW_HOME"

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