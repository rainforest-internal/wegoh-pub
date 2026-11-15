"""Integration checks for the running private API. Read the token from the environment."""
import hashlib
import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.environ.get("WEGOH_API_URL", "http://127.0.0.1:18080")
KEY = os.environ["WEGOH_API_KEY"]
PAYLOAD = b'{"fixture":"WegoH synthetic development asset","version":1}'


def call(path, data=None, key=KEY, media_type="application/json", extra_headers=None):
    headers = {"Content-Type": media_type}
    if key:
        headers["Authorization"] = "Bearer " + key
    headers.update(extra_headers or {})
    request = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


class ServerIntegrationTests(unittest.TestCase):
    def test_health(self):
        self.assertEqual(call("/health/live", key=None)[0], 200)
        self.assertEqual(call("/health/ready", key=None)[0], 200)

    def test_authentication_on_read_and_write(self):
        for key in (None, "incorrect-development-token"):
            self.assertEqual(call("/v1/dev/status", key=key)[0], 401)
            self.assertEqual(call("/v1/assets", data=PAYLOAD, key=key)[0], 401)
            self.assertEqual(call("/v1/assets/" + "a" * 64, key=key)[0], 401)

    def test_asset_round_trip_and_duplicate(self):
        expected = hashlib.sha256(PAYLOAD).hexdigest()
        code, _, body = call("/v1/assets", data=PAYLOAD)
        self.assertEqual(code, 201)
        self.assertEqual(json.loads(body)["id"], expected)
        self.assertEqual(json.loads(body)["byte_size"], len(PAYLOAD))
        # Identical content must return the same immutable ID and original metadata.
        code, _, body = call("/v1/assets", data=PAYLOAD, media_type="audio/wav")
        self.assertEqual(code, 201)
        self.assertEqual(json.loads(body)["media_type"], "application/json")
        code, headers, body = call("/v1/assets/" + expected)
        self.assertEqual(code, 200)
        self.assertEqual(body, PAYLOAD)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_invalid_inputs(self):
        self.assertEqual(call("/v1/assets", data=b"")[0], 400)
        self.assertEqual(call("/v1/assets", data=b"x", media_type="text/html")[0], 415)
        self.assertEqual(call("/v1/assets", data=b"x", extra_headers={"Content-Length": "26214401"})[0], 413)
        self.assertEqual(call("/v1/assets/not-a-checksum")[0], 404)
        self.assertEqual(call("/v1/assets/" + "0" * 64)[0], 404)

    def test_product_features_are_not_claimed(self):
        code, _, body = call("/v1/dev/status")
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)["pack_publishing"])
        self.assertFalse(json.loads(body)["trip_rooms"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
