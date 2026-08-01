"""
app.py
Main Flask application for Danu Perfume.

Responsibilities:
    - App factory / initialization
    - Database (Neon PostgreSQL via SQLAlchemy) wiring
    - Authentication (Flask-Login) for the admin dashboard
    - i18n language switching (dictionary-based, see translations.py)
    - Public storefront routes (home, shop, product notes, checkout)
    - Admin routes (login, dashboard, product CRUD, order management)
    - Secure file upload handling for product images and payment receipts
"""

import os
import random
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort, send_from_directory
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.utils import secure_filename
from sqlalchemy import func, inspect, text

from config import config_by_name
from models import db, User, Category, Product, Order, OrderItem, Bank
from translations import TRANSLATIONS, get_text


ETHIOPIA_POST_OFFICES = [
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

        return dict(
            t=t,
            current_lang=current_lang,
            available_languages=app.config["LANGUAGES"],
            lang_names={code: TRANSLATIONS[code]["lang.name"] for code in app.config["LANGUAGES"]},
            currency=app.config["CURRENCY_SYMBOL"],
            now=datetime.utcnow(),
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
                "name": p.name,
                "brand": p.brand,
                "description": p.description,
                "price": float(p.price),
                "discount_price": float(p.discount_price) if p.discount_price else None,
                "effective_price": float(p.effective_price),
                "stock": p.stock,
                "volume_ml": p.volume_ml,
                "image_url": url_for("static", filename=f"uploads/{p.image_filename}") if p.image_filename else None,
                "category": p.category.name if p.category else None,
                "category_slug": p.category.slug if p.category else None,
                "top_notes": p.top_notes_list,
                "heart_notes": p.heart_notes_list,
                "base_notes": p.base_notes_list,
            })
        return jsonify(result)

    @app.route("/api/product/<int:product_id>")
    def api_product_detail(product_id):
        """JSON endpoint for the fragrance-notes modal on the homepage."""
        p = Product.query.get_or_404(product_id)
        return jsonify({
            "id": p.id,
            "name": p.name,
            "brand": p.brand,
            "description": p.description,
            "price": float(p.price),
            "effective_price": float(p.effective_price),
            "volume_ml": p.volume_ml,
            "image_url": url_for("static", filename=f"uploads/{p.image_filename}") if p.image_filename else None,
            "top_notes": p.top_notes_list,
            "heart_notes": p.heart_notes_list,
            "base_notes": p.base_notes_list,
        })

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

    # --- Checkout ---
    def post_offices():
        query = (request.args.get("query") or "").strip().lower()
        offices = ETHIOPIA_POST_OFFICES
        if query:
            offices = [
                office for office in offices
                if query in office["name"].lower()
                or query in office["city"].lower()
                or query in office["region"].lower()
                or query in office["address"].lower()
                or query in office["postal_code"].lower()
            ]
        return render_template("post_offices.html", offices=offices, query=query)

    def api_post_offices():
        query = (request.args.get("query") or "").strip().lower()
        offices = ETHIOPIA_POST_OFFICES
        if query:
            offices = [
                office for office in offices
                if query in office["name"].lower()
                or query in office["city"].lower()
                or query in office["region"].lower()
                or query in office["address"].lower()
                or query in office["postal_code"].lower()
            ]
        return jsonify({"results": offices})

    app.add_url_rule("/post-offices", view_func=post_offices)
    app.add_url_rule("/api/post-offices", view_func=api_post_offices)

    @app.route("/checkout", methods=["GET", "POST"])
    def checkout():
        cart = get_cart()

        if not cart:
            flash("Your cart is empty.", "warning")
            return redirect(url_for("index"))

        # Build line items and compute subtotal from the DATABASE (never trust client price)
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
        post_office_options = ETHIOPIA_POST_OFFICES

        # A randomized delivery fee is proposed up-front; final fee can still be
        # adjusted by an admin when approving the order (e.g. after confirming distance).
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
            delivery_fee = request.form.get("delivery_fee", type=str)

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
                fee_decimal = Decimal(delivery_fee) if delivery_fee else proposed_fee
            except InvalidOperation:
                fee_decimal = proposed_fee

            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template(
                    "checkout.html", line_items=line_items, subtotal=subtotal,
                    banks=banks, delivery_options=delivery_options, proposed_fee=proposed_fee,
                    post_office_options=post_office_options,
                )

            receipt_filename = save_uploaded_file(receipt_file, subfolder="receipts")
            grand_total = subtotal + fee_decimal

            new_order = Order(
                order_code=generate_order_code(),
                customer_name=customer_name,
                customer_phone=customer_phone,
                delivery_address=delivery_address,
                city=city,
                post_office_location=post_office_location,
                delivery_type=delivery_type,
                notes=notes,
                payment_method=payment_method,
                bank_id=bank_id if bank_id else None,
                payment_screenshot=receipt_filename,
                subtotal_amount=subtotal,
                delivery_fee=fee_decimal,
                total_amount=grand_total,
                status=Order.STATUS_PENDING,
            )
            db.session.add(new_order)
            db.session.flush()  # get new_order.id before commit

            for item in line_items:
                db.session.add(OrderItem(
                    order_id=new_order.id,
                    product_id=item["product"].id,
                    product_name=item["product"].name,
                    unit_price=item["product"].effective_price,
                    quantity=item["quantity"],
                ))
                # Reduce stock
                item["product"].stock = max(item["product"].stock - item["quantity"], 0)

            db.session.commit()
            save_cart({})  # clear cart

            return render_template("checkout.html", order_success=True, order=new_order)

        return render_template(
            "checkout.html", line_items=line_items, subtotal=subtotal,
            banks=banks, delivery_options=delivery_options, proposed_fee=proposed_fee,
            post_office_options=post_office_options,
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

            user = User.query.filter_by(email=username).first()
            if user and user.check_password(password):
                login_user(user)
                flash("Welcome back!", "success")
                next_page = request.args.get("next")
                return redirect(next_page or url_for("admin_dashboard"))

            flash("Invalid username or password.", "error")

        return render_template("admin_login.html")

    @app.route("/admin/logout")
    @login_required
    def admin_logout():
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

        return render_template(
            "admin_dashboard.html",
            total_orders=total_orders,
            pending_orders=pending_orders,
            total_products=total_products,
            total_sales=total_sales,
            recent_orders=recent_orders,
            low_stock_products=low_stock_products,
            view="overview",
        )

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
    @login_required
    def admin_product_new():
        categories = Category.query.all()

        if request.method == "POST":
            product, error = _build_product_from_form(request, categories)
            if error:
                flash(error, "error")
                return render_template("admin_dashboard.html", view="product_form", categories=categories, product=None)

            db.session.add(product)
            db.session.commit()
            flash("Product created successfully.", "success")
            return redirect(url_for("admin_products"))

        return render_template("admin_dashboard.html", view="product_form", categories=categories, product=None)

    @app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
    @login_required
    def admin_product_edit(product_id):
        product = Product.query.get_or_404(product_id)
        categories = Category.query.all()

        if request.method == "POST":
            updated, error = _build_product_from_form(request, categories, existing=product)
            if error:
                flash(error, "error")
                return render_template("admin_dashboard.html", view="product_form", categories=categories, product=product)

            db.session.commit()
            flash("Product updated successfully.", "success")
            return redirect(url_for("admin_products"))

        return render_template("admin_dashboard.html", view="product_form", categories=categories, product=product)

    @app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
    @login_required
    def admin_product_delete(product_id):
        product = Product.query.get_or_404(product_id)
        db.session.delete(product)
        db.session.commit()
        flash("Product deleted.", "success")
        return redirect(url_for("admin_products"))

    def _build_product_from_form(req, categories, existing=None):
        """Shared logic to create/update a Product from a submitted form."""
        name = req.form.get("name", "").strip()
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
            flash(f"Order {order.order_code} updated to {new_status}.", "success")
        else:
            flash("Invalid status.", "error")

        return redirect(url_for("admin_order_detail", order_id=order.id))

    @app.route("/admin/orders/<int:order_id>/delivery-fee", methods=["POST"])
    @login_required
    def admin_order_update_delivery_fee(order_id):
        """Lets an admin adjust the delivery fee (e.g. after confirming distance
        with the customer) and recomputes the order total automatically."""
        order = Order.query.get_or_404(order_id)

        try:
            new_fee = Decimal(request.form.get("delivery_fee", "0"))
        except InvalidOperation:
            flash("Invalid delivery fee.", "error")
            return redirect(url_for("admin_order_detail", order_id=order.id))

        order.delivery_fee = new_fee
        order.total_amount = order.subtotal_amount + new_fee
        order.delivery_type = request.form.get("delivery_type", order.delivery_type)
        db.session.commit()
        flash("Delivery fee updated.", "success")
        return redirect(url_for("admin_order_detail", order_id=order.id))

    # --- Bank / Payment Account Management ---
    @app.route("/admin/banks")
    @login_required
    def admin_banks():
        banks = Bank.query.order_by(Bank.sort_order, Bank.created_at).all()
        return render_template("admin_dashboard.html", view="banks", banks=banks)

    @app.route("/admin/banks/new", methods=["GET", "POST"])
    @login_required
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
            flash("Payment account added.", "success")
            return redirect(url_for("admin_banks"))

        return render_template("admin_dashboard.html", view="bank_form", bank=None)

    @app.route("/admin/banks/<int:bank_id>/edit", methods=["GET", "POST"])
    @login_required
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
            flash("Payment account updated.", "success")
            return redirect(url_for("admin_banks"))

        return render_template("admin_dashboard.html", view="bank_form", bank=bank)

    @app.route("/admin/banks/<int:bank_id>/delete", methods=["POST"])
    @login_required
    def admin_bank_delete(bank_id):
        bank = Bank.query.get_or_404(bank_id)
        db.session.delete(bank)
        db.session.commit()
        flash("Payment account removed.", "success")
        return redirect(url_for("admin_banks"))

    # =========================================================
    # CLI / Startup: create tables and seed a default admin
    # =========================================================
    @app.cli.command("init-db")
    def init_db_command():
        """Flask CLI command: `flask init-db` — creates tables and a default admin user."""
        _init_db(app)
        print("Database initialized.")

    def _ensure_schema(flask_app):
        """Add missing columns for older SQLite databases so the admin dashboard continues to work."""
        with flask_app.app_context():
            if db.engine.url.get_backend_name() != "sqlite":
                return

            inspector = inspect(db.engine)
            for model in (User, Category, Product, Order, OrderItem, Bank):
                table_name = model.__tablename__
                if table_name not in inspector.get_table_names():
                    continue

                existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
                for column in model.__table__.columns:
                    if column.name in existing_columns:
                        continue

                    column_type = column.type.compile(dialect=db.engine.dialect)
                    db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column.name} {column_type}"))

            db.session.commit()

    def _init_db(flask_app):
        with flask_app.app_context():
            db.create_all()
            _ensure_schema(flask_app)

            for username, full_name, password in flask_app.config["ADMIN_ACCOUNTS"]:
                if not User.query.filter_by(email=username).first():
                    admin = User(full_name=full_name, email=username, is_admin=True)
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

            db.session.commit()

    # Auto-initialize on first request in case `flask init-db` wasn't run manually
    with app.app_context():
        try:
            db.create_all()
            _ensure_schema(app)
            missing_admin = any(
                not User.query.filter_by(email=u).first()
                for u, _, _ in app.config["ADMIN_ACCOUNTS"]
            )
            if missing_admin or Bank.query.count() == 0:
                _init_db(app)
        except Exception as exc:  # noqa: BLE001
            # DB might not be reachable yet at import time (e.g. during static analysis)
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
