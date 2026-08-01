import unittest

from app import create_app


class PostOfficeRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app("development")
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_post_offices_page_is_available(self):
        response = self.client.get("/post-offices")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Post Office", response.data)

    def test_post_offices_search_api_returns_matches(self):
        response = self.client.get("/api/post-offices?query=bole")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["results"])
        names = [item["name"].lower() for item in payload["results"]]
        self.assertTrue(any("bole" in name for name in names))


if __name__ == "__main__":
    unittest.main()
