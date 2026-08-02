# Danu Perfume - Deployment Troubleshooting Guide

## Common Deployment Errors and Fixes

### 1. Render: ModuleNotFoundError: No module named 'app'

**Error:**
```
ModuleNotFoundError: No module named 'app'
Exited with status 1 while running your code
Gunicorn: Running 'gunicorn "app.create_app()"'
```

**Cause:** Render couldn't find the app entry point.

**Fix:**
1. Ensure you have the latest files:
   - `app.py` ← Compatibility entry point
   - `render.yaml` ← Render configuration
   - Updated `Procfile` with explicit command

2. Push changes:
   ```bash
   git add .
   git commit -m "Fix Render deployment"
   git push origin main
   ```

3. In Render dashboard:
   - Click 3-dot menu → Redeploy
   - Wait 2-3 minutes for deployment

4. Check logs in Render dashboard → Logs tab

5. For detailed Render setup, see: `RENDER_DEPLOYMENT.md`

---

### 2. ModuleNotFoundError: No module named 'tests'

**Error:**
```
ModuleNotFoundError: No module named 'tests'
```

**Cause:** The main application is in `tests/app.py` but Python cannot import it.

**Fix:**
- Use `app.py` at project root (now available)
- Procfile uses: `gunicorn app:app`
- Both `wsgi.py` and `app.py` are compatible entry points

---

### 3. No module named 'dotenv'

**Error:**
```
ModuleNotFoundError: No module named 'dotenv'
```

**Fix:**
```bash
pip install python-dotenv
pip install -r requirements.txt
```

---

### 4. DatabaseError: Could not connect to server

**Error:**
```
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) could not connect to server
```

**Cause:** PostgreSQL database URL is incorrect or server is unreachable.

**Fix:**
1. Verify `DATABASE_URL` environment variable is set
2. Check format: `postgresql://user:password@host:port/dbname?sslmode=require`
3. For Neon.tech: ensure `?sslmode=require` is included
4. Test connection:
   ```bash
   psql $DATABASE_URL
   ```

---

### 4. ProgrammingError: relation "products" does not exist

**Error:**
```
sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedTable) relation "products" does not exist
```

**Cause:** Database tables haven't been initialized.

**Fix:**
```bash
# On first deployment, run initialization
flask init-db

# Or via Heroku:
heroku run flask init-db -a your-app-name

# For Render, SSH into the service and run:
flask init-db
```

---

### 5. FileNotFoundError: [Errno 2] No such file or directory: 'static/uploads'

**Error:**
```
FileNotFoundError: [Errno 2] No such file or directory: 'static/uploads'
```

**Cause:** Upload directory doesn't exist or permissions issue.

**Fix:**
1. Ensure directory exists:
   ```bash
   mkdir -p static/uploads
   chmod 755 static/uploads
   ```
2. For Heroku/Render, uploads should use external storage (S3 recommended)
3. Modify upload handling for production cloud storage

---

### 6. SECRET_KEY error

**Error:**
```
Missing or invalid SECRET_KEY configuration
```

**Fix:**
```bash
# Generate a secure key
python -c "import secrets; print(secrets.token_hex(32))"

# Set in environment
export SECRET_KEY=your-generated-key
```

---

### 7. 413 Payload Too Large

**Error:**
```
413 Request Entity Too Large
```

**Cause:** File upload exceeds configured limit.

**Fix:**
1. Check `MAX_UPLOAD_MB` environment variable (default: 5)
2. Increase if needed:
   ```bash
   export MAX_UPLOAD_MB=20
   ```
3. Also configure at web server level:
   - **Nginx:** `client_max_body_size 20M;`
   - **Apache:** `LimitRequestBody 20971520`

---

### 8. ImportError with psycopg2

**Error:**
```
ImportError: libpq.so.5: cannot open shared object file
```

**Cause:** Missing PostgreSQL client libraries.

**Fix:**
```bash
# For Ubuntu/Debian
apt-get install libpq-dev

# For Alpine (in Docker)
apk add postgresql-client

# Reinstall psycopg2
pip install --force-reinstall psycopg2-binary
```

