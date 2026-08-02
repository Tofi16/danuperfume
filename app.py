"""
app.py
Compatibility wrapper - imports the Flask app from wsgi.py

This file exists for compatibility with various deployment platforms that 
auto-detect the app factory pattern. Production servers should use:
  gunicorn app:app  (or wsgi:app)
"""

from wsgi import app

# Make sure the app is available at module level
if __name__ == "__main__":
    app.run()
