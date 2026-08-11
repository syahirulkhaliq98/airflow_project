#!/bin/bash
set -e

echo "🔧 Updating system..."
sudo apt update && sudo apt upgrade -y

echo "📦 Installing system dependencies..."
sudo apt install -y \
  python3 \
  python3-pip \
  python3-venv \
  build-essential \
  libssl-dev \
  libffi-dev \
  python3-dev \
  curl

echo "✅ System dependencies installed"
