#!/bin/bash
# Cleanup script to remove Python cache files and other temporary files

echo "🧹 Cleaning up Python cache files..."

# Remove __pycache__ directories
find . -type d -name "__pycache__" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null

# Remove .pyc files
find . -type f -name "*.pyc" -not -path "./.venv/*" -delete 2>/dev/null

# Remove .pyo files
find . -type f -name "*.pyo" -not -path "./.venv/*" -delete 2>/dev/null

echo "✅ Cleanup complete!"
