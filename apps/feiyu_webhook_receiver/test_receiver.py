import base64
import hashlib
import hmac
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
import urllib.error
from email.message import Message

from cryptography.fernet import Fernet


ROOT = os.path.dirname(os.path.abspath(__file__))


class ReceiverAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temp_path = tempfile.mkdtemp(prefix=".test-data-", dir=ROOT)
        self.db_path = os.path.join(self.temp_path, "events.sqlite3")
        self.token = "test-path-secret-7461"
        self.key = Fernet.generate_key().decode("ascii")
        self.dedup_key = "test-dedup-key-should-be-long-enough"
        self.webhook_secret = "test-feiyu-static-secret"
        self.webhook_token = "test-feiyu-access-token"
        env_values = {
            "FEIYU_PATH_TOKEN": self.token,
            "FEIYU_DB_PATH": self.db_path,
            "FEIYU_FERNET_KEY": self.key,
            "FEIYU_DEDUP_KEY": self.dedup_key,
            "FEIYU_WEBHOOK_SECRET": self.webhook_secret,
            "FEIYU_WEBHOOK_TOKEN": self.webhook_token,
        }
        self.previous_env = {key: os.environ.get(key) for key in env_values}
        self.previous_env["FEIYU_FORWARD_URL"] = os.environ.get("FEIYU_FORWARD_URL")
        self.previous_env["FEIYU_FORWARD_SECRET"] = os.environ.get("FEIYU_FORWARD_SECRET")
        os.environ.update(env_values)
        os.environ.pop("FEIYU_FORWARD_URL", None)
        os.environ.pop("FEIYU_FORWARD_SECRET", None)
        self.addCleanup(self.restore_environment)

        module_name = "receiver_base_test_" + uuid.uuid4().hex
        spec = importlib.util.spec_from_file_location(
            module_name, os.path.join(ROOT, "receiver.py")
        )
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = self.module
        spec.loader.exec_module(self.module)
        self.addCleanup(lambda: sys.modules.pop(module_name, None))
        self.module.initialize_db()
        self.addCleanup(self.remove_temp_data)

    def restore_environment(self):
        for key, value in self.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def remove_temp_data(self):
        shutil.rmtree(self.temp_path, ignore_errors=True)

    def request(self, method, path, body=None, headers=None):
        message = Message()
        for name, value in (headers or {}).items():
            message[name] = value
        if body is not None and message.get("Content-Length") is None:
            message["Content-Length"] = str(len(body))
        handler = object.__new__(self.module.Handler)
        handler.path = path
        handler.headers = message
        handler.rfile = io.BytesIO(body or b"")
        responses = []
        handler.send_json = lambda status, response_body: responses.append(
            (status, response_body)
        )
        if method == "GET":
            handler.do_GET()
        else:
            handler.do_POST()
        return responses[-1]

    def signed_headers(self, clue_id, timestamp="1760000000", token=None):
        token = self.webhook_token if token is None else token
        message = "{}|{}|{}".format(clue_id, token, timestamp).encode("utf-8")
        digest_hex = hmac.new(self.webhook_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return {
            "Content-Type": "application/json",
            "Access-Token": token,
            "Timestamp": timestamp,
            "Signature": base64.b64encode(digest_hex.encode("ascii")).decode("ascii"),
        }

    def load_forwarder(self):
        db_path = os.path.join(self.temp_path, "forward.sqlite3")
        env_values = {
            "FEIYU_PATH_TOKEN": self.token,
            "FEIYU_DB_PATH": db_path,
            "FEIYU_FERNET_KEY": self.key,
            "FEIYU_DEDUP_KEY": self.dedup_key,
            "FEIYU_WEBHOOK_SECRET": self.webhook_secret,
            "FEIYU_WEBHOOK_TOKEN": self.webhook_token,
            "FEIYU_FORWARD_URL": "https://chejin.invalid/api/integrations/feiyu/leads",
            "FEIYU_FORWARD_SECRET": "test-chejin-forward-secret-at-least-32-chars",
        }
        previous = {key: os.environ.get(key) for key in env_values}
        os.environ.update(env_values)

        def restore_environment():
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore_environment)
        module_name = "receiver_test_" + uuid.uuid4().hex
        spec = importlib.util.spec_from_file_location(
            module_name, os.path.join(ROOT, "receiver.py")
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        self.addCleanup(lambda: sys.modules.pop(module_name, None))
        module.initialize_db()
        return module

    def enqueue_for_forwarding(self, module, source):
        body = json.dumps(source, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        event_id = str(uuid.uuid4())
        receipt_id = str(uuid.uuid4())
        received_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn = module.connect_db()
        try:
            conn.execute(
                "INSERT INTO feiyu_events "
                "(event_id, received_at, payload_hmac, content_type, payload_ciphertext) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event_id,
                    received_at,
                    module.make_payload_hmac(body),
                    "application/json",
                    module.FERNET.encrypt(body),
                ),
            )
            conn.execute(
                "INSERT INTO feiyu_receipts "
                "(receipt_id, event_id, received_at, is_duplicate, content_length) "
                "VALUES (?, ?, ?, 0, ?)",
                (receipt_id, event_id, received_at, len(body)),
            )
            conn.execute(
                "INSERT INTO feiyu_forward_outbox "
                "(receipt_id, event_id, status, attempts, next_attempt_epoch, created_at) "
                "VALUES (?, ?, 'pending', 0, 0, ?)",
                (receipt_id, event_id, received_at),
            )
            conn.commit()
        finally:
            conn.close()
        return receipt_id

    def read_outbox_row(self, module, receipt_id):
        conn = module.connect_db()
        try:
            return conn.execute(
                "SELECT status, attempts, last_http_status, next_attempt_epoch, delivered_at "
                "FROM feiyu_forward_outbox WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        finally:
            conn.close()

    def test_health_and_unknown_path(self):
        status, body = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8")), {"status": "ok"})
        status, _ = self.request("POST", "/webhooks/feiyu/clue/wrong", b"{}")
        self.assertEqual(status, 404)
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM feiyu_events").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_encrypted_durable_capture_and_idempotent_retry(self):
        payload = json.dumps({"clue_id": "sample-1", "telephone": "15500000000"}).encode("utf-8")
        path = "/webhooks/feiyu/clue/" + self.token
        headers = self.signed_headers("sample-1")
        status, response = self.request("POST", path, payload, headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response.decode("utf-8")), {"code": "0", "message": "success"})
        status, _ = self.request("POST", path, payload, headers)
        self.assertEqual(status, 200)

        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("SELECT payload_ciphertext FROM feiyu_events").fetchall()
            receipt_count = conn.execute("SELECT COUNT(*) FROM feiyu_receipts").fetchone()[0]
            outbox_count = conn.execute("SELECT COUNT(*) FROM feiyu_forward_outbox").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(receipt_count, 2)
        self.assertEqual(outbox_count, 2)
        ciphertext = rows[0][0]
        self.assertNotIn(b"15500000000", ciphertext)
        self.assertEqual(Fernet(self.key.encode("ascii")).decrypt(ciphertext), payload)

    def test_forward_mapping_headers_https_timeout_and_success(self):
        module = self.load_forwarder()
        source_fields = {
            "id": "f-1",
            "req_id": "r-2",
            "create_time": "2026-10-27 12:00:00",
            "adv_id": "a-3",
            "adv_name": "ad account",
            "ad_id": "ad-4",
            "ad_name": "campaign",
            "promotion_id": "p-5",
            "promotion_name": "promotion",
            "clue_source": "feed",
            "clue_data_source_detail": "paid",
            "business": "consulting",
        }
        source = {
            "clue_id": "must-not-leak",
            "name": "Sample Person",
            "telphone": "15500000000",
            "weixin": "sample-wechat",
            "email": "sample@example.test",
            "private_note": "must-not-leak-either",
        }
        source.update(source_fields)
        receipt_id = self.enqueue_for_forwarding(module, source)
        captured = {}

        class MockResponse(object):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size=-1):
                return b'{"code":"OK"}'

            def getcode(self):
                return 200

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            captured["timeout"] = timeout
            return MockResponse()

        module.urlopen = fake_urlopen
        self.assertTrue(module.deliver_outbox_once())

        request = captured["request"]
        self.assertEqual(request.full_url, "https://chejin.invalid/api/integrations/feiyu/leads")
        self.assertEqual(request.get_method(), "POST")
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(
            headers["x-feiyu-forward-secret"],
            "test-chejin-forward-secret-at-least-32-chars",
        )
        self.assertEqual(captured["timeout"], module.FORWARD_TIMEOUT_SECONDS)
        forwarded = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            set(forwarded),
            {"customer_name", "phones", "wechats", "emails", "custom_fields"},
        )
        self.assertEqual(forwarded["customer_name"], "Sample Person")
        self.assertEqual(forwarded["phones"], ["15500000000"])
        self.assertEqual(forwarded["wechats"], ["sample-wechat"])
        self.assertEqual(forwarded["emails"], ["sample@example.test"])
        self.assertEqual(forwarded["custom_fields"], {"feiyu": source_fields})
        self.assertNotIn("clue_id", request.data.decode("utf-8"))
        self.assertNotIn("private_note", request.data.decode("utf-8"))
        status, attempts, http_status, _next_attempt, delivered_at = self.read_outbox_row(
            module, receipt_id
        )
        self.assertEqual((status, attempts, http_status), ("delivered", 1, 200))
        self.assertTrue(delivered_at)

    def test_phone_duplicate_conflict_is_delivered(self):
        module = self.load_forwarder()
        receipt_id = self.enqueue_for_forwarding(
            module, {"name": "Sample Person", "telphone": "15500000000"}
        )

        def fake_urlopen(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url,
                409,
                "Conflict",
                {},
                io.BytesIO(b'{"code":"LEAD_PHONE_DUPLICATED"}'),
            )

        module.urlopen = fake_urlopen
        self.assertTrue(module.deliver_outbox_once())
        status, attempts, http_status, _next_attempt, delivered_at = self.read_outbox_row(
            module, receipt_id
        )
        self.assertEqual((status, attempts, http_status), ("delivered", 1, 409))
        self.assertTrue(delivered_at)

    def test_retryable_errors_stay_pending_and_other_4xx_fail(self):
        module = self.load_forwarder()
        cases = (
            ("network", None, "pending", None),
            ("http-500", 500, "pending", 500),
            ("http-408", 408, "pending", 408),
            ("http-425", 425, "pending", 425),
            ("http-429", 429, "pending", 429),
            ("http-400", 400, "failed", 400),
            ("http-409-other", 409, "failed", 409),
            ("http-422", 422, "failed", 422),
        )
        for case_name, response_status, expected_status, expected_http_status in cases:
            with self.subTest(case=case_name):
                module.DB_PATH = os.path.join(self.temp_path, case_name + ".sqlite3")
                module.initialize_db()
                receipt_id = self.enqueue_for_forwarding(
                    module, {"name": "Sample Person", "telphone": "15500000000"}
                )

                def fake_urlopen(request, timeout=None):
                    if response_status is None:
                        raise urllib.error.URLError("offline mock")
                    body = b'{"code":"OTHER_ERROR"}'
                    raise urllib.error.HTTPError(
                        request.full_url,
                        response_status,
                        "mock response",
                        {},
                        io.BytesIO(body),
                    )

                module.urlopen = fake_urlopen
                result = module.deliver_outbox_once()
                self.assertEqual(result, expected_status == "failed")
                status, attempts, http_status, next_attempt, delivered_at = self.read_outbox_row(
                    module, receipt_id
                )
                self.assertEqual(status, expected_status)
                self.assertEqual(attempts, 1)
                self.assertEqual(http_status, expected_http_status)
                self.assertGreater(next_attempt, time.time())
                self.assertIsNone(delivered_at)

    def test_missing_phone_is_omitted_and_downstream_4xx_fails(self):
        module = self.load_forwarder()
        receipt_id = self.enqueue_for_forwarding(module, {"name": "No Phone"})
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["data"] = json.loads(request.data.decode("utf-8"))
            raise urllib.error.HTTPError(
                request.full_url,
                422,
                "Validation error",
                {},
                io.BytesIO(b'{"code":"VALIDATION_ERROR"}'),
            )

        module.urlopen = fake_urlopen
        self.assertTrue(module.deliver_outbox_once())
        self.assertEqual(captured["data"], {"customer_name": "No Phone"})
        status, attempts, http_status, _next_attempt, delivered_at = self.read_outbox_row(
            module, receipt_id
        )
        self.assertEqual((status, attempts, http_status), ("failed", 1, 422))
        self.assertIsNone(delivered_at)

    def test_http_target_must_use_https(self):
        module = self.load_forwarder()
        os.environ["FEIYU_FORWARD_URL"] = "http://chejin.invalid/api/integrations/feiyu/leads"
        with self.assertRaises(RuntimeError):
            module._forward_configuration()
    def test_invalid_or_missing_signature_is_rejected_before_storage(self):
        payload = json.dumps({"clue_id": "sample-2", "telephone": "15500000001"}).encode("utf-8")
        path = "/webhooks/feiyu/clue/" + self.token
        headers = self.signed_headers("sample-2")
        headers.pop("Signature")
        status, _ = self.request("POST", path, payload, headers)
        self.assertEqual(status, 401)

        headers = self.signed_headers("different-clue")
        status, _ = self.request("POST", path, payload, headers)
        self.assertEqual(status, 401)

        duplicate_id_payload = b'{"clue_id":"sample-2","clue_id":"different-clue"}'
        headers = self.signed_headers("sample-2")
        status, _ = self.request("POST", path, duplicate_id_payload, headers)
        self.assertEqual(status, 401)

        headers = self.signed_headers("sample-2")
        headers["Signature"] = base64.b64encode(b"wrong signature").decode("ascii")
        status, _ = self.request("POST", path, payload, headers)
        self.assertEqual(status, 401)

        message = "sample-2|{}|1760000000".format(self.webhook_token).encode("utf-8")
        raw_digest = hmac.new(self.webhook_secret.encode("utf-8"), message, hashlib.sha256).digest()
        headers = self.signed_headers("sample-2")
        headers["Signature"] = base64.b64encode(raw_digest).decode("ascii")
        status, _ = self.request("POST", path, payload, headers)
        self.assertEqual(status, 401)

        headers = self.signed_headers("sample-2")
        headers["Access-Token"] = "wrong-token"
        status, _ = self.request("POST", path, payload, headers)
        self.assertEqual(status, 401)

        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM feiyu_events").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_oversized_payload_is_rejected(self):
        status, _ = self.request(
            "POST",
            "/webhooks/feiyu/clue/" + self.token,
            b"x" * (1024 * 1024 + 1),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 413)


if __name__ == "__main__":
    unittest.main(verbosity=2)

