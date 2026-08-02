"""
app.py
Compatibility wrapper - imports the Flask app from wsgi.py

This file exists for compatibility with various deployment platforms that 
auto-detect the app factory pattern. Production servers should use:
  gunicorn app:app  (or wsgi:app)
"""

import os
import sys

# Ensure project root is in path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from wsgi import app, create_app

# Ensure template and static folders are correct (fix for templates not found error)
app.template_folder = os.path.join(project_root, 'templates')
app.static_folder = os.path.join(project_root, 'static')
app.static_url_path = '/static'

# Make sure the app is available at module level
if __name__ == "__main__":
    app.run()
