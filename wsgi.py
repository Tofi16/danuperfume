"""
wsgi.py
WSGI entry point for production deployment (Gunicorn, Heroku, Render, etc.)

This file is imported by web servers to find the Flask application instance.
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path so tests.app can be imported
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

print(f"[WSGI] Project root determined as: {project_root}", flush=True)
print(f"[WSGI] __file__ is: {__file__}", flush=True)
print(f"[WSGI] Current working directory: {os.getcwd()}", flush=True)

# Import and configure create_app
from tests.app import create_app as _create_app
from models import db, User, Customer, Product, Order

# Create the Flask app using the factory function
app = _create_app(env_name=os.environ.get("FLASK_ENV", "production"))

# FIX: Override template and static folders to use project root (not tests/ directory)
# This is necessary because Flask(__name__) in tests/app.py sets root_path relative to tests/
template_folder = os.path.join(project_root, 'templates')
static_folder = os.path.join(project_root, 'static')

print(f"[WSGI] Setting template_folder to: {template_folder}", flush=True)
print(f"[WSGI] Setting static_folder to: {static_folder}", flush=True)
print(f"[WSGI] Template folder exists: {os.path.isdir(template_folder)}", flush=True)

if os.path.isdir(template_folder):
    print(f"[WSGI] Templates in folder: {os.listdir(template_folder)}", flush=True)

app.template_folder = template_folder
app.static_folder = static_folder
app.static_url_path = '/static'

print(f"[WSGI] App is configured. Flask root_path: {app.root_path}", flush=True)

# Expose create_app for factory pattern support
create_app = _create_app

# Application context for database operations
@app.shell_context_processor
def make_shell_context():
    """Adds models to flask shell context for easier database access."""
    return {
        "db": _create_app.__globals__['db'],
        "User": User,
        "Customer": Customer,
        "Product": Product,
        "Order": Order,
    }

if __name__ == "__main__":
    # This is for local development only
    # Production servers (Gunicorn, etc.) will call app directly without running this
    with app.app_context():
        db.create_all()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", False))
