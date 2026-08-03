import os
os.environ['DATABASE_URL'] = 'sqlite:///./test.db'
from app import create_app
from models import db, User

app = create_app('development')
app.config.update(TESTING=True)

with app.app_context():
    db.drop_all()
    db.create_all()
    user = User(username='Danuta', full_name='Danuta', role='super_admin', is_admin=True)
    user.set_password('#Danu1122')
    db.session.add(user)
    db.session.commit()

    client = app.test_client()
    resp = client.post('/login', data={'username': 'Danuta', 'password': '#Danu1122'}, follow_redirects=False)
    print(resp.status_code)
    print(resp.headers.get('Location'))
