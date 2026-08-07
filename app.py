"""
app.py
Main Flask application for Danu Perfume.

Responsibilities:
    - App factory / initialization
    - Database (Neon PostgreSQL via SQLAlchemy) wiring
    - Authentication (Flask-Login) + Role-Based Access Control for the admin dashboard
    - i18n language switching (dictionary-based, see translations.py)
    - Public storefront routes (home, shop, product notes, checkout, order tracking,
      reviews, stock alerts)
    - Admin routes (login, dashboard, product CRUD, order management, payment
      accounts, delivery zones, coupons, loyalty, banners, activity log, analytics,
      bulk CSV import)
    - Secure file upload handling for product images and payment receipts
    - Lightweight fraud/risk scoring on new orders
"""

import csv
import click
import io
import os
import random
import uuid
import requests
from datetime import datetime, timedelta, date
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort, Response
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from flask_wtf.csrf import CSRFProtect, generate_csrf
from cloudinary import config as cloudinary_config
from cloudinary.uploader import upload as cloudinary_upload
from cloudinary.utils import cloudinary_url
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, inspect, text
from flask_apscheduler import APScheduler

from config import config_by_name
from models import (
    db, User, Customer, ActivityLog, Category, Product, ProductImage, Review, StockAlert,
    Bank, DeliveryZone, Coupon, LoyaltyAccount, Banner, PostOffice, Order, OrderItem,
    OrderIssueReport, AppSetting, DailySummary,
)
from translations import TRANSLATIONS, get_text


# Seed data only — used to populate the post_offices table on first run so the
# picker isn't empty out of the box. The real, full branch directory (which can
# run into the thousands) should be bulk-imported by an admin via CSV at
# /admin/post-offices/import, since Claude cannot fabricate verified addresses
# for every official Ethio Post branch.
SEED_POST_OFFICES = [
    {"name": "Addis Ababa Main Post Office", "city": "Addis Ababa", "region": "Addis Ababa", "postal_code": "1000", "address": "P.O. Box 1111, Central Addis Ababa"},
    {"name": "Bole Post Office", "city": "Addis Ababa", "region": "Addis Ababa", "postal_code": "1000", "address": "Bole Sub-city, Addis Ababa"},
    {"name": "Megenagna Post Office", "city": "Addis Ababa", "region": "Addis Ababa", "postal_code": "1000", "address": "Megenagna, Addis Ababa"},
    {"name": "Arada Post Office", "city": "Addis Ababa", "region": "Addis Ababa", "postal_code": "1000", "address": "Arada Sub-city, Addis Ababa"},
    {"name": "Kirkos Post Office", "city": "Addis Ababa", "region": "Addis Ababa", "postal_code": "1000", "address": "Kirkos, Addis Ababa"},
    {"name": "Lideta Post Office", "city": "Addis Ababa", "region": "Addis Ababa", "postal_code": "1000", "address": "Lideta, Addis Ababa"},
    {"name": "Dire Dawa Post Office", "city": "Dire Dawa", "region": "Dire Dawa", "postal_code": "3000", "address": "Dire Dawa City"},
    {"name": "Mekelle Post Office", "city": "Mekelle", "region": "Tigray", "postal_code": "7000", "address": "Mekelle City"},
    {"name": "Adama Post Office", "city": "Adama", "region": "Oromia", "postal_code": "3020", "address": "Adama City"},
    {"name": "Hawassa Post Office", "city": "Hawassa", "region": "Sidama", "postal_code": "4500", "address": "Hawassa City"},
    {"name": "Bahir Dar Post Office", "city": "Bahir Dar", "region": "Amhara", "postal_code": "6000", "address": "Bahir Dar City"},
    {"name": "Jimma Post Office", "city": "Jimma", "region": "Oromia", "postal_code": "3780", "address": "Jimma City"},
    {"name": "Gondar Post Office", "city": "Gondar", "region": "Amhara", "postal_code": "6200", "address": "Gondar City"},
    {"name": "Debre Berhan Post Office", "city": "Debre Berhan", "region": "Amhara", "postal_code": "4450", "address": "Debre Berhan City"},
    {"name": "Asosa Post Office", "city": "Asosa", "region": "Benishangul-Gumuz", "postal_code": "300", "address": "Asosa City"},
    {"name": "Jijiga Post Office", "city": "Jijiga", "region": "Somali", "postal_code": "4400", "address": "Jijiga City"},
    {"name": "Shashemene Post Office", "city": "Shashemene", "region": "Oromia", "postal_code": "2600", "address": "Shashemene City"},
    {"name": "Harar Post Office", "city": "Harar", "region": "Harari", "postal_code": "3200", "address": "Harar City"},
    {"name": "Dessie Post Office", "city": "Dessie", "region": "Amhara", "postal_code": "3000", "address": "Dessie City"},
    {"name": "Nekemte Post Office", "city": "Nekemte", "region": "Oromia", "postal_code": "2500", "address": "Nekemte City"},
]


