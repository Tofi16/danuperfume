"""
wsgi.py
WSGI entry point for production deployment (Gunicorn, Heroku, Render, etc.)

This file is imported by web servers to find the Flask application instance.
"""

import os
import sys

# Add the project root to the Python path so tests.app can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tests.app import create_app, db
from models import User, Customer, Product, Order

# Create the Flask app using the factory function
app = create_app(env_name=os.environ.get("FLASK_ENV", "production"))

# Application context for database operations
@app.shell_context_processor
def make_shell_context():
    """Adds models to flask shell context for easier database access."""
    return {
        "db": db,
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
