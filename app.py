"""
app.py
Compatibility wrapper - imports the Flask app from wsgi.py

This file exists for compatibility with various deployment platforms that 
auto-detect the app factory pattern. Production servers should use:
  gunicorn app:app  (or wsgi:app)
"""

from wsgi import app, create_app
from tests.app import create_app as _create_app

# Make sure both the app instance and factory are available at module level
# This supports both:
# - gunicorn app:app (uses app instance directly)
# - gunicorn app:create_app (uses factory pattern)

__all__ = ['app', 'create_app']

if __name__ == "__main__":
    app.run()
