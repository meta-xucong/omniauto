#!/usr/bin/env python3
"""Small, isolated Feiyu webhook receiver for Python 3.6+.

The webhook payload is deliberately retained as encrypted raw bytes. Feiyu lets
operators choose the outgoing field mapping, so this receiver reads the
configured top-level clue ID for signature validation and preserves every field.
"""

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from cryptography.fernet import Fernet


MAX_BODY_BYTES = 1024 * 1024
SUCCESS_BODY = b'{"code":"0","message":"success"}'
MAX_CONCURRENT_REQUESTS = 16
SOCKET_TIMEOUT_SECONDS = 15
FORWARD_TIMEOUT_SECONDS = 10


def required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("Missing required environment setting: " + name)
    return value


def required_secret_env(name):
    value = os.environ.get(name, "")
    if not value.strip():
        raise RuntimeError("Missing required environment setting: " + name)
    return value


PATH_TOKEN = required_env("FEIYU_PATH_TOKEN")
DB_PATH = required_env("FEIYU_DB_PATH")
FERNET = Fernet(required_env("FEIYU_FERNET_KEY").encode("ascii"))
DEDUP_KEY = required_env("FEIYU_DEDUP_KEY").encode("ascii")
WEBHOOK_SECRET = required_secret_env("FEIYU_WEBHOOK_SECRET")
WEBHOOK_TOKEN = required_secret_env("FEIYU_WEBHOOK_TOKEN")
CLUE_ID_FIELD = os.environ.get("FEIYU_CLUE_ID_FIELD", "clue_id").strip()
if not CLUE_ID_FIELD:
    raise RuntimeError("FEIYU_CLUE_ID_FIELD must not be empty")
EXPECTED_PATH = "/webhooks/feiyu/clue/" + PATH_TOKEN


def connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def initialize_db():
    parent = os.path.dirname(DB_PATH)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700)
    old_umask = os.umask(0o077)
    try:
        conn = connect_db()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS feiyu_events (
                    event_id TEXT PRIMARY KEY,
                    received_at TEXT NOT NULL,
                    payload_hmac TEXT NOT NULL UNIQUE,
                    content_type TEXT NOT NULL,
                    payload_ciphertext BLOB NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS feiyu_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    is_duplicate INTEGER NOT NULL CHECK (is_duplicate IN (0, 1)),
                    content_length INTEGER NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feiyu_receipts_received_at "
                "ON feiyu_receipts(received_at)"
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS feiyu_forward_outbox (
                    receipt_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'failed')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_epoch REAL NOT NULL DEFAULT 0,
                    last_http_status INTEGER,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feiyu_forward_outbox_pending "
                "ON feiyu_forward_outbox(status, next_attempt_epoch, created_at)"
            )
            conn.commit()
        finally:
            conn.close()
    finally:
        os.umask(old_umask)
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def make_payload_hmac(body):
    return hmac.new(DEDUP_KEY, body, hashlib.sha256).hexdigest()


