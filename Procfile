web: gunicorn --bind 0.0.0.0:$PORT --workers 3 --timeout 120 --access-logfile - app:app
release: flask init-db
