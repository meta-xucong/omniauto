# Feiyu webhook receiver

Small Python service that accepts signed Feiyu lead webhooks, stores the original request body encrypted in SQLite, and forwards mapped lead fields to Chejin AI Sales through a persistent outbox.

## Runtime

- Python 3.6 or newer
- `cryptography`
- SQLite (Python standard library)

Set these environment variables before starting `receiver.py`:

- `FEIYU_PATH_TOKEN`: random URL token used by the webhook endpoint.
- `FEIYU_DB_PATH`: SQLite database path.
- `FEIYU_FERNET_KEY`: Fernet key used to encrypt stored request bodies.
- `FEIYU_DEDUP_KEY`: HMAC key used to identify byte-identical webhook retries.
- `FEIYU_WEBHOOK_SECRET` and `FEIYU_WEBHOOK_TOKEN`: Feiyu signature credentials.
- `FEIYU_FORWARD_URL`: HTTPS Chejin endpoint ending in `/api/integrations/feiyu/leads`.
- `FEIYU_FORWARD_SECRET`: shared service secret sent in `X-Feiyu-Forward-Secret`.

`FEIYU_CLUE_ID_FIELD` optionally selects the top-level clue ID field and defaults to `clue_id`. The forwarder starts only when both forwarding settings are configured.

## Behavior

- `GET /healthz` returns a small health response.
- `POST /webhooks/feiyu/clue/<FEIYU_PATH_TOKEN>` verifies the configured Feiyu signature, then persists the original body encrypted before acknowledging the webhook.
- Each accepted webhook receipt gets its own outbox entry. Retries use exponential backoff and keep pending entries until delivery succeeds.
- Forwarding maps `name` to `customer_name`, `telphone` to `phones`, optional `weixin` to `wechats`, and optional `email` to `emails`. Selected source metadata is preserved under `custom_fields.feiyu`; the full Feiyu payload is not forwarded.
- Chejin's native lead creation flow handles phone deduplication and sales assignment. A `409` response with `LEAD_PHONE_DUPLICATED` acknowledges the receipt as handled.
- The service does not log webhook request paths, headers, or bodies.

## Local tests

Install `cryptography`, then run:

```sh
python test_receiver.py
```

Tests use temporary SQLite databases and mocked downstream HTTP responses; they do not contact Feiyu or a live Chejin service.

