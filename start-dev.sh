#!/bin/bash
# start-dev.sh - Local development startup script

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "Warning: .env file not found. Using defaults."
fi

# Set development environment
export FLASK_ENV=development
export FLASK_DEBUG=True

# Create virtual environment if it doesn't exist
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Initialize database if needed
if [ ! -f danu_perfume.db ]; then
    echo "Initializing database..."
    flask init-db
fi

# Start development server
echo "Starting development server on http://localhost:5000"
python -m flask run --host=0.0.0.0 --port=5000
