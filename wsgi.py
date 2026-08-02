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

# Import and configure create_app
from tests.app import create_app as _create_app
from models import User, Customer, Product, Order

# Create the Flask app using the factory function
app = _create_app(env_name=os.environ.get("FLASK_ENV", "production"))

# FIX: Override template and static folders to use project root (not tests/ directory)
# This is necessary because Flask(__name__) in tests/app.py sets root_path relative to tests/
app.template_folder = os.path.join(project_root, 'templates')
app.static_folder = os.path.join(project_root, 'static')
app.static_url_path = '/static'

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
