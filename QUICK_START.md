# Danu Perfume - Quick Deployment Guide

## 🚀 Choose Your Deployment Path

### Option 1: Heroku (Easiest for Beginners)

```bash
# 1. Install Heroku CLI
# Visit: https://devcenter.heroku.com/articles/heroku-cli

# 2. Login to Heroku
heroku login

# 3. Create app
heroku create danu-perfume-app

# 4. Set environment variables
heroku config:set FLASK_ENV=production
heroku config:set SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
heroku config:set DATABASE_URL="postgresql://username:password@your-neon-host/danu_perfume?sslmode=require"
heroku config:set ADMIN_PASSWORD_DANUTA="your-secure-password"
heroku config:set ADMIN_PASSWORD_TOFIK="your-secure-password"

# 5. Deploy
git push heroku main

# 6. Initialize database
heroku run flask init-db

# 7. View logs
heroku logs -t
```

**Expected output:** App running at `https://danu-perfume-app.herokuapp.com`

---

### Option 2: Render.com (Free Tier Available)

1. **Push code to GitHub**
   ```bash
   git push origin main
   ```

2. **Go to render.com** and connect GitHub account

3. **Create New → Web Service**
   - Select your repository
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn wsgi:app`
   - Environment variables: Set all from `.env.example`

4. **Deploy** - Render automatically deploys on push

---

### Option 3: Railway.app

1. **Push to GitHub**
2. **Visit railway.app** and connect GitHub
3. **New Project → GitHub Repo**
4. **Add PostgreSQL database service**
5. **Set environment variables**
6. **Deploy**

---

### Option 4: Docker (Local or Server)

**Local testing:**
```bash
docker-compose up
# App runs at http://localhost:5000
```

**Production with Docker:**
```bash
# Build image
docker build -t danu-perfume .

# Run container
docker run -d \
  -e DATABASE_URL="postgresql://..." \
  -e SECRET_KEY="your-secret" \
  -e ADMIN_PASSWORD_DANUTA="your-password" \
  -p 5000:8000 \
  danu-perfume

# View logs
docker logs -f <container-id>
```

---

### Option 5: Manual Server (AWS EC2, DigitalOcean, Linode)

**Ubuntu 22.04 Setup:**

```bash
# 1. Update system
sudo apt update && sudo apt upgrade -y

# 2. Install dependencies
sudo apt install -y python3.11 python3-pip python3-venv postgresql postgresql-contrib nginx

# 3. Clone repository
git clone your-repo-url
cd danu_perfume

# 4. Setup Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Create .env file
cp .env.example .env
# Edit .env with production values

# 6. Initialize database
flask init-db

# 7. Create systemd service
sudo tee /etc/systemd/system/danu-perfume.service > /dev/null <<EOF
[Unit]
Description=Danu Perfume Flask Application
After=network.target

[Service]
User=www-data
WorkingDirectory=/home/ubuntu/danu_perfume
Environment="PATH=/home/ubuntu/danu_perfume/venv/bin"
EnvironmentFile=/home/ubuntu/danu_perfume/.env
ExecStart=/home/ubuntu/danu_perfume/venv/bin/gunicorn wsgi:app --workers 4 --bind unix:danu.sock
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 8. Enable and start service
sudo systemctl enable danu-perfume
sudo systemctl start danu-perfume

# 9. Configure Nginx reverse proxy
sudo tee /etc/nginx/sites-available/danu-perfume > /dev/null <<EOF
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://unix:/home/ubuntu/danu_perfume/danu.sock;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /static/ {
        alias /home/ubuntu/danu_perfume/static/;
    }
}
EOF

# 10. Enable Nginx site and restart
sudo ln -s /etc/nginx/sites-available/danu-perfume /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# 11. Get SSL certificate (Let's Encrypt)
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your-domain.com
```

**Check if running:**
```bash
sudo systemctl status danu-perfume
sudo tail -f /var/log/syslog | grep danu
```

---

## 🔧 Post-Deployment Checklist

After deploying to ANY platform:

- [ ] Visit your app URL and confirm it loads
- [ ] Test admin login: `/admin/login`
- [ ] Upload a test product image
- [ ] Create a test order in checkout
- [ ] Check activity logs work
- [ ] Verify emails sending (if configured)
- [ ] Monitor error logs first 24 hours
- [ ] Set up automated backups (database)
- [ ] Configure SSL/HTTPS (automatic on Heroku/Render)
- [ ] Set up monitoring/alerts

---

## 📊 Monitoring Your Deployment

**Heroku:**
```bash
heroku logs -t              # Live logs
heroku metrics              # Performance metrics
heroku restart             # Restart app
```

**Render/Railway:**
- Check Logs tab in dashboard
- Set up Slack/email alerts

**Manual Server:**
```bash
systemctl status danu-perfume
journalctl -u danu-perfume -f
tail -f /var/log/nginx/error.log
```

---

## 🆘 If Something Goes Wrong

1. **Check logs first:**
   ```bash
   # Heroku
   heroku logs --tail
   
   # Manual server
   sudo journalctl -u danu-perfume -n 50
   ```

2. **Restart the app:**
   ```bash
   # Heroku
   heroku restart
   
   # Manual
   sudo systemctl restart danu-perfume
   ```

3. **Check database:**
   ```bash
   flask shell
   >>> from models import Product
   >>> Product.query.count()  # Should return number of products
   ```

4. **Reinitialize if empty:**
   ```bash
   flask init-db
   ```

5. **Still stuck?** See `TROUBLESHOOTING.md` for detailed error solutions

---

## 🆓 Free/Low-Cost Options

- **Heroku:** Free tier removed (pricing starts ~$5/month)
- **Render:** Free tier available (sleeps after 15 min inactivity)
- **Railway:** Free $5/month credit
- **Replit:** Free with limitations
- **PythonAnywhere:** Beginner tier ~$5/month

For database:
- **Neon.tech:** Free PostgreSQL (up to 1GB, 5 projects)
- **AWS RDS:** Free tier for 12 months
- **Render:** Free PostgreSQL (sleeps after inactivity)

---

## 📈 Scaling Tips (When You Have Traffic)

1. **Use CDN** for static files (Cloudflare free tier)
2. **Enable caching** in your app
3. **Upgrade to paid tier** on your platform
4. **Add more Gunicorn workers** (4-8 depending on traffic)
5. **Use external storage** (S3) for file uploads
6. **Set up read replicas** for database
7. **Consider async tasks** with Celery for heavy operations

---

## 📞 Getting Help

- **Flask docs:** https://flask.palletsprojects.com/
- **Stack Overflow:** Tag with `flask`, `deployment`
- **Platform support:**
  - Heroku: https://support.heroku.com/
  - Render: https://support.render.com/
  - Railway: https://support.railway.app/
- **Community Discord:** Flask Discord server
