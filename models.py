"""
models.py
SQLAlchemy ORM models for the Danu Perfume application.

Models:
    - User            : Admin/staff accounts with role-based access (Flask-Login)
    - ActivityLog      : Audit trail of admin actions (who did what, when)
    - Category         : Perfume categories (e.g. Men, Women, Unisex, Oud)
    - Product          : Perfume products with fragrance notes, pricing, SKU
    - ProductImage     : Extra gallery images for a Product (multi-image gallery)
    - Review           : Customer star-rating + comment on a Product
    - StockAlert       : "Notify me" signup for an out-of-stock Product
    - Bank             : Admin-managed payment account shown at checkout
    - DeliveryZone     : City -> fixed delivery fee mapping
    - Coupon           : Promo/discount codes
    - LoyaltyAccount   : Points balance keyed by customer phone number
    - Banner           : Admin-editable homepage hero/promo banner
    - Order            : A guest checkout order
    - OrderItem        : Individual line items belonging to an Order
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """Admin/staff user account used to access the admin dashboard."""

    __tablename__ = "users"

    ROLE_SUPER_ADMIN = "super_admin"     # full access: products, banks, orders, users, settings
    ROLE_ORDER_MANAGER = "order_manager"  # can view products, manage orders/delivery only

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False, default="Admin")
    username = db.Column(db.String(60), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default=ROLE_SUPER_ADMIN)
    is_admin = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_super_admin(self):
        return self.role == self.ROLE_SUPER_ADMIN

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class ActivityLog(db.Model):
    """Audit trail entry recording an admin action for accountability."""

    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    username = db.Column(db.String(60), nullable=False)  # snapshot in case user is later removed
    action = db.Column(db.String(120), nullable=False)   # e.g. "order.status_update"
    details = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ActivityLog {self.username}: {self.action}>"


class Category(db.Model):
    """Perfume category, e.g. Men, Women, Unisex, Oud & Attar."""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)

    products = db.relationship(
        "Product", backref="category", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Category {self.name}>"


class Product(db.Model):
    """A perfume product sold in the shop."""

    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(40), unique=True, nullable=True, index=True)
    name = db.Column(db.String(150), nullable=False)
    brand = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text, nullable=True)

    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    discount_price = db.Column(db.Numeric(10, 2), nullable=True)
    stock = db.Column(db.Integer, nullable=False, default=0)
    volume_ml = db.Column(db.Integer, nullable=True, default=50)

    # Fragrance notes (comma separated for simplicity, displayed in an animated modal)
    top_notes = db.Column(db.String(255), nullable=True)
    heart_notes = db.Column(db.String(255), nullable=True)
    base_notes = db.Column(db.String(255), nullable=True)

    image_filename = db.Column(db.String(255), nullable=True)  # primary/cover image
    is_featured = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    order_items = db.relationship("OrderItem", backref="product", lazy=True)
    gallery_images = db.relationship(
        "ProductImage", backref="product", lazy=True,
        cascade="all, delete-orphan", order_by="ProductImage.sort_order"
    )
    reviews = db.relationship(
        "Review", backref="product", lazy=True, cascade="all, delete-orphan"
    )
    stock_alerts = db.relationship(
        "StockAlert", backref="product", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def effective_price(self):
        """Returns the discount price if set, otherwise the regular price."""
        return self.discount_price if self.discount_price else self.price

    @property
    def top_notes_list(self):
        return [n.strip() for n in (self.top_notes or "").split(",") if n.strip()]

    @property
    def heart_notes_list(self):
        return [n.strip() for n in (self.heart_notes or "").split(",") if n.strip()]

    @property
    def base_notes_list(self):
        return [n.strip() for n in (self.base_notes or "").split(",") if n.strip()]

    @property
    def approved_reviews(self):
        return [r for r in self.reviews if r.is_approved]

    @property
    def average_rating(self):
        approved = self.approved_reviews
        if not approved:
            return 0
        return round(sum(r.rating for r in approved) / len(approved), 1)

    def __repr__(self):
        return f"<Product {self.name}>"


class ProductImage(db.Model):
    """An additional gallery image for a Product (beyond the primary cover image)."""

    __tablename__ = "product_images"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ProductImage product_id={self.product_id}>"


class Review(db.Model):
    """A customer's star rating and comment on a Product."""

    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    customer_name = db.Column(db.String(150), nullable=False)
    rating = db.Column(db.Integer, nullable=False, default=5)  # 1-5
    comment = db.Column(db.Text, nullable=True)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Review {self.customer_name} {self.rating}*>"


class StockAlert(db.Model):
    """A 'notify me when back in stock' signup for an out-of-stock product."""

    __tablename__ = "stock_alerts"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    notified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<StockAlert product_id={self.product_id} phone={self.phone}>"


class Bank(db.Model):
    """
    An admin-managed payment account (bank or mobile-money provider such as
    Telebirr) shown to customers at checkout so they know where to send
    payment before uploading their receipt screenshot.
    """

    __tablename__ = "banks"

    id = db.Column(db.Integer, primary_key=True)
    bank_name = db.Column(db.String(100), nullable=False)       # e.g. "Telebirr", "CBE", "Bank of Abyssinia"
    account_name = db.Column(db.String(150), nullable=False)    # e.g. "Danu Perfume PLC"
    account_number = db.Column(db.String(60), nullable=False)
    logo_filename = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Bank {self.bank_name} - {self.account_number}>"