---

### 9. CORS or Static File Issues

**Error:**
- Static CSS/JS files not loading
- CORS errors in browser console

**Fix:**
1. Configure static file serving:
   ```python
   # In wsgi.py or deployment server
   from flask import Flask
   app = Flask(__name__, static_url_path='/static', static_folder='static')
   ```
2. For production, use Nginx/Apache to serve static files
3. Or use CDN for static assets

---

### 10. Timeout Errors

**Error:**
```
TimeoutError or 504 Gateway Timeout
```

**Cause:** Request taking too long (e.g., large file upload, slow database).

**Fix:**
1. Increase Gunicorn timeout:
   ```bash
   gunicorn wsgi:app --timeout 120 --workers 4
   ```
2. Optimize database queries
3. Consider async file uploads with Celery for production
4. For Heroku/Render, use larger dyno/tier

---

### 11. Connection Pool Exhausted

**Error:**
```
QueuePool limit of size 5 overflow 10 reached
```

**Cause:** Too many concurrent database connections.

**Fix:**
Update `config.py` SQLALCHEMY_ENGINE_OPTIONS:
```python
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_size": 10,
    "pool_recycle": 3600,
    "pool_pre_ping": True,
    "max_overflow": 20,
}
```

---

### 12. Admin Login Not Working

**Error:**
- Cannot login with default credentials
- User not found error

**Fix:**
1. Ensure `flask init-db` was run
2. Check admin credentials in config:
   ```python
   ADMIN_ACCOUNTS = [
       ("Danuta", "Danuta", os.environ.get("ADMIN_PASSWORD_DANUTA", "#Danu1122"), "super_admin"),
   ]
   ```
3. Verify environment variables are set:
   ```bash
   echo $ADMIN_PASSWORD_DANUTA
   ```
4. Manually create admin if needed:
   ```python
   flask shell
   >>> from models import User, db
   >>> admin = User(username="admin", full_name="Admin", role="super_admin", is_admin=True)
   >>> admin.set_password("newpassword")
   >>> db.session.add(admin)
   >>> db.session.commit()
   ```

---

### 13. Email Validation Errors

**Error:**
```
ImportError: No module named 'email_validator'
```

**Fix:**
```bash
pip install email-validator
```

---

## Deployment Platforms - Specific Fixes

### Heroku

**Deploy logging:**
```bash
heroku logs -t -a your-app-name
```

**Common Heroku issues:**
- `Web process failed to bind to $PORT`: Usually file permissions
- `H12 Request timeout`: Increase timeout or optimize queries
- `H13 Connection closed`: Connection pool issue

### Render.com

**Check logs:**
Dashboard → Logs tab

**Common issues:**
- Build command failing: Check `pip install -r requirements.txt` output
- Start command failing: Ensure `Procfile` or build settings are correct

### Railway.app

Similar to Render; check:
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn wsgi:app`

---

## Verification Checklist

After deployment, verify:

```bash
# Check app is running
curl https://your-app-url/

# Check admin login page loads
curl https://your-app-url/admin/login

# Check API endpoint
curl https://your-app-url/api/products

# Check logs for errors
heroku logs -t  # or your platform's equivalent
```

---

## Performance Optimization for Production

1. **Enable HTTP/2 and compression** at web server level
2. **Use CDN** for static assets
3. **Cache frequently accessed data** (categories, delivery zones)
4. **Use connection pooling** (already configured)
5. **Optimize database queries** (add indexes on commonly filtered columns)
6. **Use async tasks** for file uploads with Celery
7. **Monitor memory usage** with appropriate worker count
8. **Set up error tracking** with Sentry or similar

---

## Support Resources

- Flask Documentation: https://flask.palletsprojects.com/
- Flask-SQLAlchemy: https://flask-sqlalchemy.palletsprojects.com/
- Gunicorn: https://gunicorn.org/
- PostgreSQL: https://www.postgresql.org/docs/
- Neon.tech (PostgreSQL): https://neon.tech/docs/