def make_feiyu_signature(clue_id, token, timestamp):
    """Build Feiyu's documented keyed SHA-256 signature in Base64 form."""
    message = "{}|{}|{}".format(clue_id, token, timestamp).encode("utf-8")
    digest_hex = hmac.new(WEBHOOK_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return base64.b64encode(digest_hex.encode("ascii")).decode("ascii")


def extract_clue_id(body):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        payload = json.loads(body.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    clue_id = payload.get(CLUE_ID_FIELD)
    if isinstance(clue_id, bool) or not isinstance(clue_id, (str, int)):
        return None
    clue_id = str(clue_id).strip()
    if not clue_id or len(clue_id) > 256:
        return None
    return clue_id


def _forward_configuration():
    target = os.environ.get("FEIYU_FORWARD_URL", "").strip()
    secret = os.environ.get("FEIYU_FORWARD_SECRET", "").strip()
    if not target and not secret:
        return None, None
    if not target or len(secret) < 32:
        raise RuntimeError("Feiyu forwarding requires FEIYU_FORWARD_URL and a 32-character FEIYU_FORWARD_SECRET")
    parsed = urlsplit(target)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("FEIYU_FORWARD_URL must use HTTPS")
    return target, secret


def _has_forward_value(value):
    return value is not None and not (isinstance(value, str) and not value.strip())


def _map_forward_payload(source):
    """Build only the fields accepted by the Chejin Feiyu integration."""
    mapped = {}
    if "name" in source:
        mapped["customer_name"] = source["name"]
    phone = source.get("telphone")
    if _has_forward_value(phone):
        mapped["phones"] = [phone]
    for source_key, target_key in (("weixin", "wechats"), ("email", "emails")):
        value = source.get(source_key)
        if _has_forward_value(value):
            mapped[target_key] = [value]

    source_fields = (
        "id",
        "req_id",
        "create_time",
        "adv_id",
        "adv_name",
        "ad_id",
        "ad_name",
        "promotion_id",
        "promotion_name",
        "clue_source",
        "clue_data_source_detail",
        "business",
    )
    feiyu_fields = {key: source[key] for key in source_fields if key in source}
    if feiyu_fields:
        mapped["custom_fields"] = {"feiyu": feiyu_fields}
    return mapped


def _record_forward_result(receipt_id, status, http_status):
    conn = connect_db()
    try:
        if status == "delivered":
            conn.execute(
                "UPDATE feiyu_forward_outbox "
                "SET status = 'delivered', last_http_status = ?, delivered_at = ? "
                "WHERE receipt_id = ? AND status = 'pending'",
                (
                    http_status,
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    receipt_id,
                ),
            )
        else:
            conn.execute(
                "UPDATE feiyu_forward_outbox "
                "SET status = ?, last_http_status = ? "
                "WHERE receipt_id = ? AND status = 'pending'",
                (status, http_status, receipt_id),
            )
        conn.commit()
    finally:
        conn.close()


def deliver_outbox_once():
    """Map a stored Feiyu clue to the required Chejin fields and deliver it."""
    target, secret = _forward_configuration()
    if not target:
        return False
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT o.receipt_id, o.attempts, e.payload_ciphertext "
            "FROM feiyu_forward_outbox o JOIN feiyu_events e ON e.event_id = o.event_id "
            "WHERE o.status = 'pending' AND o.next_attempt_epoch <= ? "
            "ORDER BY o.created_at LIMIT 1",
            (time.time(),),
        ).fetchone()
        if row is None:
            return False
        receipt_id, previous_attempts, ciphertext = row
        attempt = int(previous_attempts) + 1
        delay = min(5 * (2 ** min(attempt - 1, 10)), 3600)
        conn.execute(
            "UPDATE feiyu_forward_outbox SET attempts = ?, next_attempt_epoch = ? WHERE receipt_id = ? AND status = 'pending'",
            (attempt, time.time() + delay, receipt_id),
        )
        conn.commit()
    finally:
        conn.close()

    response_status = None
    try:
        source = json.loads(FERNET.decrypt(ciphertext).decode("utf-8"))
        if not isinstance(source, dict):
            raise ValueError("stored Feiyu payload is not a JSON object")
        mapped = _map_forward_payload(source)
        body = json.dumps(mapped, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            target,
            data=body,
            headers={"Content-Type": "application/json", "X-Feiyu-Forward-Secret": secret},
            method="POST",
        )
        try:
            with urlopen(request, timeout=FORWARD_TIMEOUT_SECONDS) as response:
                response_body = response.read(4096)
                response_status = response.getcode()
        except HTTPError as response:
            response_status = response.code
            try:
                response_body = response.read(4096)
            except OSError:
                response_body = b""
    except Exception:
        _record_forward_result(receipt_id, "pending", response_status)
        # The exception message is intentionally omitted: upstream error bodies
        # can contain customer data or credentials.
        return False

    try:
        acknowledgement = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        acknowledgement = {}
    if not isinstance(acknowledgement, dict):
        acknowledgement = {}

    duplicate = (
        response_status == 409
        and acknowledgement.get("code") == "LEAD_PHONE_DUPLICATED"
    )
    accepted = (
        response_status is not None
        and 200 <= response_status < 300
        and acknowledgement.get("code") == "OK"
    )
    if duplicate or accepted:
        _record_forward_result(receipt_id, "delivered", response_status)
        return True

    if (
        response_status is not None
        and 400 <= response_status < 500
        and response_status not in (408, 425, 429)
    ):
        _record_forward_result(receipt_id, "failed", response_status)
        return True

    _record_forward_result(receipt_id, "pending", response_status)
    return False


def _forwarder_loop():
    while True:
        try:
            delivered = deliver_outbox_once()
        except Exception:
            # Keep receiver availability independent from downstream settings.
            delivered = False
        if not delivered:
            time.sleep(2)


def start_forwarder():
    target, _secret = _forward_configuration()
    if not target:
        return None
    thread = threading.Thread(target=_forwarder_loop, name="feiyu-forwarder", daemon=True)
    thread.start()
    return thread


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, request_handler):
        self.request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
        super(ThreadingHTTPServer, self).__init__(server_address, request_handler)

    def process_request(self, request, client_address):
        if not self.request_slots.acquire(False):
            self.shutdown_request(request)
            return
        try:
            super(ThreadingHTTPServer, self).process_request(request, client_address)
        except Exception:
            self.request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super(ThreadingHTTPServer, self).process_request_thread(request, client_address)
        finally:
            self.request_slots.release()

    def handle_error(self, _request, _client_address):
        # Avoid the standard traceback formatter, which may include request data.
        return