class DeliveryZone(db.Model):
    """A city/zone with a fixed delivery fee, used instead of (or alongside) the random fee."""

    __tablename__ = "delivery_zones"

    id = db.Column(db.Integer, primary_key=True)
    city_name = db.Column(db.String(100), unique=True, nullable=False)
    fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<DeliveryZone {self.city_name}: {self.fee}>"


class Coupon(db.Model):
    """A promo/discount code redeemable at checkout."""

    __tablename__ = "coupons"

    TYPE_PERCENT = "percent"
    TYPE_FIXED = "fixed"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    discount_type = db.Column(db.String(20), nullable=False, default=TYPE_PERCENT)
    discount_value = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    usage_limit = db.Column(db.Integer, nullable=True)   # None = unlimited
    used_count = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_valid(self):
        if not self.is_active:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        if self.usage_limit is not None and self.used_count >= self.usage_limit:
            return False
        return True

    def calculate_discount(self, subtotal):
        if self.discount_type == self.TYPE_PERCENT:
            return (subtotal * self.discount_value) / 100
        return min(self.discount_value, subtotal)

    def __repr__(self):
        return f"<Coupon {self.code}>"


class LoyaltyAccount(db.Model):
    """Simple points-balance account keyed by the customer's phone number."""

    __tablename__ = "loyalty_accounts"

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(30), unique=True, nullable=False, index=True)
    customer_name = db.Column(db.String(150), nullable=True)
    points = db.Column(db.Integer, default=0, nullable=False)
    total_spent = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    referral_code = db.Column(db.String(20), unique=True, nullable=True)
    referred_by_phone = db.Column(db.String(30), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<LoyaltyAccount {self.phone}: {self.points}pts>"


class Banner(db.Model):
    """An admin-editable homepage hero/promo banner (for holidays, sales, etc.)."""

    __tablename__ = "banners"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    subtitle = db.Column(db.String(255), nullable=True)
    image_filename = db.Column(db.String(255), nullable=True)
    cta_text = db.Column(db.String(60), nullable=True)
    cta_link = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Banner {self.title}>"


class Order(db.Model):
    """A guest checkout order, including delivery info and payment proof."""

    __tablename__ = "orders"

    STATUS_PENDING = "Pending"
    STATUS_APPROVED = "Approved"
    STATUS_OUT_FOR_DELIVERY = "Out for Delivery"
    STATUS_DELIVERED = "Delivered"
    STATUS_CANCELLED = "Cancelled"

    DELIVERY_STANDARD = "Standard Courier"
    DELIVERY_MOTORCYCLE = "Motorcycle Rider"
    DELIVERY_PICKUP = "Post Office Pickup"

    RISK_LOW = "Low"
    RISK_MEDIUM = "Medium"
    RISK_HIGH = "High"

    id = db.Column(db.Integer, primary_key=True)
    order_code = db.Column(db.String(20), unique=True, nullable=False)

    # Guest customer information
    customer_name = db.Column(db.String(150), nullable=False)
    customer_phone = db.Column(db.String(30), nullable=False)
    delivery_address = db.Column(db.String(255), nullable=False)
    city = db.Column(db.String(100), nullable=True)
    post_office_location = db.Column(db.String(150), nullable=True)
    delivery_type = db.Column(db.String(40), nullable=False, default=DELIVERY_STANDARD)
    rider_name = db.Column(db.String(100), nullable=True)
    rider_phone = db.Column(db.String(30), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Gift options
    is_gift = db.Column(db.Boolean, default=False, nullable=False)
    gift_message = db.Column(db.String(300), nullable=True)

    # Payment
    payment_method = db.Column(db.String(30), nullable=False, default="Telebirr")
    bank_id = db.Column(db.Integer, db.ForeignKey("banks.id"), nullable=True)
    payment_screenshot = db.Column(db.String(255), nullable=True)

    # Coupon / pricing breakdown
    coupon_code = db.Column(db.String(40), nullable=True)
    discount_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    subtotal_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    delivery_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    # Loyalty
    points_earned = db.Column(db.Integer, default=0, nullable=False)

    # Fraud / risk scoring
    risk_level = db.Column(db.String(20), nullable=False, default=RISK_LOW)
    risk_reasons = db.Column(db.String(255), nullable=True)

    status = db.Column(db.String(30), nullable=False, default=STATUS_PENDING)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = db.relationship(
        "OrderItem", backref="order", lazy=True, cascade="all, delete-orphan"
    )
    bank = db.relationship("Bank")

    def __repr__(self):
        return f"<Order {self.order_code} - {self.status}>"


class OrderItem(db.Model):
    """A single product line item within an Order."""

    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)

    product_name = db.Column(db.String(150), nullable=False)  # snapshot at purchase time
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    def __repr__(self):
        return f"<OrderItem {self.product_name} x{self.quantity}>"
