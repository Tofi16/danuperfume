"""
models.py
SQLAlchemy ORM models for the Danu Perfume application.

Models:
    - User        : Admin/staff accounts (Flask-Login integration)
    - Category     : Perfume categories (e.g. Men, Women, Unisex, Oud)
    - Product      : Perfume products with fragrance notes and pricing
    - Order        : A guest checkout order
    - OrderItem    : Individual line items belonging to an Order
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """Admin/staff user account used to access the admin dashboard."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False, default="Admin")
    username = db.Column(db.String(60), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    @property
    def username(self):
        return self.email

    @username.setter
    def username(self, value):
        self.email = value

    def __repr__(self):
        return f"<User {self.email}>"


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

    image_filename = db.Column(db.String(255), nullable=True)
    is_featured = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    order_items = db.relationship("OrderItem", backref="product", lazy=True)

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

    def __repr__(self):
        return f"<Product {self.name}>"


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

    id = db.Column(db.Integer, primary_key=True)
    order_code = db.Column(db.String(20), unique=True, nullable=False)

    # Guest customer information
    customer_name = db.Column(db.String(150), nullable=False)
    customer_phone = db.Column(db.String(30), nullable=False)
    delivery_address = db.Column(db.String(255), nullable=False)
    city = db.Column(db.String(100), nullable=True)
    post_office_location = db.Column(db.String(150), nullable=True)
    delivery_type = db.Column(db.String(40), nullable=False, default=DELIVERY_STANDARD)
    notes = db.Column(db.Text, nullable=True)

    # Payment
    payment_method = db.Column(db.String(30), nullable=False, default="Telebirr")
    bank_id = db.Column(db.Integer, db.ForeignKey("banks.id"), nullable=True)
    payment_screenshot = db.Column(db.String(255), nullable=True)

    subtotal_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    delivery_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
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