class Handler(BaseHTTPRequestHandler):
    server_version = "FeiyuReceiver"
    sys_version = ""

    def setup(self):
        self.request.settimeout(SOCKET_TIMEOUT_SECONDS)
        super(Handler, self).setup()

    def log_message(self, _format, *_args):
        # Never write request paths, headers, or payloads to logs.
        return

    def send_json(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlsplit(self.path).path == "/healthz":
            self.send_json(200, b'{"status":"ok"}')
            return
        self.send_json(404, b'{"code":"404","message":"not found"}')

    def do_POST(self):
        if urlsplit(self.path).path != EXPECTED_PATH:
            self.send_json(404, b'{"code":"404","message":"not found"}')
            return

        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except (TypeError, ValueError):
            length = -1
        if length < 0:
            self.send_json(411, b'{"code":"411","message":"content length required"}')
            return
        if length > MAX_BODY_BYTES:
            self.send_json(413, b'{"code":"413","message":"payload too large"}')
            return

        body = self.rfile.read(length)
        if len(body) != length or not body:
            self.send_json(400, b'{"code":"400","message":"invalid body"}')
            return

        token_headers = self.headers.get_all("Access-Token", [])
        timestamp_headers = self.headers.get_all("Timestamp", [])
        signature_headers = self.headers.get_all("Signature", [])
        if len(token_headers) != 1 or len(timestamp_headers) != 1 or len(signature_headers) != 1:
            self.send_json(401, b'{"code":"401","message":"invalid signature"}')
            return
        token = token_headers[0]
        timestamp = timestamp_headers[0]
        signature = signature_headers[0]
        clue_id = extract_clue_id(body)
        if not token or not timestamp or not signature or clue_id is None:
            self.send_json(401, b'{"code":"401","message":"invalid signature"}')
            return
        if not hmac.compare_digest(token.encode("utf-8"), WEBHOOK_TOKEN.encode("utf-8")):
            self.send_json(401, b'{"code":"401","message":"invalid signature"}')
            return
        expected_signature = make_feiyu_signature(clue_id, token, timestamp)
        if not hmac.compare_digest(signature.encode("utf-8"), expected_signature.encode("ascii")):
            self.send_json(401, b'{"code":"401","message":"invalid signature"}')
            return

        ciphertext = FERNET.encrypt(body)
        payload_hmac = make_payload_hmac(body)
        content_type = self.headers.get("Content-Type", "")[:128]
        received_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn = None
        try:
            conn = connect_db()
            cursor = conn.execute(
                "INSERT OR IGNORE INTO feiyu_events "
                "(event_id, received_at, payload_hmac, content_type, payload_ciphertext) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), received_at, payload_hmac, content_type, sqlite3.Binary(ciphertext)),
            )
            event_row = conn.execute(
                "SELECT event_id FROM feiyu_events WHERE payload_hmac = ?",
                (payload_hmac,),
            ).fetchone()
            if event_row is None:
                raise sqlite3.IntegrityError("accepted payload was not persisted")
            receipt_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO feiyu_receipts "
                "(receipt_id, event_id, received_at, is_duplicate, content_length) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    receipt_id,
                    event_row[0],
                    received_at,
                    1 if cursor.rowcount == 0 else 0,
                    length,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO feiyu_forward_outbox "
                "(receipt_id, event_id, status, attempts, next_attempt_epoch, created_at) "
                "VALUES (?, ?, 'pending', 0, 0, ?)",
                (receipt_id, event_row[0], received_at),
            )
            conn.commit()
        except Exception:
            if conn is not None:
                conn.rollback()
            self.send_json(500, b'{"code":"500","message":"storage unavailable"}')
            return
        finally:
            if conn is not None:
                conn.close()

        # Feiyu retries on non-success responses. Return success only after the
        # durable insert (or recognition of an identical retry) has completed.
        self.send_json(200, SUCCESS_BODY)


def main():
    initialize_db()
    start_forwarder()
    host = os.environ.get("FEIYU_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("FEIYU_BIND_PORT", "8781"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()

