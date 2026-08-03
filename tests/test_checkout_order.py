import importlib.util
import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_checkout.db")

app_spec = importlib.util.spec_from_file_location("danu_app", os.path.join(ROOT, "app.py"))
app_module = importlib.util.module_from_spec(app_spec)
assert app_spec.loader is not None
app_spec.loader.exec_module(app_module)
create_app = app_module.create_app

from models import Category, LoyaltyAccount, Order, Product, db


def test_checkout_handles_loyalty_account_with_null_points(tmp_path, monkeypatch):
    db_path = tmp_path / "test_checkout.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    monkeypatch.chdir(ROOT)

    app = create_app("development")
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    with app.app_context():
        db.drop_all()
        db.create_all()

        category = Category(name="Test", slug="test")
        db.session.add(category)
        db.session.commit()

        product = Product(name="Test Perfume", price=100, stock=5, category_id=category.id)
        db.session.add(product)
        db.session.commit()

        loyalty_account = LoyaltyAccount(phone="0911111111", customer_name="Test", points=None, total_spent=None)
        db.session.add(loyalty_account)
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as session:
                session["cart"] = {str(product.id): 1}

            response = client.post(
                "/checkout",
                data={
                    "customer_name": "Test",
                    "customer_phone": "0911111111",
                    "delivery_address": "Addis",
                    "city": "Addis Ababa",
                    "post_office_location": "Main",
                    "delivery_type": "Standard Courier",
                    "payment_method": "Telebirr",
                    "notes": "hi",
                    "coupon_code": "",
                    "delivery_fee": "100",
                    "payment_screenshot": (io.BytesIO(b"fake-image"), "test.png"),
                },
                content_type="multipart/form-data",
            )

            assert response.status_code == 200
            assert Order.query.count() == 1

            loyalty_account = LoyaltyAccount.query.filter_by(phone="0911111111").first()
            assert loyalty_account is not None
            assert loyalty_account.points is not None
            assert loyalty_account.points >= 0
            assert loyalty_account.total_spent is not None
