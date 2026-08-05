from app import app
endpoints = [r.endpoint for r in app.url_map.iter_rules()]
print('update_account_settings' in endpoints)
print(endpoints)
