from tests.app import create_app

app = create_app(env_name='development')

if __name__ == '__main__':
    try:
        app.testing = True
        with app.test_client() as c:
            resp = c.get('/admin/dashboard')
            print('STATUS:', resp.status_code)
            print(resp.get_data(as_text=True)[:4000])
    except Exception as e:
        import traceback
        traceback.print_exc()
        print('EXC:', e)