def create_app(env_name=None):
    """Application factory."""
    app = Flask(__name__)

    env_name = env_name or os.environ.get("FLASK_ENV", "production")
    app.config.from_object(config_by_name.get(env_name, config_by_name["production"]))

    if app.config.get("CLOUDINARY_URL"):
        cloudinary_config(cloudinary_url=app.config["CLOUDINARY_URL"])
    elif app.config.get("CLOUDINARY_CLOUD_NAME") and app.config.get("CLOUDINARY_API_KEY") and app.config.get("CLOUDINARY_API_SECRET"):
        cloudinary_config(
            cloud_name=app.config["CLOUDINARY_CLOUD_NAME"],
            api_key=app.config["CLOUDINARY_API_KEY"],
            api_secret=app.config["CLOUDINARY_API_SECRET"],
        )

    # --- Initialize extensions ---
    db.init_app(app)

    # --- Initialize APScheduler for daily automated tasks ---
    scheduler = APScheduler()
    scheduler.init_app(app)
    
    # Only start the scheduler if it's not already running and we're not in a worker thread
    try:
        if not scheduler.running:
            scheduler.start()
    except Exception as e:  # noqa: BLE001
        print(f"Warning: APScheduler failed to start: {str(e)}")
        # Don't fail the entire app if scheduler has issues

    # SECURITY FIX: CSRF protection for every POST/PUT/DELETE form in the app
    # (login, checkout, admin CRUD, etc.). `csrf_token()` is exposed to every
    # template below so `{{ csrf_token() }}` can be dropped into any <form>.
    csrf = CSRFProtect(app)
    app.jinja_env.globals["csrf_token"] = generate_csrf

    login_manager = LoginManager()
    login_manager.login_view = "customer_login"
    login_manager.login_message = "Please log in to continue."
    login_manager.login_message_category = "warning"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(prefixed_id):
        # IDs are prefixed ("admin-3" / "customer-7") so one login system can
        # safely serve two different account types without ever confusing them.
        try:
            kind, raw_id = prefixed_id.split("-", 1)
        except ValueError:
            return None
        if kind == "admin":
            return db.session.get(User, int(raw_id))
        if kind == "customer":
            return db.session.get(Customer, int(raw_id))
        return None

    # --- Ensure upload folder exists ---
    upload_path = os.path.join(app.root_path, app.config["UPLOAD_FOLDER"])
    os.makedirs(upload_path, exist_ok=True)

    # --- Schedule daily automated tasks ---
    # Schedule the daily summary generation to run at 00:00 UTC every day
    # This will capture metrics, create summary records, and send Telegram reports
    try:
        @scheduler.scheduled_job('cron', hour=0, minute=0, timezone='UTC', id='daily_summary')
        def scheduled_daily_summary():
            with app.app_context():
                generate_daily_summary()
    except Exception as e:  # noqa: BLE001
        print(f"Warning: Could not register scheduler job: {str(e)}")

    # =========================================================
    # i18n helpers
    # =========================================================
    @app.before_request
    def set_default_language():
        if "lang" not in session:
            session["lang"] = app.config["DEFAULT_LANGUAGE"]

    @app.route("/set-language/<lang_code>")
    def set_language(lang_code):
        if lang_code in app.config["LANGUAGES"]:
            session["lang"] = lang_code
        return redirect(request.referrer or url_for("index"))

    @app.context_processor
    def inject_globals():
        current_lang = session.get("lang", app.config["DEFAULT_LANGUAGE"])

        def t(key):
            return get_text(key, current_lang)

        active_banner = None
        try:
            active_banner = Banner.query.filter_by(is_active=True).order_by(Banner.created_at.desc()).first()
        except Exception:  # noqa: BLE001
            pass  # table may not exist yet on a fresh, un-migrated DB

        support_telegram_username = None
        try:
            support_telegram_username = get_setting("telegram_support_username")
        except Exception:  # noqa: BLE001
            pass

        return dict(
            t=t,
            current_lang=current_lang,
            available_languages=app.config["LANGUAGES"],
            lang_names={code: TRANSLATIONS[code]["lang.name"] for code in app.config["LANGUAGES"]},
            currency=app.config["CURRENCY_SYMBOL"],
            fx_rates=app.config["FX_RATES"],
            now=datetime.utcnow(),
            active_banner=active_banner,
            media_url=media_url,
            support_telegram_username=support_telegram_username,
        )

    # =========================================================
    # File upload helpers
    # =========================================================
    def allowed_file(filename):
        return (
            "." in filename
            and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
        )

    def save_uploaded_file(file_storage, subfolder=""):
        """
        Saves an uploaded file and returns either a local relative path or a Cloudinary URL.
        """
        if not file_storage or file_storage.filename == "":
            return None

        if not allowed_file(file_storage.filename):
            return None

        if app.config.get("CLOUDINARY_URL") or (
            app.config.get("CLOUDINARY_CLOUD_NAME") and
            app.config.get("CLOUDINARY_API_KEY") and
            app.config.get("CLOUDINARY_API_SECRET")
        ):
            cloud_url = upload_to_cloudinary(file_storage, folder=f"danu_perfume/{subfolder}" if subfolder else "danu_perfume")
            if cloud_url:
                return cloud_url

        original_name = secure_filename(file_storage.filename)
        extension = original_name.rsplit(".", 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex}.{extension}"

        target_dir = os.path.join(app.root_path, app.config["UPLOAD_FOLDER"], subfolder)
        os.makedirs(target_dir, exist_ok=True)

        file_storage.save(os.path.join(target_dir, unique_name))

        return f"{subfolder}/{unique_name}" if subfolder else unique_name

    def upload_to_cloudinary(file_storage, folder="danu_perfume"):
        """
        Uploads a file to Cloudinary if configured, otherwise returns None.
        """
        if not file_storage or not (
            app.config.get("CLOUDINARY_URL") or (
                app.config.get("CLOUDINARY_CLOUD_NAME") and
                app.config.get("CLOUDINARY_API_KEY") and
                app.config.get("CLOUDINARY_API_SECRET")
            )
        ):
            return None

        try:
            result = cloudinary_upload(
                file_storage,
                folder=folder,
                use_filename=True,
                unique_filename=True,
                overwrite=False,
            )
            return result.get("secure_url")
        except Exception:
            return None

    def media_url(path_or_url):
        """
        Returns a correct public URL for a stored media asset.
        If the value already looks like a complete URL, return it as-is.
        """
        if not path_or_url:
            return None
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return url_for("static", filename=f"uploads/{path_or_url}")

    def generate_order_code():
        return "DP-" + uuid.uuid4().hex[:8].upper()

    def roll_delivery_fee():
        """Generates a randomized delivery fee within the configured ETB range."""
        low = app.config["DELIVERY_FEE_MIN"]
        high = app.config["DELIVERY_FEE_MAX"]
        return Decimal(str(round(random.uniform(low, high), 2)))

    def resolve_delivery_fee(city):
        """Prefers a fixed DeliveryZone fee for the given city; falls back to a random fee."""
        if city:
            zone = DeliveryZone.query.filter(
                func.lower(DeliveryZone.city_name) == city.strip().lower(),
                DeliveryZone.is_active == True,  # noqa: E712
            ).first()
            if zone:
                return zone.fee
        return roll_delivery_fee()

    # =========================================================
    # App Settings (key/value) + Telegram notifications
    # =========================================================
    # SECURITY: never hardcode the bot token here — GitHub's secret scanner will
    # flag it (and anyone with repo read access could message as your bot).
    # Set it once in your hosting provider's Environment Variables instead.
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    def get_setting(key, default=None):
        try:
            row = db.session.get(AppSetting, key)
            return row.value if row and row.value else default
        except Exception:  # noqa: BLE001
            return default

    def set_setting(key, value):
        row = db.session.get(AppSetting, key)
        if row:
            row.value = value
        else:
            row = AppSetting(key=key, value=value)
            db.session.add(row)
        db.session.commit()

    def mask_phone(phone):
        """SECURITY FIX: never send a customer's full phone number into a Telegram
        chat that could be forwarded, screenshotted, or read by anyone with access
        to the bot. Keeps the last 3 digits visible so the admin can still match
        the order to the customer in the dashboard."""
        if not phone:
            return "—"
        digits = phone.strip()
        if len(digits) <= 4:
            return "*" * len(digits)
        return digits[:-7] + "***" + digits[-4:] if len(digits) > 7 else digits[:2] + "***" + digits[-2:]

    def send_telegram_message(text):
        """Fire-and-forget message to the admin's configured Telegram chat.
        Never raises — a Telegram outage must not block checkout or any
        other request that triggers a notification."""
        chat_id = get_setting("telegram_chat_id")
        if not chat_id or not TELEGRAM_BOT_TOKEN:
            return False
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=6,
            )
            return resp.ok
        except Exception:  # noqa: BLE001
            return False

    def send_telegram_photo(photo_url, caption):
        """Send the payment receipt image alongside the order details, so the
        admin can verify the transfer without opening the dashboard first."""
        chat_id = get_setting("telegram_chat_id")
        if not chat_id or not TELEGRAM_BOT_TOKEN or not photo_url:
            return False
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                json={"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML"},
                timeout=8,
            )
            return resp.ok
        except Exception:  # noqa: BLE001
            return False

    def notify_new_order_telegram(order):
        lines = [
            "🛍️ <b>New Order — Danu Perfume &amp; Cosmo</b>",
            f"Order: <b>{order.order_code}</b>",
            # SECURITY FIX: phone is masked before it ever leaves the server —
            # the full number stays in the admin dashboard, not in a chat that
            # can be forwarded or screenshotted (see checkout review, part 1).
            f"Customer: {order.customer_name} ({mask_phone(order.customer_phone)})",
            f"City: {order.city or '—'}",
            f"Delivery: {order.delivery_type}",
            f"Total: {order.total_amount} ETB",
        ]
        if order.risk_level and order.risk_level != "Low Risk":
            lines.append(f"⚠️ Risk: {order.risk_level}")
        try:
            lines.append(f'<a href="{url_for("admin_order_detail", order_id=order.id, _external=True)}">Open in Dashboard →</a>')
        except Exception:  # noqa: BLE001
            pass  # outside a request context (e.g. a future cron job) — just skip the link
        message = "\n".join(lines)

        # SECURITY FIX: the payment receipt (which can contain a bank account
        # number / IBAN) is deliberately NOT forwarded to Telegram anymore.
        # Admins verify the receipt inside the dashboard, where it's behind
        # login instead of sitting in a chat log. See notify_new_order_telegram
        # docstring / part 1 of the review.
        send_telegram_message(message)

    def generate_daily_summary():
        """
        Scheduled job to run at 00:00 UTC each day.
        Captures daily transaction metrics, creates a summary record, and sends a report to Telegram.
        """
        try:
            yesterday = datetime.utcnow().date() - timedelta(days=1)
            start_of_day = datetime.combine(yesterday, datetime.min.time())
            end_of_day = datetime.combine(yesterday, datetime.max.time())
            
            # Check if summary already exists for this day (prevents duplicates)
            existing = DailySummary.query.filter_by(summary_date=yesterday).first()
            if existing:
                return f"Summary already exists for {yesterday}"
            
            # Query all orders from yesterday
            orders_yesterday = Order.query.filter(
                Order.created_at >= start_of_day,
                Order.created_at <= end_of_day
            ).all()
            
            # Calculate metrics
            total_orders = len(orders_yesterday)
            pending_orders = len([o for o in orders_yesterday if o.status == Order.STATUS_PENDING])
            approved_orders = len([o for o in orders_yesterday if o.status == Order.STATUS_APPROVED])
            delivered_orders = len([o for o in orders_yesterday if o.status == Order.STATUS_DELIVERED])
            cancelled_orders = len([o for o in orders_yesterday if o.status == Order.STATUS_CANCELLED])
            
            total_revenue = Decimal('0')
            total_discount = Decimal('0')
            total_delivery_fees = Decimal('0')
            standard_courier_count = 0
            motorcycle_rider_count = 0
            post_office_pickup_count = 0
            high_risk_count = 0
            medium_risk_count = 0
            total_points_issued = 0
            
            for order in orders_yesterday:
                total_revenue += order.total_amount or Decimal('0')
                total_discount += order.discount_amount or Decimal('0')
                total_delivery_fees += order.delivery_fee or Decimal('0')
                total_points_issued += order.points_earned or 0
                
                if order.delivery_type == Order.DELIVERY_STANDARD:
                    standard_courier_count += 1
                elif order.delivery_type == Order.DELIVERY_MOTORCYCLE:
                    motorcycle_rider_count += 1
                elif order.delivery_type == Order.DELIVERY_PICKUP:
                    post_office_pickup_count += 1
                
                if order.risk_level == Order.RISK_HIGH:
                    high_risk_count += 1
                elif order.risk_level == Order.RISK_MEDIUM:
                    medium_risk_count += 1
            
            # Calculate new vs returning customers (based on phone number duplicates)
            customer_phones_yesterday = [o.customer_phone for o in orders_yesterday]
            new_customers = 0
            returning_customers = 0
            
            for phone in set(customer_phones_yesterday):
                previous_orders = Order.query.filter(
                    Order.customer_phone == phone,
                    Order.created_at < start_of_day
                ).count()
                
                if previous_orders == 0:
                    new_customers += 1
                else:
                    returning_customers += 1
            
            # Create the daily summary record
            summary = DailySummary(
                summary_date=yesterday,
                total_orders=total_orders,
                pending_orders=pending_orders,
                approved_orders=approved_orders,
                delivered_orders=delivered_orders,
                cancelled_orders=cancelled_orders,
                total_revenue=total_revenue,
                total_discount_given=total_discount,
                total_delivery_fees=total_delivery_fees,
                new_customers=new_customers,
                returning_customers=returning_customers,
                standard_courier_count=standard_courier_count,
                motorcycle_rider_count=motorcycle_rider_count,
                post_office_pickup_count=post_office_pickup_count,
                high_risk_orders=high_risk_count,
                medium_risk_orders=medium_risk_count,
                points_issued=total_points_issued,
                report_generated_at=datetime.utcnow(),
            )
            db.session.add(summary)
            db.session.commit()
            
            # Send Telegram report
            send_daily_report_telegram(summary)
            
            return f"Daily summary created for {yesterday}"
        except Exception as e:  # noqa: BLE001
            print(f"Error generating daily summary: {str(e)}")
            return f"Error: {str(e)}"

    def send_daily_report_telegram(summary):
        """
        Formats and sends the daily summary report to Telegram chat.
        Includes all key metrics for daily review by admin.
        """
        chat_id = get_setting("telegram_chat_id")
        if not chat_id or not TELEGRAM_BOT_TOKEN:
            return False
        
        try:
            # Format the daily report message
            report_lines = [
                "📊 <b>Daily Summary Report — Danu Perfume</b>",
                f"<b>Date:</b> {summary.summary_date.strftime('%A, %B %d, %Y')}",
                "",
                "<b>📦 Order Metrics</b>",
                f"  • Total Orders: {summary.total_orders}",
                f"  • Pending: {summary.pending_orders} | Approved: {summary.approved_orders}",
                f"  • Delivered: {summary.delivered_orders} | Cancelled: {summary.cancelled_orders}",
                "",
                "<b>💰 Financial Summary</b>",
                f"  • Total Revenue: {summary.total_revenue} ETB",
                f"  • Discounts Given: {summary.total_discount_given} ETB",
                f"  • Delivery Fees: {summary.total_delivery_fees} ETB",
                "",
                "<b>👥 Customer Metrics</b>",
                f"  • New Customers: {summary.new_customers}",
                f"  • Returning Customers: {summary.returning_customers}",
                "",
                "<b>🚚 Delivery Breakdown</b>",
                f"  • Standard Courier: {summary.standard_courier_count}",
                f"  • Motorcycle Rider: {summary.motorcycle_rider_count}",
                f"  • Post Office Pickup: {summary.post_office_pickup_count}",
                "",
                "<b>⚠️ Risk Assessment</b>",
                f"  • High Risk Orders: {summary.high_risk_orders}",
                f"  • Medium Risk Orders: {summary.medium_risk_orders}",
                "",
                "<b>🎁 Loyalty Points</b>",
                f"  • Points Issued: {summary.points_issued}",
                "",
                f"<i>Report Generated: {summary.report_generated_at.strftime('%H:%M:%S UTC')}</i>",
            ]
            
            message = "\n".join(report_lines)
            
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=8,
            )
            
            if resp.ok:
                # Update the summary record to mark as notified
                summary.telegram_notified = True
                summary.telegram_notified_at = datetime.utcnow()
                db.session.commit()
            
            return resp.ok
        except Exception:  # noqa: BLE001
            return False

    # =========================================================
    # Activity log + RBAC helpers
    # =========================================================
    def log_activity(action, details=""):
        try:
            entry = ActivityLog(
                user_id=current_user.id if current_user.is_authenticated else None,
                username=current_user.username if current_user.is_authenticated else "system",
                action=action,
                details=details[:500],
            )
            db.session.add(entry)
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()

    def admin_required(view_func):
        """Allow access only to the two named admin accounts."""
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("customer_login", next=request.path))

            if not isinstance(current_user, User):
                flash("Access denied. Only Tofik or Danuta can access the admin panel.", "error")
                return redirect(url_for("customer_account"))

            username = (getattr(current_user, "username", "") or "").strip().lower()
            if username not in {"tofik", "danuta"}:
                flash("Access denied. Only Tofik or Danuta can access the admin panel.", "error")
                return redirect(url_for("customer_account"))

            return view_func(*args, **kwargs)
        return wrapper

    def super_admin_required(view_func):
        @wraps(view_func)
        @admin_required
        def wrapper(*args, **kwargs):
            if not current_user.is_super_admin:
                flash("You don't have permission to access that page.", "error")
                return redirect(url_for("admin_dashboard"))
            return view_func(*args, **kwargs)
        return wrapper

    # =========================================================
    # Fraud / risk scoring
    # =========================================================
    def score_order_risk(customer_phone, total_amount):
        """A lightweight heuristic risk score shown to admins as a color-coded badge."""
        reasons = []
        risk = Order.RISK_LOW

        if total_amount and total_amount >= Decimal(str(app.config["RISK_HIGH_ORDER_AMOUNT"])):
            reasons.append("High order value")
            risk = Order.RISK_MEDIUM

        window_start = datetime.utcnow() - timedelta(minutes=app.config["RISK_DUPLICATE_WINDOW_MINUTES"])
        recent_count = Order.query.filter(
            Order.customer_phone == customer_phone,
            Order.created_at >= window_start,
        ).count()
        if recent_count >= 2:
            reasons.append(f"{recent_count} orders from this phone in {app.config['RISK_DUPLICATE_WINDOW_MINUTES']} min")
            risk = Order.RISK_HIGH

        return risk, "; ".join(reasons)

    # =========================================================
    # Loyalty helpers
    # =========================================================
    def award_loyalty_points(phone, customer_name, amount_spent):
        account = LoyaltyAccount.query.filter_by(phone=phone).first()
        if not account:
            account = LoyaltyAccount(
                phone=phone,
                customer_name=customer_name,
                referral_code=("DANU" + uuid.uuid4().hex[:6].upper()),
                points=0,
                total_spent=0,
            )
            db.session.add(account)

        points = int((float(amount_spent) / 100) * app.config["LOYALTY_POINTS_PER_100_ETB"])
        current_points = account.points or 0
        current_spent = account.total_spent or 0
        account.points = current_points + points
        account.total_spent = current_spent + amount_spent
        account.customer_name = customer_name
        return points

    def award_review_bonus(phone, customer_name, bonus_points=15):
        """Flat loyalty bonus for leaving a review (Rule 4: reward feedback).
        Kept separate from spend-based points since it isn't tied to an order total."""
        if not phone:
            return 0
        account = LoyaltyAccount.query.filter_by(phone=phone).first()
        if not account:
            account = LoyaltyAccount(
                phone=phone,
                customer_name=customer_name or "Customer",
                referral_code=("DANU" + uuid.uuid4().hex[:6].upper()),
                points=0,
                total_spent=0,
            )
            db.session.add(account)
        account.points = (account.points or 0) + bonus_points
        if customer_name:
            account.customer_name = customer_name
        return bonus_points

    # =========================================================
    # Cart helpers (session-based cart, server-side validation on checkout)
    # =========================================================
    def get_cart():
        return session.get("cart", {})  # {product_id(str): quantity}

    def save_cart(cart):
        session["cart"] = cart
        session.modified = True

    # =========================================================
    # PUBLIC STOREFRONT ROUTES
    # =========================================================
    @app.route("/")
    def index():
        featured = (
            Product.query.filter_by(is_active=True, is_featured=True).limit(8).all()
        )
        categories = Category.query.all()
        return render_template("index.html", featured=featured, categories=categories)

    @app.route("/api/products")
    def api_products():
        """JSON endpoint used by Alpine.js to filter/search the catalog client-side."""
        query = Product.query.filter_by(is_active=True)

        category_slug = request.args.get("category")
        if category_slug and category_slug != "all":
            query = query.join(Category).filter(Category.slug == category_slug)

        search_term = request.args.get("q")
        if search_term:
            like_term = f"%{search_term}%"
            query = query.filter(
                db.or_(Product.name.ilike(like_term), Product.brand.ilike(like_term))
            )

        min_price = request.args.get("min_price", type=float)
        max_price = request.args.get("max_price", type=float)
        if min_price is not None:
            query = query.filter(Product.price >= min_price)
        if max_price is not None:
            query = query.filter(Product.price <= max_price)

        products = query.order_by(Product.created_at.desc()).all()

        new_arrival_cutoff = datetime.utcnow() - timedelta(days=14)
        result = []
        for p in products:
            result.append({
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "brand": p.brand,
                "description": p.description,
                "price": float(p.price),
                "discount_price": float(p.discount_price) if p.discount_price else None,
                "effective_price": float(p.effective_price),
                "stock": p.stock,
                "volume_ml": p.volume_ml,
                "image_url": media_url(p.image_filename) if p.image_filename else None,
                "gallery": [media_url(img.filename) for img in p.gallery_images],
                "category": p.category.name if p.category else None,
                "category_slug": p.category.slug if p.category else None,
                "top_notes": p.top_notes_list,
                "heart_notes": p.heart_notes_list,
                "base_notes": p.base_notes_list,
                "average_rating": p.average_rating,
                "review_count": len(p.approved_reviews),
                # part 4 of the review: lets the storefront show a "NEW" ribbon
                # on anything added in the last 14 days, without the client
                # needing to parse/compare timestamps itself.
                "is_new": bool(p.created_at and p.created_at >= new_arrival_cutoff),
            })
        return jsonify(result)

    @app.route("/api/product/<int:product_id>")
    def api_product_detail(product_id):
        """JSON endpoint for the fragrance-notes modal on the homepage."""
        p = Product.query.get_or_404(product_id)
        return jsonify({
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "brand": p.brand,
            "description": p.description,
            "price": float(p.price),
            "effective_price": float(p.effective_price),
            "volume_ml": p.volume_ml,
            "image_url": media_url(p.image_filename) if p.image_filename else None,
            "gallery": [media_url(img.filename) for img in p.gallery_images],
            "top_notes": p.top_notes_list,
            "heart_notes": p.heart_notes_list,
            "base_notes": p.base_notes_list,
            "average_rating": p.average_rating,
            "reviews": [
                {
                    "customer_name": r.customer_name, "rating": r.rating, "comment": r.comment,
                    "longevity_rating": r.longevity_rating,
                    "scent_match_rating": r.scent_match_rating,
                    "packaging_rating": r.packaging_rating,
                    "delivery_rating": r.delivery_rating,
                    "photo_url": media_url(r.photo_filename) if r.photo_filename else None,
                    "admin_reply": r.admin_reply,
                }
                for r in p.approved_reviews
            ],
        })

    @app.route("/api/product/<int:product_id>/review", methods=["POST"])
    def api_product_review_submit(product_id):
        """Customers submit a review; it stays hidden until an admin approves it.

        Accepts multipart/form-data so an optional 'verified purchase' photo can
        travel alongside the text fields (Rule 3). Sub-ratings for longevity,
        scent match, and packaging are optional (Rule 2); delivery experience is
        rated separately from the product itself (Rule 7).
        """
        product = Product.query.get_or_404(product_id)
        data = request.form if request.form else (request.get_json(silent=True) or {})

        customer_name = (data.get("customer_name") or "").strip()
        customer_phone = (data.get("customer_phone") or "").strip()
        comment = (data.get("comment") or "").strip()

        def _clean_sub_rating(field):
            raw = data.get(field)
            if raw in (None, ""):
                return None
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return None
            return value if 1 <= value <= 5 else None

        try:
            rating = int(data.get("rating", 5))
        except (TypeError, ValueError):
            rating = 5

        if not customer_name or rating < 1 or rating > 5:
            return jsonify({"error": "Please provide your name and a rating between 1 and 5."}), 400

        # Rule 5: require a minimum amount of detail so reviews stay useful,
        # rather than allowing drive-by "good" / "nice" spam entries.
        if len(comment) < 15:
            return jsonify({"error": "Please share a few more words about your experience (at least 15 characters)."}), 400

        photo_filename = None
        photo_file = request.files.get("photo") if request.files else None
        if photo_file and photo_file.filename:
            photo_filename = save_uploaded_file(photo_file, subfolder="reviews")

        review = Review(
            product_id=product.id, customer_name=customer_name,
            rating=rating, comment=comment, is_approved=False,
            longevity_rating=_clean_sub_rating("longevity_rating"),
            scent_match_rating=_clean_sub_rating("scent_match_rating"),
            packaging_rating=_clean_sub_rating("packaging_rating"),
            delivery_rating=_clean_sub_rating("delivery_rating"),
            photo_filename=photo_filename,
        )
        db.session.add(review)

        bonus = 0
        if customer_phone:
            # Rule 4: reward feedback with loyalty points, regardless of order total.
            bonus = award_review_bonus(customer_phone, customer_name)

        db.session.commit()

        message = "Thank you! Your review will appear once approved."
        if bonus:
            message += f" You've earned {bonus} loyalty points for sharing your feedback."
        return jsonify({"success": True, "message": message, "bonus_points": bonus})

    @app.route("/api/report-issue", methods=["POST"])
    def api_report_issue():
        """Rule 8: a delivery/order problem report, separate from the star-review flow,
        so a customer with a real problem reaches support directly instead of only
        leaving a public low rating with nowhere for it to go."""
        data = request.get_json(silent=True) or {}
        order_code = (data.get("order_code") or "").strip().upper()
        phone = (data.get("phone") or "").strip()
        issue_type = (data.get("issue_type") or "other").strip()
        description = (data.get("description") or "").strip()

        if not order_code or not phone:
            return jsonify({"error": "Please provide your order code and phone number."}), 400
        if len(description) < 10:
            return jsonify({"error": "Please describe the issue in a bit more detail (at least 10 characters)."}), 400

        order = Order.query.filter_by(order_code=order_code, customer_phone=phone).first()
        if not order:
            return jsonify({"error": "We couldn't find an order matching that code and phone number."}), 404

        report = OrderIssueReport(
            order_id=order.id,
            order_code=order.order_code,
            customer_name=order.customer_name,
            customer_phone=phone,
            issue_type=issue_type,
            description=description,
            status="Open",
        )
        db.session.add(report)
        db.session.commit()
        log_activity("issue_report.create", f"{order.order_code} — {issue_type}")

        try:
            send_telegram_message(
                "⚠️ <b>Order Issue Reported</b>\n"
                f"Order: <b>{order.order_code}</b>\n"
                f"Customer: {order.customer_name} ({mask_phone(phone)})\n"
                f"Type: {issue_type.replace('_', ' ').title()}\n"
                f"Details: {description}"
            )
        except Exception:  # noqa: BLE001
            pass

        return jsonify({"success": True, "message": "Thank you — our team will reach out about your order shortly."})

    @app.route("/api/product/<int:product_id>/notify-me", methods=["POST"])
    def api_stock_alert_signup(product_id):
        """'Notify me when back in stock' signup for an out-of-stock product."""
        product = Product.query.get_or_404(product_id)
        data = request.get_json(silent=True) or {}
        phone = (data.get("phone") or "").strip()

        if not phone:
            return jsonify({"error": "Phone number is required."}), 400

        existing = StockAlert.query.filter_by(product_id=product.id, phone=phone, notified=False).first()
        if not existing:
            db.session.add(StockAlert(product_id=product.id, phone=phone))
            db.session.commit()

        return jsonify({"success": True, "message": "We'll notify you when this is back in stock."})

    # --- Order Tracking (public, no login required) ---
    @app.route("/track", methods=["GET", "POST"])
    def track_order():
        order = None
        if request.method == "POST":
            code = request.form.get("order_code", "").strip().upper()
            phone = request.form.get("phone", "").strip()
            order = Order.query.filter_by(order_code=code, customer_phone=phone).first()
            if not order:
                flash("No matching order found. Please check your order code and phone number.", "error")
        return render_template("track_order.html", order=order)

    # --- Cart API (session-based, used by Alpine.js) ---
    @app.route("/api/cart", methods=["GET"])
    def api_cart_get():
        cart = get_cart()
        items = []
        total = Decimal("0")
        for product_id_str, qty in cart.items():
            product = db.session.get(Product, int(product_id_str))
            if not product:
                continue
            subtotal = product.effective_price * qty
            total += subtotal
            items.append({
                "product_id": product.id,
                "name": product.name,
                "price": float(product.effective_price),
                "quantity": qty,
                "subtotal": float(subtotal),
                "image_url": media_url(product.image_filename) if product.image_filename else None,
                "stock": product.stock,
            })
        return jsonify({"items": items, "total": float(total)})

    @app.route("/api/cart/add", methods=["POST"])
    def api_cart_add():
        data = request.get_json(silent=True) or {}
        product_id = str(data.get("product_id", ""))
        quantity = int(data.get("quantity", 1))

        product = db.session.get(Product, int(product_id)) if product_id.isdigit() else None
        if not product or not product.is_active:
            return jsonify({"error": "Product not found"}), 404

        cart = get_cart()
        current_qty = cart.get(product_id, 0)
        new_qty = min(current_qty + quantity, max(product.stock, 0)) if product.stock else current_qty + quantity
        cart[product_id] = new_qty if new_qty > 0 else 1
        save_cart(cart)
        return jsonify({"success": True, "cart_count": sum(cart.values())})

    @app.route("/api/cart/update", methods=["POST"])
    def api_cart_update():
        data = request.get_json(silent=True) or {}
        product_id = str(data.get("product_id", ""))
        quantity = int(data.get("quantity", 1))

        cart = get_cart()
        if product_id in cart:
            if quantity <= 0:
                cart.pop(product_id)
            else:
                cart[product_id] = quantity
            save_cart(cart)
        return jsonify({"success": True, "cart_count": sum(cart.values())})

    @app.route("/api/cart/remove", methods=["POST"])
    def api_cart_remove():
        data = request.get_json(silent=True) or {}
        product_id = str(data.get("product_id", ""))
        cart = get_cart()
        cart.pop(product_id, None)
        save_cart(cart)
        return jsonify({"success": True, "cart_count": sum(cart.values())})

    @app.route("/api/coupon/validate", methods=["POST"])
    def api_coupon_validate():
        """Validates a coupon code against the current cart subtotal (used live in checkout.html)."""
        data = request.get_json(silent=True) or {}
        code = (data.get("code") or "").strip().upper()

        cart = get_cart()
        subtotal = Decimal("0")
        for product_id_str, qty in cart.items():
            product = db.session.get(Product, int(product_id_str))
            if product:
                subtotal += product.effective_price * qty

        coupon = Coupon.query.filter_by(code=code).first()
        if not coupon or not coupon.is_valid():
            return jsonify({"valid": False, "message": "This coupon is invalid or has expired."}), 400

        discount = coupon.calculate_discount(subtotal)
        return jsonify({
            "valid": True,
            "code": coupon.code,
            "discount": float(discount),
            "new_total": float(subtotal - discount),
        })

    # --- Post Office Directory (database-backed, scales to thousands of branches) ---
    @app.route("/post-offices")
    def post_offices():
        query = request.args.get("query", "").strip()
        offices_query = PostOffice.query.filter_by(is_active=True)
        if query:
            like_term = f"%{query}%"
            offices_query = offices_query.filter(
                db.or_(
                    PostOffice.name.ilike(like_term),
                    PostOffice.city.ilike(like_term),
                    PostOffice.region.ilike(like_term),
                    PostOffice.address.ilike(like_term),
                    PostOffice.postal_code.ilike(like_term),
                )
            )
        offices = offices_query.order_by(PostOffice.city, PostOffice.name).limit(500).all()
        total_count = PostOffice.query.filter_by(is_active=True).count()
        return render_template("post_offices.html", offices=offices, query=query, total_count=total_count)

    @app.route("/api/post-offices")
    def api_post_offices():
        """Live search endpoint used by the autocomplete picker at checkout. Returns
        at most 20 matches — safe to use even with a 1000+ branch directory."""
        query = request.args.get("query", "").strip()
        offices_query = PostOffice.query.filter_by(is_active=True)
        if query:
            like_term = f"%{query}%"
            offices_query = offices_query.filter(
                db.or_(
                    PostOffice.name.ilike(like_term),
                    PostOffice.city.ilike(like_term),
                    PostOffice.region.ilike(like_term),
                )
            )
        offices = offices_query.order_by(PostOffice.city, PostOffice.name).limit(20).all()
        return jsonify({
            "results": [
                {"name": o.name, "city": o.city, "region": o.region, "postal_code": o.postal_code, "address": o.address}
                for o in offices
            ]
        })

    # --- Checkout ---
    @app.route("/checkout", methods=["GET", "POST"])
    def checkout():
        cart = get_cart()

        if not cart:
            flash("Your cart is empty.", "warning")
            return redirect(url_for("index"))

        line_items = []
        subtotal = Decimal("0")
        for product_id_str, qty in cart.items():
            product = db.session.get(Product, int(product_id_str))
            if not product:
                continue
            item_subtotal = product.effective_price * qty
            subtotal += item_subtotal
            line_items.append({"product": product, "quantity": qty, "subtotal": item_subtotal})

        banks = Bank.query.filter_by(is_active=True).order_by(Bank.sort_order).all()
        delivery_options = [Order.DELIVERY_STANDARD, Order.DELIVERY_MOTORCYCLE, Order.DELIVERY_PICKUP]

        # Roll the delivery fee only once per checkout session — reloading the page,
        # switching language, or re-rendering after a validation error must NOT
        # change the quoted price. It's cleared once the order is actually placed.
        if "checkout_delivery_fee" not in session:
            session["checkout_delivery_fee"] = str(roll_delivery_fee())
        proposed_fee = Decimal(session["checkout_delivery_fee"])

        if request.method == "POST":
            customer_name = request.form.get("customer_name", "").strip()
            customer_phone = request.form.get("customer_phone", "").strip()
            delivery_address = request.form.get("delivery_address", "").strip()
            city = request.form.get("city", "").strip()
            post_office_location = request.form.get("post_office_location", "").strip()
            delivery_type = request.form.get("delivery_type", Order.DELIVERY_STANDARD)
            notes = request.form.get("notes", "").strip()
            payment_method = request.form.get("payment_method", "Telebirr")
            bank_id = request.form.get("bank_id", type=int)
            coupon_code = request.form.get("coupon_code", "").strip().upper()
            is_gift = bool(request.form.get("is_gift"))
            gift_message = request.form.get("gift_message", "").strip()
            delivery_fee_raw = request.form.get("delivery_fee", "")

            errors = []
            if not customer_name:
                errors.append("Full name is required.")
            if not customer_phone:
                errors.append("Phone number is required.")
            if not delivery_address:
                errors.append("Delivery address is required.")
            if not city:
                errors.append("City is required.")

            receipt_file = request.files.get("payment_screenshot")
            if not receipt_file or receipt_file.filename == "":
                errors.append("Payment screenshot is required.")
            elif not allowed_file(receipt_file.filename):
                errors.append("Invalid file type. Please upload a JPG, PNG, WEBP or GIF image.")

            try:
                fee_decimal = Decimal(delivery_fee_raw) if delivery_fee_raw else resolve_delivery_fee(city)
            except InvalidOperation:
                fee_decimal = resolve_delivery_fee(city)

            # Coupon validation (server-side, authoritative)
            discount_amount = Decimal("0")
            applied_coupon = None
            if coupon_code:
                applied_coupon = Coupon.query.filter_by(code=coupon_code).first()
                if applied_coupon and applied_coupon.is_valid():
                    discount_amount = applied_coupon.calculate_discount(subtotal)
                else:
                    errors.append("The coupon code entered is invalid or expired.")

            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template(
                    "checkout.html", line_items=line_items, subtotal=subtotal,
                    banks=banks, delivery_options=delivery_options, proposed_fee=proposed_fee,
                )

            receipt_filename = save_uploaded_file(receipt_file, subfolder="receipts")
            grand_total = subtotal - discount_amount + fee_decimal

            risk_level, risk_reasons = score_order_risk(customer_phone, grand_total)
            points = award_loyalty_points(customer_phone, customer_name, grand_total)

            new_order = Order(
                order_code=generate_order_code(),
                customer_id=current_user.id if isinstance(current_user, Customer) else None,
                customer_name=customer_name,
                customer_phone=customer_phone,
                delivery_address=delivery_address,
                city=city,
                post_office_location=post_office_location,
                delivery_type=delivery_type,
                notes=notes,
                is_gift=is_gift,
                gift_message=gift_message if is_gift else None,
                payment_method=payment_method,
                bank_id=bank_id if bank_id else None,
                payment_screenshot=receipt_filename,
                coupon_code=applied_coupon.code if applied_coupon else None,
                discount_amount=discount_amount,
                subtotal_amount=subtotal,
                delivery_fee=fee_decimal,
                total_amount=grand_total,
                points_earned=points,
                risk_level=risk_level,
                risk_reasons=risk_reasons,
                status=Order.STATUS_PENDING,
            )
            db.session.add(new_order)
            if isinstance(current_user, Customer) and not current_user.phone:
                current_user.phone = customer_phone
            db.session.flush()

            for item in line_items:
                db.session.add(OrderItem(
                    order_id=new_order.id,
                    product_id=item["product"].id,
                    product_name=item["product"].name,
                    unit_price=item["product"].effective_price,
                    quantity=item["quantity"],
                ))
                item["product"].stock = max(item["product"].stock - item["quantity"], 0)

            if applied_coupon:
                applied_coupon.used_count += 1

            db.session.commit()
            try:
                notify_new_order_telegram(new_order)
            except Exception:  # noqa: BLE001
                pass  # a notification failure must never break checkout
            save_cart({})
            session.pop("checkout_delivery_fee", None)

            return render_template("checkout.html", order_success=True, order=new_order)

        return render_template(
            "checkout.html", line_items=line_items, subtotal=subtotal,
            banks=banks, delivery_options=delivery_options, proposed_fee=proposed_fee,
        )

    # =========================================================
    # CUSTOMER ACCOUNT ROUTES (optional login on top of guest checkout)
    # =========================================================
    def _username_is_taken(username):
        """
        UPDATED (per request): usernames are no longer specially 'reserved' —
        that gave a confusing warning even when the name was free. Instead this
        checks both the admin (`users`) and customer (`customers`) tables, so a
        username shows as taken the normal way once it's actually in use by
        either account type — including after Danuta/Tofik register their own
        admin accounts with their own strong passwords.
        """
        normalized = (username or "").strip().lower()
        if not normalized:
            return False
        if User.query.filter(func.lower(User.username) == normalized).first():
            return True
        if Customer.query.filter(func.lower(Customer.username) == normalized).first():
            return True
        return False

    @app.route("/register", methods=["GET", "POST"])
    def customer_register():
        if current_user.is_authenticated:
            return redirect(url_for("customer_account") if isinstance(current_user, Customer) else url_for("admin_dashboard"))

        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            errors = []
            if not full_name:
                errors.append("Full name is required.")
            if not username or len(username) < 3:
                errors.append("Username must be at least 3 characters.")
            elif _username_is_taken(username):
                errors.append("That username is already taken — please choose another.")
            if len(password) < 6:
                errors.append("Password must be at least 6 characters.")
            if password != confirm_password:
                errors.append("Passwords do not match.")

            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template("register.html", full_name=full_name, username=username)

            customer = Customer(full_name=full_name, username=username)
            customer.set_password(password)
            db.session.add(customer)
            try:
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()
                flash("Unable to create your account right now. Please try again.", "error")
                return render_template("register.html", full_name=full_name, username=username)

            login_user(customer)
            flash(f"Welcome to Danu Perfume & Cosmo, {full_name}!", "success")
            return redirect(url_for("index"))

        return render_template("register.html")

    @app.route("/api/check-username")
    def api_check_username():
        """Live availability check used while typing on the register form."""
        username = request.args.get("username", "").strip()
        if len(username) < 3:
            return jsonify({"available": False, "reason": "too_short"})
        taken = _username_is_taken(username)
        return jsonify({"available": not taken, "reason": "taken" if taken else None})

    @app.route("/admin/login")
    def admin_login_redirect():
        return redirect(url_for("customer_login"))

    @app.route("/login", methods=["GET", "POST"])
    def customer_login():
        if current_user.is_authenticated:
            if isinstance(current_user, User):
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("customer_account"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            user = User.query.filter(func.lower(User.username) == username.lower()).first()
            if user and user.check_password(password):
                login_user(user)
                log_activity("auth.login", f"{username} logged in")
                flash("Welcome back!", "success")
                next_page = request.args.get("next")
                return redirect(next_page or url_for("admin_dashboard"))

            customer = Customer.query.filter(func.lower(Customer.username) == username.lower()).first()
            if customer and customer.check_password(password):
                login_user(customer)
                flash(f"Welcome back, {customer.full_name}!", "success")
                next_page = request.args.get("next")
                return redirect(next_page or url_for("customer_account"))

            flash("Invalid username or password.", "error")

        return render_template("customer_login.html")

    @app.route("/logout")
    @login_required
    def customer_logout():
        logout_user()
        flash("You've been logged out.", "success")
        return redirect(url_for("customer_login"))

    @app.route("/account")
    @login_required
    def customer_account():
        orders = []
        loyalty = None
        loyalty_progress = 0
        loyalty_remaining = 0
        if isinstance(current_user, Customer):
            orders = Order.query.filter_by(customer_id=current_user.id).order_by(Order.created_at.desc()).all()
            if current_user.phone:
                loyalty = LoyaltyAccount.query.filter_by(phone=current_user.phone).first()
                if loyalty:
                    milestone = 500  # points per reward tier
                    into_tier = (loyalty.points or 0) % milestone
                    loyalty_progress = round((into_tier / milestone) * 100, 1)
                    loyalty_remaining = milestone - into_tier
        return render_template(
            "account.html",
            orders=orders,
            loyalty=loyalty,
            loyalty_progress=loyalty_progress,
            loyalty_remaining=loyalty_remaining,
        )

    # BUG FIX: this route used to be indented one level too deep, nested inside
    # customer_account() and placed AFTER its `return` — meaning Flask never
    # registered it at all, so the "Save" button on Profile Settings 404'd.
    # It's now a normal top-level route like every other @app.route.
    @app.route("/account/settings", methods=["POST"])
    @login_required
    def update_account_settings():
        if not isinstance(current_user, Customer):
            flash("Only customers can update these settings.", "error")
            return redirect(url_for("customer_account"))

        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        preferred_language = request.form.get("preferred_language")

        if full_name:
            current_user.full_name = full_name
        current_user.phone = phone or None
        current_user.preferred_language = preferred_language or None

        try:
            db.session.add(current_user)
            db.session.commit()
            # Also update session language immediately if changed
            if preferred_language:
                session["lang"] = preferred_language
            flash("Profile settings saved.", "success")
        except Exception:  # noqa: BLE001
            db.session.rollback()
            flash("Could not save settings — please try again.", "error")

        return redirect(url_for("customer_account"))

    @app.route("/change-password", methods=["GET", "POST"])
    @login_required
    def change_password():
        """Allow customers and admins to change their password securely."""
        if not isinstance(current_user, (Customer, User)):
            flash("You must be logged in to change your password.", "error")
            return redirect(url_for("customer_login"))

        if request.method == "POST":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            errors = []

            # Validate current password
            if not current_password:
                errors.append("Current password is required.")
            elif not current_user.check_password(current_password):
                errors.append("Current password is incorrect.")

            # Validate new password
            if not new_password:
                errors.append("New password is required.")
            elif len(new_password) < 6:
                errors.append("New password must be at least 6 characters.")

            # Validate password confirmation
            if new_password != confirm_password:
                errors.append("New passwords do not match.")

            # Prevent reusing the current password
            if current_password and new_password and current_user.check_password(new_password):
                errors.append("New password must be different from your current password.")

            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template("change_password.html")

            # Update the password
            try:
                current_user.set_password(new_password)
                db.session.add(current_user)
                db.session.commit()

                # Log the activity
                if isinstance(current_user, User):
                    log_activity("auth.password_change", f"{current_user.username} changed password")

                flash("Your password has been changed successfully.", "success")
                return redirect(url_for("customer_account"))
            except Exception:  # noqa: BLE001
                db.session.rollback()
                flash("Could not update password — please try again.", "error")
                return render_template("change_password.html")

        return render_template("change_password.html")

    # =========================================================
    # ADMIN ROUTES
    # =========================================================
    @app.route("/admin/logout")
    @admin_required
    def admin_logout():
        log_activity("auth.logout", f"{current_user.username} logged out")
        logout_user()
        flash("You have been logged out.", "success")
        return redirect(url_for("customer_login"))

    @app.route("/admin")
    @app.route("/admin/dashboard")
    @admin_required
    def admin_dashboard():
        total_orders = Order.query.count()
        pending_orders = Order.query.filter_by(status=Order.STATUS_PENDING).count()
        total_products = Product.query.count()
        total_sales = db.session.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(
            Order.status != Order.STATUS_CANCELLED
        ).scalar()

        recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
        low_stock_products = Product.query.filter(Product.stock <= 5).limit(5).all()
        high_risk_orders = Order.query.filter_by(risk_level=Order.RISK_HIGH).order_by(Order.created_at.desc()).limit(5).all()

        return render_template(
            "admin_dashboard.html",
            total_orders=total_orders,
            pending_orders=pending_orders,
            total_products=total_products,
            total_sales=total_sales,
            recent_orders=recent_orders,
            low_stock_products=low_stock_products,
            high_risk_orders=high_risk_orders,
            view="overview",
        )

    # --- Analytics ---
    @app.route("/admin/analytics")
    @admin_required
    def admin_analytics():
        return render_template("admin_dashboard.html", view="analytics")

    @app.route("/admin/analytics/sales-data")
    @admin_required
    def admin_analytics_data():
        """JSON data (last 14 days) consumed by Chart.js on the analytics view."""
        days = []
        totals = []
        for i in range(13, -1, -1):
            day = (datetime.utcnow() - timedelta(days=i)).date()
            day_total = db.session.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(
                func.date(Order.created_at) == day,
                Order.status != Order.STATUS_CANCELLED,
            ).scalar()
            days.append(day.strftime("%b %d"))
            totals.append(float(day_total))

        top_products = (
            db.session.query(OrderItem.product_name, func.sum(OrderItem.quantity).label("qty"))
            .group_by(OrderItem.product_name)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(5)
            .all()
        )
        top_customers = (
            db.session.query(Order.customer_phone, Order.customer_name, func.sum(Order.total_amount).label("spent"))
            .filter(Order.status != Order.STATUS_CANCELLED)
            .group_by(Order.customer_phone, Order.customer_name)
            .order_by(func.sum(Order.total_amount).desc())
            .limit(5)
            .all()
        )

        return jsonify({
            "labels": days,
            "sales": totals,
            "top_products": [{"name": n, "qty": int(q)} for n, q in top_products],
            "top_customers": [{"name": n, "phone": p, "spent": float(s)} for p, n, s in top_customers],
        })

    # --- Activity Log ---
    @app.route("/admin/activity-log")
    @super_admin_required
    def admin_activity_log():
        logs = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(200).all()
        return render_template("admin_dashboard.html", view="activity_log", logs=logs)

    # --- Settings (Telegram order notifications + public support username) ---
    @app.route("/admin/settings", methods=["GET", "POST"])
    @super_admin_required
    def admin_settings():
        if request.method == "POST":
            chat_id = request.form.get("telegram_chat_id", "").strip()
            support_username = request.form.get("telegram_support_username", "").strip().lstrip("@")
            set_setting("telegram_chat_id", chat_id)
            set_setting("telegram_support_username", support_username)
            log_activity("settings.update", "Telegram settings updated")
            flash("Settings saved.", "success")
            return redirect(url_for("admin_settings"))

        return render_template(
            "admin_dashboard.html", view="settings",
            telegram_chat_id=get_setting("telegram_chat_id", ""),
            telegram_support_username=get_setting("telegram_support_username", ""),
        )

    @app.route("/admin/settings/telegram-test", methods=["POST"])
    @super_admin_required
    def admin_settings_telegram_test():
        ok = send_telegram_message("✅ Danu Perfume & Cosmo — test notification. Your Telegram alerts are working.")
        flash("Test message sent — check Telegram." if ok else
              "Couldn't send the test message. Double-check the Chat ID and that you've messaged the bot at least once.",
              "success" if ok else "error")
        return redirect(url_for("admin_settings"))

    # --- Product CRUD ---
    @app.route("/admin/products")
    @admin_required
    def admin_products():
        products = Product.query.order_by(Product.created_at.desc()).all()
        categories = Category.query.all()
        return render_template(
            "admin_dashboard.html",
            view="products",
            products=products,
            categories=categories,
        )

    @app.route("/admin/products/new", methods=["GET", "POST"])
    @super_admin_required
    def admin_product_new():
        categories = Category.query.all()

        if request.method == "POST":
            product, error = _build_product_from_form(request, categories)
            if error:
                flash(error, "error")
                return render_template("admin_dashboard.html", view="product_form", categories=categories, product=None)

            db.session.add(product)
            db.session.commit()
            _save_gallery_images(product)
            log_activity("product.create", product.name)
            flash("Product created successfully.", "success")
            return redirect(url_for("admin_products"))

        return render_template("admin_dashboard.html", view="product_form", categories=categories, product=None)

    @app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
    @super_admin_required
    def admin_product_edit(product_id):
        product = Product.query.get_or_404(product_id)
        categories = Category.query.all()

        if request.method == "POST":
            updated, error = _build_product_from_form(request, categories, existing=product)
            if error:
                flash(error, "error")
                return render_template("admin_dashboard.html", view="product_form", categories=categories, product=product)

            db.session.commit()
            _save_gallery_images(product)
            log_activity("product.update", product.name)
            flash("Product updated successfully.", "success")
            return redirect(url_for("admin_products"))

        return render_template("admin_dashboard.html", view="product_form", categories=categories, product=product)

    @app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
    @super_admin_required
    def admin_product_delete(product_id):
        product = Product.query.get_or_404(product_id)
        log_activity("product.delete", product.name)
        db.session.delete(product)
        db.session.commit()
        flash("Product deleted.", "success")
        return redirect(url_for("admin_products"))

    def _save_gallery_images(product):
        """Handles the multi-file 'gallery_images' input for a Product form."""
        files = request.files.getlist("gallery_images")
        next_sort = len(product.gallery_images)
        for f in files:
            if f and f.filename:
                saved = save_uploaded_file(f, subfolder="products")
                if saved:
                    db.session.add(ProductImage(product_id=product.id, filename=saved, sort_order=next_sort))
                    next_sort += 1
        db.session.commit()

    @app.route("/admin/products/gallery/<int:image_id>/delete", methods=["POST"])
    @super_admin_required
    def admin_product_gallery_delete(image_id):
        image = ProductImage.query.get_or_404(image_id)
        product_id = image.product_id
        db.session.delete(image)
        db.session.commit()
        return redirect(url_for("admin_product_edit", product_id=product_id))

    def _build_product_from_form(req, categories, existing=None):
        """Shared logic to create/update a Product from a submitted form."""
        name = req.form.get("name", "").strip()
        sku = req.form.get("sku", "").strip() or None
        brand = req.form.get("brand", "").strip()
        description = req.form.get("description", "").strip()
        category_id = req.form.get("category_id")
        volume_ml = req.form.get("volume_ml", type=int) or 50
        stock = req.form.get("stock", type=int) or 0
        top_notes = req.form.get("top_notes", "").strip()
        heart_notes = req.form.get("heart_notes", "").strip()
        base_notes = req.form.get("base_notes", "").strip()
        is_featured = bool(req.form.get("is_featured"))
        is_active = bool(req.form.get("is_active", "on"))

        if not name:
            return existing, "Product name is required."
        if not category_id:
            return existing, "Please select a category."

        try:
            price = Decimal(req.form.get("price", "0"))
        except InvalidOperation:
            return existing, "Invalid price value."

        discount_raw = req.form.get("discount_price", "").strip()
        discount_price = None
        if discount_raw:
            try:
                discount_price = Decimal(discount_raw)
            except InvalidOperation:
                return existing, "Invalid discount price value."

        product = existing or Product()
        product.name = name
        product.sku = sku
        product.brand = brand
        product.description = description
        product.category_id = int(category_id)
        product.price = price
        product.discount_price = discount_price
        product.stock = stock
        product.volume_ml = volume_ml
        product.top_notes = top_notes
        product.heart_notes = heart_notes
        product.base_notes = base_notes
        product.is_featured = is_featured
        product.is_active = is_active

        image_file = req.files.get("image")
        if image_file and image_file.filename:
            saved_name = save_uploaded_file(image_file, subfolder="products")
            if saved_name:
                product.image_filename = saved_name

        return product, None

    # --- Bulk CSV Import ---
    @app.route("/admin/products/import", methods=["GET", "POST"])
    @super_admin_required
    def admin_products_import():
        categories = {c.slug: c for c in Category.query.all()}

        if request.method == "POST":
            csv_file = request.files.get("csv_file")
            if not csv_file or not csv_file.filename.lower().endswith(".csv"):
                flash("Please upload a valid .csv file.", "error")
                return render_template("admin_dashboard.html", view="products_import")

            stream = io.StringIO(csv_file.stream.read().decode("utf-8-sig"))
            reader = csv.DictReader(stream)

            created, skipped = 0, 0
            for row in reader:
                name = (row.get("name") or "").strip()
                category_slug = (row.get("category_slug") or "").strip()
                if not name or category_slug not in categories:
                    skipped += 1
                    continue

                try:
                    price = Decimal(row.get("price") or "0")
                except InvalidOperation:
                    skipped += 1
                    continue

                product = Product(
                    name=name,
                    sku=(row.get("sku") or "").strip() or None,
                    brand=(row.get("brand") or "").strip(),
                    description=(row.get("description") or "").strip(),
                    price=price,
                    stock=int(row.get("stock") or 0),
                    volume_ml=int(row.get("volume_ml") or 50),
                    top_notes=(row.get("top_notes") or "").strip(),
                    heart_notes=(row.get("heart_notes") or "").strip(),
                    base_notes=(row.get("base_notes") or "").strip(),
                    category_id=categories[category_slug].id,
                    is_active=True,
                )
                db.session.add(product)
                created += 1

            db.session.commit()
            log_activity("product.bulk_import", f"{created} created, {skipped} skipped")
            flash(f"Import complete: {created} products created, {skipped} rows skipped.", "success")
            return redirect(url_for("admin_products"))

        return render_template("admin_dashboard.html", view="products_import")

    @app.route("/admin/products/import/template.csv")
    @admin_required
    def admin_products_import_template():
        header = "name,sku,brand,description,price,stock,volume_ml,top_notes,heart_notes,base_notes,category_slug\n"
        example = 'Golden Oud,DP-001,Danu,"A rich oud fragrance",1200,20,50,"Bergamot, Saffron","Oud, Rose","Amber, Musk",oud-attar\n'
        return Response(header + example, mimetype="text/csv", headers={
            "Content-Disposition": "attachment; filename=danu_product_import_template.csv"
        })

    # --- Reviews Moderation ---
    @app.route("/admin/reviews")
    @admin_required
    def admin_reviews():
        pending = Review.query.filter_by(is_approved=False).order_by(Review.created_at.desc()).all()
        approved = Review.query.filter_by(is_approved=True).order_by(Review.created_at.desc()).limit(50).all()
        return render_template("admin_dashboard.html", view="reviews", pending=pending, approved=approved)

    @app.route("/admin/reviews/<int:review_id>/approve", methods=["POST"])
    @admin_required
    def admin_review_approve(review_id):
        review = Review.query.get_or_404(review_id)
        review.is_approved = True
        db.session.commit()
        log_activity("review.approve", f"{review.product.name} by {review.customer_name}")
        flash("Review approved and published.", "success")
        return redirect(url_for("admin_reviews"))

    @app.route("/admin/reviews/<int:review_id>/delete", methods=["POST"])
    @admin_required
    def admin_review_delete(review_id):
        review = Review.query.get_or_404(review_id)
        db.session.delete(review)
        db.session.commit()
        flash("Review deleted.", "success")
        return redirect(url_for("admin_reviews"))

    @app.route("/admin/reviews/<int:review_id>/reply", methods=["POST"])
    @admin_required
    def admin_review_reply(review_id):
        """Rule 6: let the brand publicly reply under a published review."""
        review = Review.query.get_or_404(review_id)
        reply_text = (request.form.get("admin_reply") or "").strip()
        review.admin_reply = reply_text or None
        review.admin_reply_at = datetime.utcnow() if reply_text else None
        db.session.commit()
        log_activity("review.reply", f"{review.product.name} by {review.customer_name}")
        flash("Reply saved.", "success")
        return redirect(url_for("admin_reviews"))

    # --- Order Issue Reports (Rule 8) ---
    @app.route("/admin/issue-reports")
    @admin_required
    def admin_issue_reports():
        open_reports = OrderIssueReport.query.filter(OrderIssueReport.status != "Resolved") \
            .order_by(OrderIssueReport.created_at.desc()).all()
        resolved_reports = OrderIssueReport.query.filter_by(status="Resolved") \
            .order_by(OrderIssueReport.created_at.desc()).limit(50).all()
        return render_template("admin_dashboard.html", view="issue_reports",
                                open_reports=open_reports, resolved_reports=resolved_reports)

    @app.route("/admin/issue-reports/<int:report_id>/resolve", methods=["POST"])
    @admin_required
    def admin_issue_report_resolve(report_id):
        report = OrderIssueReport.query.get_or_404(report_id)
        report.status = "Resolved"
        db.session.commit()
        log_activity("issue_report.resolve", f"{report.order_code}")
        flash("Issue marked as resolved.", "success")
        return redirect(url_for("admin_issue_reports"))

    # --- Stock Alerts ---
    @app.route("/admin/stock-alerts")
    @admin_required
    def admin_stock_alerts():
        alerts = (
            StockAlert.query.filter_by(notified=False)
            .join(Product)
            .order_by(StockAlert.created_at.desc())
            .all()
        )
        return render_template("admin_dashboard.html", view="stock_alerts", alerts=alerts)

    @app.route("/admin/stock-alerts/<int:alert_id>/mark-notified", methods=["POST"])
    @admin_required
    def admin_stock_alert_mark_notified(alert_id):
        alert = StockAlert.query.get_or_404(alert_id)
        alert.notified = True
        db.session.commit()
        return redirect(url_for("admin_stock_alerts"))

    # --- Order Management ---
    @app.route("/admin/orders")
    @admin_required
    def admin_orders():
        status_filter = request.args.get("status")
        query = Order.query
        if status_filter and status_filter != "all":
            query = query.filter_by(status=status_filter)
        orders = query.order_by(Order.created_at.desc()).all()
        return render_template(
            "admin_dashboard.html",
            view="orders",
            orders=orders,
            status_filter=status_filter or "all",
            statuses=[
                Order.STATUS_PENDING, Order.STATUS_APPROVED,
                Order.STATUS_OUT_FOR_DELIVERY, Order.STATUS_DELIVERED,
                Order.STATUS_CANCELLED,
            ],
        )

    @app.route("/admin/orders/<int:order_id>")
    @admin_required
    def admin_order_detail(order_id):
        order = Order.query.get_or_404(order_id)
        return render_template(
            "admin_dashboard.html",
            view="order_detail",
            order=order,
            statuses=[
                Order.STATUS_PENDING, Order.STATUS_APPROVED,
                Order.STATUS_OUT_FOR_DELIVERY, Order.STATUS_DELIVERED,
                Order.STATUS_CANCELLED,
            ],
        )

    @app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
    @admin_required
    def admin_order_update_status(order_id):
        order = Order.query.get_or_404(order_id)
        new_status = request.form.get("status")

        valid_statuses = {
            Order.STATUS_PENDING, Order.STATUS_APPROVED,
            Order.STATUS_OUT_FOR_DELIVERY, Order.STATUS_DELIVERED,
            Order.STATUS_CANCELLED,
        }
        if new_status in valid_statuses:
            order.status = new_status
            db.session.commit()
            log_activity("order.status_update", f"{order.order_code} -> {new_status}")
            flash(f"Order {order.order_code} updated to {new_status}.", "success")
        else:
            flash("Invalid status.", "error")

        return redirect(url_for("admin_order_detail", order_id=order.id))

    @app.route("/admin/orders/<int:order_id>/delivery-fee", methods=["POST"])
    @admin_required
    def admin_order_update_delivery_fee(order_id):
        order = Order.query.get_or_404(order_id)

        try:
            new_fee = Decimal(request.form.get("delivery_fee", "0"))
        except InvalidOperation:
            flash("Invalid delivery fee.", "error")
            return redirect(url_for("admin_order_detail", order_id=order.id))

        order.delivery_fee = new_fee
        order.total_amount = order.subtotal_amount - order.discount_amount + new_fee
        order.delivery_type = request.form.get("delivery_type", order.delivery_type)
        order.rider_name = request.form.get("rider_name", "").strip() or None
        order.rider_phone = request.form.get("rider_phone", "").strip() or None
        db.session.commit()
        log_activity("order.delivery_update", order.order_code)
        flash("Delivery details updated.", "success")
        return redirect(url_for("admin_order_detail", order_id=order.id))

    @app.route("/admin/orders/<int:order_id>/invoice")
    @admin_required
    def admin_order_invoice(order_id):
        """Printable HTML invoice (use the browser's Print -> Save as PDF)."""
        order = Order.query.get_or_404(order_id)
        return render_template("invoice.html", order=order)

    # --- Bank / Payment Account Management ---
    @app.route("/admin/banks")
    @super_admin_required
    def admin_banks():
        banks = Bank.query.order_by(Bank.sort_order, Bank.created_at).all()
        return render_template("admin_dashboard.html", view="banks", banks=banks)

    @app.route("/admin/banks/new", methods=["GET", "POST"])
    @super_admin_required
    def admin_bank_new():
        if request.method == "POST":
            bank_name = request.form.get("bank_name", "").strip()
            account_name = request.form.get("account_name", "").strip()
            account_number = request.form.get("account_number", "").strip()
            sort_order = request.form.get("sort_order", type=int) or 0
            is_active = bool(request.form.get("is_active", "on"))

            if not bank_name or not account_name or not account_number:
                flash("Bank name, account name and account number are required.", "error")
                return render_template("admin_dashboard.html", view="bank_form", bank=None)

            logo_filename = None
            logo_file = request.files.get("logo")
            if logo_file and logo_file.filename:
                logo_filename = save_uploaded_file(logo_file, subfolder="banks")

            bank = Bank(
                bank_name=bank_name, account_name=account_name, account_number=account_number,
                sort_order=sort_order, is_active=is_active, logo_filename=logo_filename,
            )
            db.session.add(bank)
            db.session.commit()
            log_activity("bank.create", bank_name)
            flash("Payment account added.", "success")
            return redirect(url_for("admin_banks"))

        return render_template("admin_dashboard.html", view="bank_form", bank=None)

    @app.route("/admin/banks/<int:bank_id>/edit", methods=["GET", "POST"])
    @super_admin_required
    def admin_bank_edit(bank_id):
        bank = Bank.query.get_or_404(bank_id)

        if request.method == "POST":
            bank.bank_name = request.form.get("bank_name", "").strip()
            bank.account_name = request.form.get("account_name", "").strip()
            bank.account_number = request.form.get("account_number", "").strip()
            bank.sort_order = request.form.get("sort_order", type=int) or 0
            bank.is_active = bool(request.form.get("is_active"))

            logo_file = request.files.get("logo")
            if logo_file and logo_file.filename:
                saved = save_uploaded_file(logo_file, subfolder="banks")
                if saved:
                    bank.logo_filename = saved

            db.session.commit()
            log_activity("bank.update", bank.bank_name)
            flash("Payment account updated.", "success")
            return redirect(url_for("admin_banks"))

        return render_template("admin_dashboard.html", view="bank_form", bank=bank)

    @app.route("/admin/banks/<int:bank_id>/delete", methods=["POST"])
    @super_admin_required
    def admin_bank_delete(bank_id):
        bank = Bank.query.get_or_404(bank_id)
        log_activity("bank.delete", bank.bank_name)
        db.session.delete(bank)
        db.session.commit()
        flash("Payment account removed.", "success")
        return redirect(url_for("admin_banks"))

    # --- Post Office Directory Management ---
    @app.route("/admin/post-offices")
    @super_admin_required
    def admin_post_offices():
        query = request.args.get("query", "").strip()
        offices_query = PostOffice.query
        if query:
            like_term = f"%{query}%"
            offices_query = offices_query.filter(
                db.or_(PostOffice.name.ilike(like_term), PostOffice.city.ilike(like_term), PostOffice.region.ilike(like_term))
            )
        offices = offices_query.order_by(PostOffice.city, PostOffice.name).limit(200).all()
        total_count = PostOffice.query.count()
        return render_template("admin_dashboard.html", view="post_offices", offices=offices, total_count=total_count, query=query)

    @app.route("/admin/post-offices/new", methods=["POST"])
    @super_admin_required
    def admin_post_office_new():
        name = request.form.get("name", "").strip()
        city = request.form.get("city", "").strip()
        region = request.form.get("region", "").strip()
        postal_code = request.form.get("postal_code", "").strip()
        address = request.form.get("address", "").strip()

        if not name or not city:
            flash("Post office name and city are required.", "error")
            return redirect(url_for("admin_post_offices"))

        db.session.add(PostOffice(name=name, city=city, region=region, postal_code=postal_code, address=address))
        db.session.commit()
        log_activity("post_office.create", name)
        flash("Post office added.", "success")
        return redirect(url_for("admin_post_offices"))

    @app.route("/admin/post-offices/<int:office_id>/delete", methods=["POST"])
    @super_admin_required
    def admin_post_office_delete(office_id):
        office = PostOffice.query.get_or_404(office_id)
        db.session.delete(office)
        db.session.commit()
        flash("Post office removed.", "success")
        return redirect(url_for("admin_post_offices"))

    @app.route("/admin/post-offices/import", methods=["GET", "POST"])
    @super_admin_required
    def admin_post_offices_import():
        """Bulk-import the full official branch directory (handles 1000+ rows) via CSV."""
        if request.method == "POST":
            csv_file = request.files.get("csv_file")
            if not csv_file or not csv_file.filename.lower().endswith(".csv"):
                flash("Please upload a valid .csv file.", "error")
                return render_template("admin_dashboard.html", view="post_offices_import")

            stream = io.StringIO(csv_file.stream.read().decode("utf-8-sig"))
            reader = csv.DictReader(stream)

            created, skipped = 0, 0
            for row in reader:
                name = (row.get("name") or "").strip()
                city = (row.get("city") or "").strip()
                if not name or not city:
                    skipped += 1
                    continue

                db.session.add(PostOffice(
                    name=name,
                    city=city,
                    region=(row.get("region") or "").strip(),
                    postal_code=(row.get("postal_code") or "").strip(),
                    address=(row.get("address") or "").strip(),
                    is_active=True,
                ))
                created += 1

                # Commit in batches so a 1000+ row file doesn't hold one giant transaction
                if created % 200 == 0:
                    db.session.commit()

            db.session.commit()
            log_activity("post_office.bulk_import", f"{created} created, {skipped} skipped")
            flash(f"Import complete: {created} post offices added, {skipped} rows skipped.", "success")
            return redirect(url_for("admin_post_offices"))

        return render_template("admin_dashboard.html", view="post_offices_import")

    @app.route("/admin/post-offices/import/template.csv")
    @admin_required
    def admin_post_offices_import_template():
        header = "name,city,region,postal_code,address\n"
        example = 'Bole Post Office,Addis Ababa,Addis Ababa,1000,"Bole Sub-city, Addis Ababa"\n'
        return Response(header + example, mimetype="text/csv", headers={
            "Content-Disposition": "attachment; filename=danu_post_office_import_template.csv"
        })

    # --- Delivery Zones ---
    @app.route("/admin/delivery-zones")
    @super_admin_required
    def admin_delivery_zones():
        zones = DeliveryZone.query.order_by(DeliveryZone.city_name).all()
        return render_template("admin_dashboard.html", view="delivery_zones", zones=zones)

    @app.route("/admin/delivery-zones/save", methods=["POST"])
    @super_admin_required
    def admin_delivery_zone_save():
        city_name = request.form.get("city_name", "").strip()
        try:
            fee = Decimal(request.form.get("fee", "0"))
        except InvalidOperation:
            flash("Invalid fee amount.", "error")
            return redirect(url_for("admin_delivery_zones"))

        if not city_name:
            flash("City name is required.", "error")
            return redirect(url_for("admin_delivery_zones"))

        zone = DeliveryZone.query.filter_by(city_name=city_name).first()
        if not zone:
            zone = DeliveryZone(city_name=city_name)
            db.session.add(zone)
        zone.fee = fee
        zone.is_active = True
        db.session.commit()
        flash(f"Delivery fee for {city_name} saved.", "success")
        return redirect(url_for("admin_delivery_zones"))

    @app.route("/admin/delivery-zones/<int:zone_id>/delete", methods=["POST"])
    @super_admin_required
    def admin_delivery_zone_delete(zone_id):
        zone = DeliveryZone.query.get_or_404(zone_id)
        db.session.delete(zone)
        db.session.commit()
        flash("Delivery zone removed.", "success")
        return redirect(url_for("admin_delivery_zones"))

    # --- Coupons ---
    @app.route("/admin/coupons")
    @super_admin_required
    def admin_coupons():
        coupons = Coupon.query.order_by(Coupon.created_at.desc()).all()
        return render_template("admin_dashboard.html", view="coupons", coupons=coupons)

    @app.route("/admin/coupons/new", methods=["POST"])
    @super_admin_required
    def admin_coupon_new():
        code = request.form.get("code", "").strip().upper()
        discount_type = request.form.get("discount_type", Coupon.TYPE_PERCENT)
        usage_limit = request.form.get("usage_limit", type=int)
        expires_raw = request.form.get("expires_at", "").strip()

        try:
            discount_value = Decimal(request.form.get("discount_value", "0"))
        except InvalidOperation:
            flash("Invalid discount value.", "error")
            return redirect(url_for("admin_coupons"))

        if not code:
            flash("Coupon code is required.", "error")
            return redirect(url_for("admin_coupons"))

        expires_at = None
        if expires_raw:
            try:
                expires_at = datetime.strptime(expires_raw, "%Y-%m-%d")
            except ValueError:
                pass

        coupon = Coupon(
            code=code, discount_type=discount_type, discount_value=discount_value,
            usage_limit=usage_limit, expires_at=expires_at, is_active=True,
        )
        db.session.add(coupon)
        db.session.commit()
        log_activity("coupon.create", code)
        flash("Coupon created.", "success")
        return redirect(url_for("admin_coupons"))

    @app.route("/admin/coupons/<int:coupon_id>/toggle", methods=["POST"])
    @super_admin_required
    def admin_coupon_toggle(coupon_id):
        coupon = Coupon.query.get_or_404(coupon_id)
        coupon.is_active = not coupon.is_active
        db.session.commit()
        return redirect(url_for("admin_coupons"))

    @app.route("/admin/coupons/<int:coupon_id>/delete", methods=["POST"])
    @super_admin_required
    def admin_coupon_delete(coupon_id):
        coupon = Coupon.query.get_or_404(coupon_id)
        db.session.delete(coupon)
        db.session.commit()
        flash("Coupon deleted.", "success")
        return redirect(url_for("admin_coupons"))

    # --- Loyalty Accounts ---
    @app.route("/admin/loyalty")
    @admin_required
    def admin_loyalty():
        accounts = LoyaltyAccount.query.order_by(LoyaltyAccount.points.desc()).limit(100).all()
        return render_template("admin_dashboard.html", view="loyalty", accounts=accounts)

    # --- Banners ---
    @app.route("/admin/banners")
    @super_admin_required
    def admin_banners():
        banners = Banner.query.order_by(Banner.created_at.desc()).all()
        return render_template("admin_dashboard.html", view="banners", banners=banners)

    @app.route("/admin/banners/new", methods=["GET", "POST"])
    @super_admin_required
    def admin_banner_new():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            if not title:
                flash("Banner title is required.", "error")
                return render_template("admin_dashboard.html", view="banner_form", banner=None)

            image_filename = None
            image_file = request.files.get("image")
            if image_file and image_file.filename:
                image_filename = save_uploaded_file(image_file, subfolder="banners")

            is_active = bool(request.form.get("is_active"))
            if is_active:
                Banner.query.update({Banner.is_active: False})  # only one active banner at a time

            banner = Banner(
                title=title,
                subtitle=request.form.get("subtitle", "").strip(),
                cta_text=request.form.get("cta_text", "").strip(),
                cta_link=request.form.get("cta_link", "").strip(),
                image_filename=image_filename,
                is_active=is_active,
            )
            db.session.add(banner)
            db.session.commit()
            log_activity("banner.create", title)
            flash("Banner saved.", "success")
            return redirect(url_for("admin_banners"))

        return render_template("admin_dashboard.html", view="banner_form", banner=None)

    @app.route("/admin/banners/<int:banner_id>/activate", methods=["POST"])
    @super_admin_required
    def admin_banner_activate(banner_id):
        Banner.query.update({Banner.is_active: False})
        banner = Banner.query.get_or_404(banner_id)
        banner.is_active = True
        db.session.commit()
        flash(f"'{banner.title}' is now live on the homepage.", "success")
        return redirect(url_for("admin_banners"))

    @app.route("/admin/banners/<int:banner_id>/delete", methods=["POST"])
    @super_admin_required
    def admin_banner_delete(banner_id):
        banner = Banner.query.get_or_404(banner_id)
        db.session.delete(banner)
        db.session.commit()
        flash("Banner deleted.", "success")
        return redirect(url_for("admin_banners"))

    # --- Customer Data Export (privacy / compliance) ---
    @app.route("/my-data", methods=["GET", "POST"])
    def customer_data_export():
        """Lets a customer look up and export their own order history by phone + one order code
        (a lightweight, no-login identity check appropriate for a guest-checkout store)."""
        data = None
        if request.method == "POST":
            phone = request.form.get("phone", "").strip()
            order_code = request.form.get("order_code", "").strip().upper()
            verifying_order = Order.query.filter_by(customer_phone=phone, order_code=order_code).first()
            if verifying_order:
                orders = Order.query.filter_by(customer_phone=phone).order_by(Order.created_at.desc()).all()
                data = {
                    "phone": phone,
                    "orders": [
                        {
                            "order_code": o.order_code, "status": o.status,
                            "total_amount": float(o.total_amount), "created_at": o.created_at.isoformat(),
                            "items": [{"product": i.product_name, "qty": i.quantity} for i in o.items],
                        }
                        for o in orders
                    ],
                }
            else:
                flash("We couldn't verify your identity with that phone number and order code.", "error")
        return render_template("my_data.html", data=data)

    @app.route("/my-data/export.json", methods=["POST"])
    def customer_data_export_json():
        phone = request.form.get("phone", "").strip()
        order_code = request.form.get("order_code", "").strip().upper()
        verifying_order = Order.query.filter_by(customer_phone=phone, order_code=order_code).first()
        if not verifying_order:
            abort(403)

        orders = Order.query.filter_by(customer_phone=phone).order_by(Order.created_at.desc()).all()
        payload = {
            "phone": phone,
            "exported_at": datetime.utcnow().isoformat(),
            "orders": [
                {
                    "order_code": o.order_code, "status": o.status,
                    "total_amount": float(o.total_amount), "created_at": o.created_at.isoformat(),
                    "delivery_address": o.delivery_address, "city": o.city,
                    "items": [{"product": i.product_name, "qty": i.quantity, "unit_price": float(i.unit_price)} for i in o.items],
                }
                for o in orders
            ],
        }
        import json
        return Response(
            json.dumps(payload, indent=2), mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename=danu_perfume_data_{phone}.json"},
        )

    # =========================================================
    # CLI / Startup: create tables and seed default data
    # =========================================================
    @app.cli.command("init-db")
    def init_db_command():
        """Flask CLI command: `flask init-db` — creates tables and seeds default data."""
        _init_db(app)
        print("Database initialized.")

    @app.cli.command("reset-accounts")
    @click.option("--force", is_flag=True, help="Delete existing admin/customer accounts and recreate defaults.")
    def reset_accounts_command(force):
        """
        Flask CLI command: `flask reset-accounts --force`

        Deletes all existing admin (User) and customer (Customer) records, then
        re-creates the default Danuta/Tofik admin accounts from configured env vars.
        Only run this when you need to remove stale or conflicting login records.
        """
        if not force:
            print("This command is destructive. Run it again with --force to proceed.")
            return

        with app.app_context():
            deleted_customers = Customer.query.delete()
            deleted_admins = User.query.delete()
            db.session.commit()
            print(f"[Danu Perfume] Removed {deleted_admins} admin account(s) and {deleted_customers} customer account(s).")

            _init_db(app)
            print("[Danu Perfume] Danuta and Tofik re-created from ADMIN_PASSWORD_DANUTA / ADMIN_PASSWORD_TOFIK.")
            print("[Danu Perfume] Done. Log in at /login with your new passwords.")

    def _ensure_schema(flask_app):
        """
        Safety net: if the model definitions gain new columns after the database
        already exists (SQLite locally OR Postgres/Neon in production), add the
        missing columns automatically instead of the app crashing with
        'column does not exist' on every query that touches that table.

        This runs on every startup and is a no-op once the schema is caught up
        (each ALTER is skipped if the column is already present). For a larger
        production app you'd normally reach for Flask-Migrate/Alembic instead —
        this lightweight version exists so a single-file deploy never breaks
        just because a model gained a field.
        """
        with flask_app.app_context():
            inspector = inspect(db.engine)
            all_models = (
                User, Customer, ActivityLog, Category, Product, ProductImage, Review, StockAlert,
                Bank, DeliveryZone, Coupon, LoyaltyAccount, Banner, PostOffice, Order, OrderItem,
                OrderIssueReport, DailySummary, AppSetting,
            )
            for model in all_models:
                table_name = model.__tablename__
                if table_name not in inspector.get_table_names():
                    continue

                existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
                for column in model.__table__.columns:
                    if column.name in existing_columns:
                        continue

                    column_type = column.type.compile(dialect=db.engine.dialect)
                    # Each column addition commits (or rolls back) on its own so that
                    # Postgres aborting one statement never blocks the rest of the batch.
                    try:
                        db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column.name} {column_type}"))
                        db.session.commit()
                        print(f"[Danu Perfume] Schema fix: added {table_name}.{column.name}", flush=True)
                    except Exception as exc:  # noqa: BLE001
                        db.session.rollback()
                        print(f"[Danu Perfume] Schema fix skipped for {table_name}.{column.name}: {exc}", flush=True)

    def _init_db(flask_app):
        with flask_app.app_context():
            db.create_all()
            _ensure_schema(flask_app)

            for username, full_name, password, role in flask_app.config["ADMIN_ACCOUNTS"]:
                admin = User.query.filter(func.lower(User.username) == username.lower()).first()
                if not admin:
                    admin = User(full_name=full_name, username=username, role=role, is_admin=True)
                    db.session.add(admin)

                admin.full_name = full_name
                admin.username = username
                admin.role = role
                admin.is_admin = True
                admin.set_password(password)

            if Category.query.count() == 0:
                default_categories = [
                    Category(name="Women", slug="women"),
                    Category(name="Men", slug="men"),
                    Category(name="Unisex", slug="unisex"),
                    Category(name="Oud & Attar", slug="oud-attar"),
                ]
                db.session.add_all(default_categories)

            if Bank.query.count() == 0:
                default_banks = [
                    Bank(bank_name="Telebirr", account_name="Danu Perfume", account_number="0900000000", sort_order=1),
                    Bank(bank_name="Commercial Bank of Ethiopia", account_name="Danu Perfume PLC", account_number="1000000000000", sort_order=2),
                ]
                db.session.add_all(default_banks)

            if DeliveryZone.query.count() == 0:
                default_zones = [
                    DeliveryZone(city_name="Addis Ababa", fee=Decimal("100")),
                    DeliveryZone(city_name="Adama", fee=Decimal("200")),
                    DeliveryZone(city_name="Bahir Dar", fee=Decimal("250")),
                ]
                db.session.add_all(default_zones)

            if PostOffice.query.count() == 0:
                db.session.add_all([PostOffice(**office) for office in SEED_POST_OFFICES])

            db.session.commit()

    with app.app_context():
        try:
            db.create_all()
            _ensure_schema(app)

            if Category.query.count() == 0:
                db.session.add_all([
                    Category(name="Women", slug="women"),
                    Category(name="Men", slug="men"),
                    Category(name="Unisex", slug="unisex"),
                    Category(name="Oud & Attar", slug="oud-attar"),
                ])
                db.session.commit()

            missing_admin = any(
                not User.query.filter(func.lower(User.username) == u.lower()).first()
                for u, _, _, _ in app.config["ADMIN_ACCOUNTS"]
            )
            if missing_admin or Bank.query.count() == 0 or DeliveryZone.query.count() == 0 or PostOffice.query.count() == 0:
                _init_db(app)

            # SECURITY: if any admin password was auto-generated because the env
            # var wasn't set (see config.py), print it ONCE now so whoever is
            # watching the deploy logs can capture and store it — it will not be
            # shown again and is never written to disk or committed to git.
            if app.config.get("GENERATED_ADMIN_PASSWORDS"):
                print("=" * 60, flush=True)
                print("[Danu Perfume] ⚠️  Auto-generated admin password(s) —", flush=True)
                print("set these as real env vars, then redeploy:", flush=True)
                for env_key, pw in app.config["GENERATED_ADMIN_PASSWORDS"].items():
                    print(f"    {env_key} = {pw}", flush=True)
                print("=" * 60, flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[Danu Perfume] Startup DB check skipped: {exc}")

    # PERFORMANCE FIX (part 3 of the review): cache CSS/JS/uploaded images in the
    # browser for a year. Safe because filenames for uploads are already unique
    # (uuid4-based) and style.css/app assets should be cache-busted by
    # redeploying with a new filename/version if they ever need to change fast.
    @app.after_request
    def add_static_cache_headers(response):
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        return (
            "<h1 style='font-family:sans-serif;text-align:center;margin-top:15vh;'>"
            "404 &mdash; Page Not Found</h1>"
            "<p style='text-align:center;'><a href='/'>Return to Danu Perfume</a></p>",
            404,
        )

    @app.errorhandler(413)
    def file_too_large(e):
        flash("Uploaded file is too large. Maximum size is 5MB.", "error")
        return redirect(request.referrer or url_for("index"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=app.config.get("DEBUG", False))
