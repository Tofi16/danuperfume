# Danu Perfume Deployment Guide

## Quick Start for Heroku/Render Deployment

### Prerequisites
1. Git repository initialized (`.git/` already exists)
2. Heroku CLI or Render account set up
3. Environment variables configured

### Environment Variables Required

Create a `.env` file (or configure in your platform):

```
FLASK_ENV=production
SECRET_KEY=your-long-random-secret-key-here
DATABASE_URL=postgresql://username:password@host/dbname?sslmode=require
UPLOAD_FOLDER=static/uploads
MAX_UPLOAD_MB=5
ADMIN_PASSWORD_DANUTA=your-secure-password
ADMIN_PASSWORD_TOFIK=your-secure-password
DELIVERY_FEE_MIN=80
DELIVERY_FEE_MAX=250
FX_RATE_USD=0.0075
FX_RATE_EUR=0.0069
LOYALTY_POINTS_PER_100_ETB=5
RISK_HIGH_ORDER_AMOUNT=5000
RISK_DUPLICATE_WINDOW_MINUTES=30
```

### For Heroku

```bash
# Login to Heroku
heroku login

# Create a new app
heroku create your-app-name

# Set environment variables
heroku config:set FLASK_ENV=production
heroku config:set SECRET_KEY=your-secret-key
heroku config:set DATABASE_URL=your-neon-postgres-url

# Deploy
git push heroku main

# Initialize database
heroku run flask init-db
```

### For Render.com

1. Connect your GitHub repository
2. Create a new Web Service
3. Use build command: `pip install -r requirements.txt`
4. Use start command: `gunicorn wsgi:app`
5. Add all environment variables in the Settings tab
6. Deploy

### For Manual Server Deployment

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL=postgresql://...
export SECRET_KEY=your-secret-key
export FLASK_ENV=production

# Initialize database (first time only)
flask init-db

# Run with Gunicorn
gunicorn wsgi:app --bind 0.0.0.0:8000 --workers 4
```

## Files Added for Deployment

- **wsgi.py** - WSGI entry point for production servers
- **Procfile** - Process configuration for Heroku/Render
- **runtime.txt** - Python version specification
- **.gitignore** - Files to exclude from Git

## Database Setup

The application automatically initializes the database on first startup:
- Creates all tables
- Adds default admin accounts
- Seeds default categories, banks, delivery zones, and post offices

For manual initialization on deployment:
```bash
flask init-db
```

## Troubleshooting

### Import Error: No module named 'tests'
- Ensure `wsgi.py` is in the project root
- Python path is automatically configured in `wsgi.py`

### Database Connection Error
- Verify `DATABASE_URL` environment variable is set correctly
- For Neon.tech, ensure URL includes `?sslmode=require`

### Static Files Not Loading
- Ensure `UPLOAD_FOLDER=static/uploads` is set
- Uploads directory must be writable by the web process

### 413 File Too Large Error
- Check `MAX_UPLOAD_MB` environment variable
- Default is 5MB

## Production Checklist

- [ ] Set `SECRET_KEY` to a long, random string
- [ ] Set `FLASK_ENV=production`
- [ ] Set `DEBUG=False` (implicit in production config)
- [ ] Configure PostgreSQL database (Neon.tech recommended)
- [ ] Set secure admin passwords
- [ ] Configure all required environment variables
- [ ] Run `flask init-db` on deployment
- [ ] Test login with admin credentials
- [ ] Verify file uploads work
- [ ] Set up error monitoring (Sentry recommended)
- [ ] Configure HTTPS/SSL
- [ ] Set up regular database backups

## Monitoring & Logs

- Check application logs through your platform's dashboard
- For local errors, review Flask output
- Enable error monitoring for production bugs
