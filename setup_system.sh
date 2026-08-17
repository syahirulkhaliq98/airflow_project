#!/bin/bash
set -e

echo "🔧 Updating system..."
sudo apt update && sudo apt upgrade -y

echo "📦 Installing system dependencies..."
sudo apt install -y \
  python3.12 \
  python3.12-pip \
  python3.12-venv \
  build-essential \
  libssl-dev \
  libffi-dev \
  python3.12-dev \
  curl

echo "✅ System dependencies installed"
