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

print(f"[APP.PY] Project root: {project_root}", flush=True)

from wsgi import app, create_app

# Ensure template and static folders are correct (fix for templates not found error)
template_folder = os.path.join(project_root, 'templates')
static_folder = os.path.join(project_root, 'static')

print(f"[APP.PY] Setting template_folder to: {template_folder}", flush=True)
print(f"[APP.PY] Setting static_folder to: {static_folder}", flush=True)

app.template_folder = template_folder
app.static_folder = static_folder
app.static_url_path = '/static'

print(f"[APP.PY] App configured. template_folder: {app.template_folder}", flush=True)

# Make sure the app is available at module level
if __name__ == "__main__":
    app.run()
