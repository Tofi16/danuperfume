# Render.com Deployment Guide - Danu Perfume

## Quick Fix for "ModuleNotFoundError: No module named 'app'"

If you see this error when deploying to Render:
```
ModuleNotFoundError: No module named 'app'
Exited with status 1 while running your code
```

The fixes have been applied to your project. Follow these steps:

---

## 1. Deploy the Updated Code

Make sure to commit and push the new files:

```bash
git add .
git commit -m "Fix Render deployment - add app.py and render.yaml"
git push origin main
```

New files added:
- `app.py` - Compatibility entry point
- `render.yaml` - Render-specific configuration
- Updated `Procfile` with explicit gunicorn command

---

## 2. Render Dashboard Configuration

### Option A: Using render.yaml (Recommended)

1. Your `render.yaml` file now explicitly configures:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn --bind 0.0.0.0:$PORT app:app --workers 3 --timeout 120`
   - Environment variables
   - Disk storage for uploads

2. After pushing, Render will automatically use this configuration

3. No manual setup needed on dashboard!

### Option B: Manual Render Dashboard Setup (If render.yaml doesn't work)

1. Go to your Render dashboard
2. Select your service → Settings
3. Update these settings:

   **Build Command:**
   ```
   pip install -r requirements.txt
   ```

   **Start Command:**
   ```
   gunicorn --bind 0.0.0.0:$PORT app:app --workers 3 --timeout 120
   ```

4. Click Save and redeploy

---

## 3. Environment Variables

Make sure these are set in Render dashboard (Environment → Env Vars):

```
FLASK_ENV=production
SECRET_KEY=your-generated-secret-key
DATABASE_URL=postgresql://username:password@host:port/dbname?sslmode=require
ADMIN_PASSWORD_DANUTA=your-secure-password
ADMIN_PASSWORD_TOFIK=your-secure-password
```

**For SECRET_KEY**, generate it with:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 4. Database Setup

After deployment succeeds for the first time:

1. Go to Render dashboard → Select your service
2. Click "Shell" tab
3. Run:
   ```bash
   flask init-db
   ```

This initializes the database tables and creates default admin accounts.

---

## 5. Troubleshooting Render Deployment

### Problem: Still showing "ModuleNotFoundError"

**Solution:**
1. Make sure you pushed the latest changes (including `app.py`)
2. In Render dashboard, click the 3-dot menu → Redeploy
3. Wait 2-3 minutes for deployment to complete
4. Check logs in the "Logs" tab

### Problem: "ModuleNotFoundError: No module named 'tests'"

**Solution:**
- The `tests/` folder should NOT be imported at the top level
- We created `app.py` to avoid this issue
- Make sure you have the latest `app.py` file

### Problem: "ModuleNotFoundError: No module named 'models'"

**Solution:**
- Ensure `models.py` is in the project root
- It's already there, but if missing, deploy latest version

### Problem: Database connection fails

**Solution:**
1. Verify `DATABASE_URL` is set correctly in Render environment
2. For Neon.tech: URL should end with `?sslmode=require`
3. Test connection: In Render shell run:
   ```bash
   python -c "from models import db; print('Database connected!')"
   ```

### Problem: Admin login doesn't work

**Solution:**
1. Check if you ran `flask init-db` in Render shell
2. Verify `ADMIN_PASSWORD_DANUTA` and `ADMIN_PASSWORD_TOFIK` are set
3. Default credentials: Username = "Danuta" or "Tofik"

---

## 6. Monitoring & Logs

### View Logs in Render

1. Dashboard → Select service
2. Click "Logs" tab
3. Filter by time to see recent errors

### Common Log Messages

```
Starting 'gunicorn app:app'  ← Good, app is starting
Listening on 0.0.0.0:PORT   ← Good, server is ready
Exited with status 1         ← Bad, app crashed
```

### Check Health

Visit your app URL:
```
https://your-app-name.onrender.com/
```

Should see the Danu Perfume homepage.

---

## 7. Redeploy Options

### Option 1: Push to GitHub (Automatic)
```bash
git push origin main
# Render automatically deploys
```

### Option 2: Manual Redeploy in Dashboard
1. Render dashboard → Select service
2. Click 3-dot menu → Redeploy
3. Wait 2-3 minutes

### Option 3: Rebuild from Scratch
1. Click 3-dot menu → Delete
2. Create new service from GitHub repo
3. Configure settings
4. Deploy

---

## 8. Performance Tips

### Increase Workers
For higher traffic, update `Procfile`:
```
web: gunicorn --bind 0.0.0.0:$PORT app:app --workers 5 --timeout 120
```

Then redeploy. Render free tier might be limited to 3-4 workers.

### Upgrade Dyno
Render free tier suspends after 15 minutes of inactivity. To always-on:
- Upgrade to Starter plan ($7/month)
- Select "Always On" in service settings

---

## 9. Database Backups

Render doesn't automatically backup PostgreSQL. Set up backups:

### Option A: Use Neon.tech Dashboard
1. Go to Neon.tech dashboard
2. Select project → Backups
3. Download or restore as needed

### Option B: Manual Backup Command
In Render shell:
```bash
pg_dump $DATABASE_URL > backup.sql
```

---

## 10. SSL/HTTPS

Render automatically provides HTTPS for `.onrender.com` domains.

For custom domain:
1. Dashboard → Settings → Custom Domains
2. Add your domain
3. Follow instructions to update DNS
4. SSL certificate is automatic

---

## Files That Fixed Render Deployment

✅ `app.py` - Compatibility entry point for Gunicorn  
✅ `wsgi.py` - Primary WSGI entry point (already created)  
✅ `render.yaml` - Render-specific configuration  
✅ Updated `Procfile` - Explicit gunicorn command  

All issues should be resolved. If you still see errors, check the Logs tab in Render dashboard and refer to the error message in `TROUBLESHOOTING.md`.

---

## Success Indicators

After deployment, you should see:

✅ App URL accessible  
✅ Homepage loads  
✅ Admin login page loads at `/admin/login`  
✅ Static files (CSS) loading  
✅ No errors in Logs  

If all 5 are working, deployment is successful! 🎉
