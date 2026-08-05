from models import Customer
cols=[c.name for c in Customer.__table__.columns]
print('preferred_language' in cols)
print(cols)
