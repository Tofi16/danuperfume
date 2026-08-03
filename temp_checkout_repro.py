import importlib
import io
import os

os.environ['DATABASE_URL'] = 'sqlite:///./test_checkout.db'

import app as app_module
app_module = importlib.reload(app_module)
app = app_module.create_app('development')
app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

with app.app_context():
    from models import db, Product, Category
    db.drop_all()
    db.create_all()
    cat = Category(name='Test', slug='test')
    db.session.add(cat)
    db.session.commit()
    p = Product(name='Test Perfume', price=100, stock=5, category_id=cat.id)
    db.session.add(p)
    db.session.commit()
    print('product_id', p.id)

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['cart'] = {str(p.id): 1}
    data = {
        'customer_name': 'Test',
        'customer_phone': '0911111111',
        'delivery_address': 'Addis',
        'city': 'Addis Ababa',
        'post_office_location': 'Main',
        'delivery_type': 'Standard Courier',
        'payment_method': 'Telebirr',
        'notes': 'hi',
        'coupon_code': '',
        'delivery_fee': '100',
    }
    file_data = (io.BytesIO(b'fake-image'), 'test.png')
    resp = client.post(
        '/checkout',
        data={**data, 'payment_screenshot': (file_data[0], file_data[1])},
        content_type='multipart/form-data',
    )
    print('status', resp.status_code)
    print(resp.get_data(as_text=True)[:4000])
