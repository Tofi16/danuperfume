# Pre-Deployment Checklist for Render

Complete this checklist before pushing to Render:

## 1. Code Changes
- [ ] Latest app.py with both app and create_app exports
- [ ] Updated Procfile with explicit gunicorn command
- [ ] Updated render.yaml with correct startCommand
- [ ] All requirements.txt dependencies listed

## 2. Git Preparation
```bash
# Check status
git status

# Stage all changes
git add .

# Commit with descriptive message
git commit -m "Fix AppImportError: update app entry points and configs"

# Verify commit
git log --oneline -1

# Push to main branch
git push origin main
```

## 3. Render Dashboard - Before Deploying

### Check Environment Variables
1. Go to Dashboard → Select "danu-perfume" service
2. Click Settings
3. Go to Environment
4. Verify these are set:
   - `FLASK_ENV` = `production`
   - `DATABASE_URL` = Valid PostgreSQL URL (from Neon.tech or similar)
   - `SECRET_KEY` = Random 32+ character string
   - `ADMIN_PASSWORD_DANUTA` = Your secure password
   - `ADMIN_PASSWORD_TOFIK` = Your secure password
   - `PYTHONUNBUFFERED` = `true`

**Missing any?** Add them before deploying

### Check Build Settings (if not using render.yaml)
1. Dashboard → Settings → Build Settings
2. Verify:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn --bind 0.0.0.0:$PORT --workers 3 --timeout 120 app:app`

**If different:** Update to match above

## 4. Deploy

### Option A: If Using render.yaml (Automatic)
- Just push your code
- Render automatically detects render.yaml
- Auto-deploys using configuration

### Option B: If Manual Dashboard Config
1. Dashboard → 3-dot menu → Redeploy
2. Wait 2-3 minutes
3. DO NOT just hit "Restart" - must use Redeploy

## 5. Monitor Deployment

1. Go to Logs tab
2. Watch for these messages (good signs):
   ```
   Building...
   Running build command...
   Installing dependencies...
   Build successful
   Starting service...
   Listening on 0.0.0.0:PORT
   ```

3. Watch for these errors (bad signs):
   ```
   Exited with status 1
   ModuleNotFoundError
   AppImportError
   Failed to find attribute
   ```

## 6. After Deployment Succeeds

1. Verify app is running:
   - App URL in Events shows green ✓
   - Logs show "Listening on..."

2. Initialize database:
   - Go to Shell tab in Render
   - Run: `flask init-db`
   - Wait for: "Database initialized."

3. Test in browser:
   - Visit: `https://danu-perfume.onrender.com/`
   - Should show Danu Perfume homepage
   - Try: `/admin/login`
   - Should show admin login page

4. Test login:
   - Username: `Danuta`
   - Password: (use ADMIN_PASSWORD_DANUTA)
   - Should redirect to dashboard

## 7. Troubleshooting If Deployment Fails

### Error: AppImportError: Failed to find attribute 'create_app' in 'app'

**Solution:**
- Make sure you have the updated app.py
- Run: `python -c "from app import app, create_app; print('OK')"`
- Should output: `OK`
- If error, pull latest code and redeploy

### Error: ModuleNotFoundError: No module named 'X'

**Solution:**
- Check requirements.txt has all imports
- Try: `pip install -r requirements.txt` locally
- If fails locally, fix locally first
- Then commit and push

### Error: Exited with status 1 (no other details)

**Solution:**
1. Check full logs in Logs tab
2. Search logs for "Traceback" or "Error:"
3. Look for the actual Python error
4. Fix locally and redeploy

### App runs but homepage shows errors

**Solution:**
1. Database might not be initialized
2. In Shell tab, run: `flask init-db`
3. Refresh browser page
4. Should work now

### Admin login doesn't work

**Solution:**
1. Run `flask init-db` (if not already done)
2. Check PASSWORD environment variables are set
3. Username must be exactly: `Danuta` or `Tofik` (case-sensitive)
4. Password: (from ADMIN_PASSWORD_DANUTA or TOFIK env var)

## 8. Final Verification Checklist

- [ ] Deployment succeeded (green checkmark in Events)
- [ ] Logs show "Listening on..." without errors
- [ ] Homepage loads at app URL
- [ ] Admin login page shows at `/admin/login`
- [ ] Can log in with admin credentials
- [ ] Database initialized (ran `flask init-db`)
- [ ] Can view dashboard after login
- [ ] No errors in Logs tab

**All checked?** Deployment successful! 🎉

---

## Quick Reference Commands

```bash
# Check what changed
git diff --cached

# Undo last commit (if needed)
git reset --soft HEAD~1

# Push to Render
git push origin main

# In Render Shell:
flask init-db          # Initialize database
python -m flask shell  # Open Python shell
```

---

## Support

- **Render-specific guide:** RENDER_DEPLOYMENT.md
- **This error specifically:** RENDER_FIX.md
- **All deployment errors:** TROUBLESHOOTING.md
- **Other platforms:** QUICK_START.md
