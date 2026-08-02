import unittest

from app import create_app
from models import db, User


class AuthTemplateRegressionTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app("development")
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_non_allowed_admin_username_is_denied(self):
        user = User(username="auth-test-admin", full_name="Auth Test Admin", email="auth-test-admin@example.com", role=None, is_admin=True)
        user.set_password("secret123")
        db.session.add(user)
        db.session.commit()

        response = self.client.post(
            "/login",
            data={"username": "auth-test-admin", "password": "secret123"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/account")

    def test_non_admin_usernames_are_not_reserved_for_customer_accounts(self):
        user = User(username="staff-user", full_name="Staff User", email="staff-user@example.com", role="order_manager", is_admin=True)
        user.set_password("secret123")
        db.session.add(user)
        db.session.commit()

        response = self.client.post(
            "/register",
            data={"full_name": "Customer One", "username": "staff-user", "password": "pass1234", "confirm_password": "pass1234"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_admin_dashboard_requires_login(self):
        response = self.client.get("/admin/dashboard", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_non_admin_user_is_blocked_from_admin_dashboard(self):
        customer = User(username="customer-user", full_name="Customer User", email="customer-user@example.com", role="order_manager", is_admin=True)
        customer.set_password("password123")
        db.session.add(customer)
        db.session.commit()

        self.client.post(
            "/login",
            data={"username": "customer-user", "password": "password123"},
            follow_redirects=False,
        )

        response = self.client.get("/admin/dashboard", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/account")


if __name__ == "__main__":
    unittest.main()
