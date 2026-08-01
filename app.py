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
import io
import os
import random
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort, Response
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.utils import secure_filename
from sqlalchemy import func, text

from config import config_by_name
from models import (
    db, User, ActivityLog, Category, Product, ProductImage, Review, StockAlert,
    Bank, DeliveryZone, Coupon, LoyaltyAccount, Banner, Order, OrderItem,
)
from translations import TRANSLATIONS, get_text


def create_app(env_name=None):
    """Application factory."""
    app = Flask(__name__)

    env_name = env_name or os.environ.get("FLASK_ENV", "production")
    app.config.from_object(config_by_name.get(env_name, config_by_name["production"]))

    # Ensure a safe SQLite fallback is present so the app can start
    # even if a DATABASE_URL/SQLALCHEMY_DATABASE_URI isn't provided.
    if not app.config.get("SQLALCHEMY_DATABASE_URI") and not app.config.get("SQLALCHEMY_BINDS"):
        default_sqlite = f"sqlite:///{os.path.join(os.path.abspath(os.path.dirname(__file__)), 'danu_perfume.db')}"
        # Explicitly assign the fallback to ensure Flask-SQLAlchemy sees it during init
        app.config["SQLALCHEMY_DATABASE_URI"] = default_sqlite

    # --- Initialize extensions ---
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "admin_login"
    login_manager.login_message = "Please log in to access the admin dashboard."
    login_manager.login_message_category = "warning"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # --- Ensure upload folder exists ---
    upload_path = os.path.join(app.root_path, app.config["UPLOAD_FOLDER"])
    os.makedirs(upload_path, exist_ok=True)

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

        return dict(
            t=t,
            current_lang=current_lang,
            available_languages=app.config["LANGUAGES"],
            lang_names={code: TRANSLATIONS[code]["lang.name"] for code in app.config["LANGUAGES"]},
            currency=app.config["CURRENCY_SYMBOL"],
            fx_rates=app.config["FX_RATES"],
            now=datetime.utcnow(),
            active_banner=active_banner,
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
        Safely saves an uploaded file with a randomized, secure filename.
        Returns the relative filename (to store in the DB) or None if invalid.
        """
        if not file_storage or file_storage.filename == "":
            return None

        if not allowed_file(file_storage.filename):
            return None

        original_name = secure_filename(file_storage.filename)
        extension = original_name.rsplit(".", 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex}.{extension}"

        target_dir = os.path.join(app.root_path, app.config["UPLOAD_FOLDER"], subfolder)
        os.makedirs(target_dir, exist_ok=True)

        file_storage.save(os.path.join(target_dir, unique_name))

        return f"{subfolder}/{unique_name}" if subfolder else unique_name

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

    def super_admin_required(view_func):
        @wraps(view_func)
        @login_required
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
                phone=phone, customer_name=customer_name,
                referral_code=("DANU" + uuid.uuid4().hex[:6].upper()),
            )
            db.session.add(account)

        points = int((float(amount_spent) / 100) * app.config["LOYALTY_POINTS_PER_100_ETB"])
        account.points += points
        account.total_spent = (account.total_spent or 0) + amount_spent
        account.customer_name = customer_name
        return points

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
                "image_url": url_for("static", filename=f"uploads/{p.image_filename}") if p.image_filename else None,
                "gallery": [url_for("static", filename=f"uploads/{img.filename}") for img in p.gallery_images],
                "category": p.category.name if p.category else None,
                "category_slug": p.category.slug if p.category else None,
                "top_notes": p.top_notes_list,
                "heart_notes": p.heart_notes_list,
                "base_notes": p.base_notes_list,
                "average_rating": p.average_rating,
                "review_count": len(p.approved_reviews),
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
            "image_url": url_for("static", filename=f"uploads/{p.image_filename}") if p.image_filename else None,
            "gallery": [url_for("static", filename=f"uploads/{img.filename}") for img in p.gallery_images],
            "top_notes": p.top_notes_list,
            "heart_notes": p.heart_notes_list,
            "base_notes": p.base_notes_list,
            "average_rating": p.average_rating,
            "reviews": [
                {"customer_name": r.customer_name, "rating": r.rating, "comment": r.comment}
                for r in p.approved_reviews
            ],
        })

    @app.route("/api/product/<int:product_id>/review", methods=["POST"])
    def api_product_review_submit(product_id):
        """Customers submit a review; it stays hidden until an admin approves it."""
        product = Product.query.get_or_404(product_id)
        data = request.get_json(silent=True) or {}
        customer_name = (data.get("customer_name") or "").strip()
        rating = int(data.get("rating", 5))
        comment = (data.get("comment") or "").strip()

        if not customer_name or rating < 1 or rating > 5:
            return jsonify({"error": "Please provide your name and a rating between 1 and 5."}), 400

        review = Review(
            product_id=product.id, customer_name=customer_name,
            rating=rating, comment=comment, is_approved=False,
        )
        db.session.add(review)
        db.session.commit()
        return jsonify({"success": True, "message": "Thank you! Your review will appear once approved."})

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
                "image_url": url_for("static", filename=f"uploads/{product.image_filename}") if product.image_filename else None,
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
        proposed_fee = roll_delivery_fee()

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
            save_cart({})

            return render_template("checkout.html", order_success=True, order=new_order)

        return render_template(
            "checkout.html", line_items=line_items, subtotal=subtotal,
            banks=banks, delivery_options=delivery_options, proposed_fee=proposed_fee,
        )

    # =========================================================
    # ADMIN ROUTES
    # =========================================================
    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if current_user.is_authenticated:
            return redirect(url_for("admin_dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                login_user(user)
                log_activity("auth.login", f"{username} logged in")
                flash("Welcome back!", "success")
                next_page = request.args.get("next")
                return redirect(next_page or url_for("admin_dashboard"))

            flash("Invalid username or password.", "error")

        return render_template("admin_login.html")

    @app.route("/admin/logout")
    @login_required
    def admin_logout():
        log_activity("auth.logout", f"{current_user.username} logged out")
        logout_user()
        flash("You have been logged out.", "success")
        return redirect(url_for("admin_login"))

    @app.route("/admin")
    @app.route("/admin/dashboard")
    @login_required
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
    @login_required
    def admin_analytics():
        return render_template("admin_dashboard.html", view="analytics")

    @app.route("/admin/analytics/sales-data")
    @login_required
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

    # --- Product CRUD ---
    @app.route("/admin/products")
    @login_required
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
    @login_required
    def admin_products_import_template():
        header = "name,sku,brand,description,price,stock,volume_ml,top_notes,heart_notes,base_notes,category_slug\n"
        example = 'Golden Oud,DP-001,Danu,"A rich oud fragrance",1200,20,50,"Bergamot, Saffron","Oud, Rose","Amber, Musk",oud-attar\n'
        return Response(header + example, mimetype="text/csv", headers={
            "Content-Disposition": "attachment; filename=danu_product_import_template.csv"
        })

    # --- Reviews Moderation ---
    @app.route("/admin/reviews")
    @login_required
    def admin_reviews():
        pending = Review.query.filter_by(is_approved=False).order_by(Review.created_at.desc()).all()
        approved = Review.query.filter_by(is_approved=True).order_by(Review.created_at.desc()).limit(50).all()
        return render_template("admin_dashboard.html", view="reviews", pending=pending, approved=approved)

    @app.route("/admin/reviews/<int:review_id>/approve", methods=["POST"])
    @login_required
    def admin_review_approve(review_id):
        review = Review.query.get_or_404(review_id)
        review.is_approved = True
        db.session.commit()
        log_activity("review.approve", f"{review.product.name} by {review.customer_name}")
        flash("Review approved and published.", "success")
        return redirect(url_for("admin_reviews"))

    @app.route("/admin/reviews/<int:review_id>/delete", methods=["POST"])
    @login_required
    def admin_review_delete(review_id):
        review = Review.query.get_or_404(review_id)
        db.session.delete(review)
        db.session.commit()
        flash("Review deleted.", "success")
        return redirect(url_for("admin_reviews"))

    # --- Stock Alerts ---
    @app.route("/admin/stock-alerts")
    @login_required
    def admin_stock_alerts():
        alerts = (
            StockAlert.query.filter_by(notified=False)
            .join(Product)
            .order_by(StockAlert.created_at.desc())
            .all()
        )
        return render_template("admin_dashboard.html", view="stock_alerts", alerts=alerts)

    @app.route("/admin/stock-alerts/<int:alert_id>/mark-notified", methods=["POST"])
    @login_required
    def admin_stock_alert_mark_notified(alert_id):
        alert = StockAlert.query.get_or_404(alert_id)
        alert.notified = True
        db.session.commit()
        return redirect(url_for("admin_stock_alerts"))

    # --- Order Management ---
    @app.route("/admin/orders")
    @login_required
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
    @login_required
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
    @login_required
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
    @login_required
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
    @login_required
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
    @login_required
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

    def _init_db(flask_app):
        with flask_app.app_context():
            db.create_all()

            for acct in flask_app.config["ADMIN_ACCOUNTS"]:
                # Support tuples of (username, full_name, password) and (username, full_name, password, role)
                try:
                    if len(acct) == 4:
                        username, full_name, password, role = acct
                    elif len(acct) == 3:
                        username, full_name, password = acct
                        role = User.ROLE_SUPER_ADMIN
                    else:
                        continue
                except Exception:
                    continue

                if not User.query.filter_by(username=username).first():
                    admin = User(full_name=full_name, username=username, role=role, is_admin=True)
                    admin.set_password(password)
                    db.session.add(admin)

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

            db.session.commit()

    with app.app_context():
        try:
            # Ensure base tables exist (will not modify existing columns)
            db.create_all()

            # SQLite compatibility: add missing columns that older DBs may lack.
            def _ensure_schema_compat():
                engine = db.engine

                def has_column(table, column):
                    try:
                        rows = engine.execute(text(f"PRAGMA table_info('{table}')")).fetchall()
                    except Exception:
                        return False
                    return any(r[1] == column for r in rows)

                # users.username (older DBs may not have this column)
                if not has_column('users', 'username'):
                    try:
                        with engine.begin() as conn:
                            conn.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(60)"))
                    except Exception:
                        pass

                # users.role (older DBs may not have role column)
                if not has_column('users', 'role'):
                    try:
                        with engine.begin() as conn:
                            conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(30)"))
                    except Exception:
                        pass
                else:
                    # Ensure existing users have a role set
                    try:
                        with engine.begin() as conn:
                            conn.execute(text(f"UPDATE users SET role = :role WHERE role IS NULL OR role = ''"), {'role': User.ROLE_SUPER_ADMIN})
                    except Exception:
                        pass
                    # Also ensure via ORM update in case the SQL above didn't take effect
                    try:
                        db.session.query(User).filter((User.role == None) | (User.role == "")).update({"role": User.ROLE_SUPER_ADMIN}, synchronize_session=False)
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

                # products.sku (some seed DBs may be from an earlier schema)
                if not has_column('products', 'sku'):
                    try:
                        with engine.begin() as conn:
                            conn.execute(text("ALTER TABLE products ADD COLUMN sku VARCHAR(40)"))
                    except Exception:
                        pass

                # Ensure common `orders` columns exist (avoid admin dashboard query failures)
                orders_columns = {
                    'rider_name': "VARCHAR(100)",
                    'rider_phone': "VARCHAR(30)",
                    'notes': "TEXT",
                    'is_gift': "BOOLEAN",
                    'gift_message': "VARCHAR(300)",
                    'payment_method': "VARCHAR(30)",
                    'bank_id': "INTEGER",
                    'payment_screenshot': "VARCHAR(255)",
                    'coupon_code': "VARCHAR(40)",
                    'discount_amount': "NUMERIC",
                    'subtotal_amount': "NUMERIC",
                    'delivery_fee': "NUMERIC",
                    'total_amount': "NUMERIC",
                    'points_earned': "INTEGER",
                    'risk_level': "VARCHAR(20)",
                    'risk_reasons': "VARCHAR(255)",
                    'status': "VARCHAR(30)",
                    'created_at': "DATETIME",
                    'updated_at': "DATETIME",
                }
                for col, coltype in orders_columns.items():
                    if not has_column('orders', col):
                        try:
                            with engine.begin() as conn:
                                conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col} {coltype}"))
                        except Exception:
                            pass

                # Populate username for existing users if missing
                try:
                    with engine.begin() as conn:
                        conn.execute(text("UPDATE users SET username = full_name WHERE username IS NULL OR username = ''"))
                except Exception:
                    pass

            _ensure_schema_compat()

            missing_admin = any(
                not User.query.filter_by(username=u).first()
                for u, _, _, _ in app.config["ADMIN_ACCOUNTS"]
            )
            if missing_admin or Bank.query.count() == 0:
                _init_db(app)
        except Exception as exc:  # noqa: BLE001
            print(f"[Danu Perfume] Startup DB check skipped: {exc}")

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
