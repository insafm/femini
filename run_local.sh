#!/bin/bash

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Virtual environment 'venv' not found. Please create it first."
    exit 1
fi

# Set project root
PROJECT_ROOT=$(pwd)

# Load environment variables from root .env file
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "Loading environment from .env file..."
    echo "Loading environment from .env file..."
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
else
    echo "Warning: .env file not found at $PROJECT_ROOT/.env"
    exit 1
fi

# Update paths to use local directories (not container paths)
export USER_DATA_BASE_DIR=$PROJECT_ROOT/user_data
export COOKIES_BASE_DIR=$PROJECT_ROOT/cookies
export DOWNLOAD_DIR=$PROJECT_ROOT/downloads
export LOG_DIR=$PROJECT_ROOT/logs
export DATABASE_PATH=$PROJECT_ROOT/data/femini_api.db
export HEADLESS=False

# Add to PYTHONPATH for local development
export PYTHONPATH=$PYTHONPATH:$PROJECT_ROOT/femini-playwright:$PROJECT_ROOT/femini-api

# Create necessary directories
mkdir -p data
mkdir -p downloads
mkdir -p user_data
mkdir -p logs
mkdir -p cookies

echo "Starting Femini API Server locally..."
echo "Environment loaded from .env"
echo "HEADLESS: $HEADLESS"
echo "DB_PATH: $DB_PATH"
echo "Credentials loaded: ${#GEMINI_CREDENTIALS} characters"

# Run the server
cd femini-api
python3 -m src.api_server
