from tests.app import create_app

app = create_app(env_name='development')
app.testing = True
paths = [
    '/',
    '/admin',
    '/admin/login',
    '/admin/dashboard',
    '/register',
    '/login',
    '/api/check-username?username=Danuta'
]

if __name__ == '__main__':
    with app.test_client() as c:
        for p in paths:
            try:
                resp = c.get(p)
                print(f"{p} -> {resp.status_code}")
            except Exception as e:
                import traceback
                print(f"{p} -> EXCEPTION: {e}")
                traceback.print_exc()
