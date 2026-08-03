import os
os.environ['DATABASE_URL'] = 'sqlite:///./test.db'
from app import create_app
from models import db, Category

app = create_app('development')
app.config.update(TESTING=True)

with app.app_context():
    db.drop_all()
    db.create_all()
    print('categories_after_init', Category.query.count())
