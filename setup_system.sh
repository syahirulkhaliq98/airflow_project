#!/bin/bash
set -e

echo "🔧 Updating system..."
sudo apt update && sudo apt upgrade -y

echo "📦 Installing system dependencies..."
sudo apt install -y \
    build-essential \
    curl \
    git \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncursesw5-dev \
    xz-utils \
    tk-dev \
    libxml2-dev \
    libxmlsec1-dev \
    libffi-dev \
    liblzma-dev

echo "🐍 Installing pyenv..."

if [ ! -d "$HOME/.pyenv" ]; then
    curl https://pyenv.run | bash
fi

echo "⚙️ Configuring pyenv..."

if ! grep -q 'export PATH="$HOME/.pyenv/bin:$PATH"' "$HOME/.bashrc"; then
    echo 'export PATH="$HOME/.pyenv/bin:$PATH"' >> "$HOME/.bashrc"
fi

if ! grep -q 'pyenv init -' "$HOME/.bashrc"; then
    echo 'eval "$(pyenv init -)"' >> "$HOME/.bashrc"
fi

export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init -)"

echo "🐍 Installing Python 3.12..."

if ! pyenv versions --bare | grep -q '^3.12'; then
    pyenv install 3.12.10
fi

echo "✅ Python installation completed"

pyenv versions