from wsgi import app

if __name__ == '__main__':
    try:
        with app.test_client() as c:
            resp = c.get('/admin')
            print('STATUS:', resp.status)
            data = resp.get_data(as_text=True)
            print('\n--- RESPONSE START ---\n')
            print(data[:4000])
            print('\n--- RESPONSE END ---')
    except Exception as e:
        import traceback
        traceback.print_exc()
        print('EXCEPTION:', e)
