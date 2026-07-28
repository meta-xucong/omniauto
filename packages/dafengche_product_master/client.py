"""Dafengche Open Platform client and request-signing contract."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from .contract import CAR_DETAIL_API, CAR_IDS_API, CAR_PICTURES_API, CAR_UPDATE_API, SHOP_API


PRODUCTION_ENDPOINT = "https://openapi.souche.com/v3"


class DafengcheTransport(Protocol):
    """Host-provided HTTP transport; credentials must never be logged by the core."""

    def post(self, url: str, payload: Mapping[str, str], *, timeout_seconds: float) -> Mapping[str, Any]:
        """Send one request and return the decoded JSON response."""


@dataclass(frozen=True)
class DafengcheCredentials:
    app_key: str
    app_secret: str


def build_signature(parameters: Mapping[str, str], app_secret: str) -> str:
    """Implement the documented v3 request signing algorithm.

    Parameters are sorted by key, joined as ``key=value`` pairs with ``&``,
    base64-encoded as UTF-8, prefixed by the secret, then SHA-1 hashed.  The
    caller must omit ``sign`` from ``parameters``.
    """

    if "sign" in parameters:
        raise ValueError("sign must not be included when calculating Dafengche signature")
    canonical = "&".join(f"{key}={parameters[key]}" for key in sorted(parameters))
    encoded = base64.b64encode(canonical.encode("utf-8")).decode("ascii")
    return hashlib.sha1(f"{app_secret}{encoded}".encode("utf-8")).hexdigest()


class DafengcheReadOnlyClient:
    """Minimal official read-only API client.

    The client returns upstream payloads without schema translation.  Mapping
    into local records is intentionally handled by the mirror service.
    """

    def __init__(
        self,
        *,
        credentials: DafengcheCredentials,
        transport: DafengcheTransport,
        endpoint: str = PRODUCTION_ENDPOINT,
        timeout_seconds: float = 15.0,
        now_seconds: Callable[[], float] = time.time,
    ) -> None:
        if not credentials.app_key or not credentials.app_secret:
            raise ValueError("Dafengche app_key and app_secret are required")
        self.credentials = credentials
        self.transport = transport
        self.endpoint = str(endpoint or PRODUCTION_ENDPOINT)
        self.timeout_seconds = float(timeout_seconds)
        self._now_seconds = now_seconds

    def build_request(self, api: str, data: Mapping[str, Any], *, timestamp: int | None = None) -> dict[str, str]:
        if not api:
            raise ValueError("Dafengche API name is required")
        request = {
            "api": str(api),
            "appKey": self.credentials.app_key,
            "timestamp": str(int(self._now_seconds() if timestamp is None else timestamp)),
            "data": json.dumps(dict(data), ensure_ascii=False, separators=(",", ":")),
        }
        request["sign"] = build_signature(request, self.credentials.app_secret)
        return request

    def call(self, api: str, data: Mapping[str, Any]) -> Any:
        response = self.transport.post(
            self.endpoint,
            self.build_request(api, data),
            timeout_seconds=self.timeout_seconds,
        )
        if not isinstance(response, Mapping):
            raise ValueError("Dafengche response must be a JSON object")
        if response.get("success") is False:
            raise RuntimeError(f"Dafengche upstream rejected request: {response.get('message') or response.get('error') or 'unknown'}")
        return copy.deepcopy(response.get("data", response))

    def get_shop(self, *, app_id: str, shop_code: str) -> Any:
        return self.call(SHOP_API, {"appId": app_id, "shopCode": shop_code})

    def list_car_ids(self, *, app_id: str, operator: str, shop_code: str, operation_phase: str) -> Any:
        return self.call(
            CAR_IDS_API,
            {
                "appId": app_id,
                "operator": operator,
                "shopCode": shop_code,
                "operationPhase": operation_phase,
            },
        )

    def get_car_detail(self, *, app_id: str, operator: str, car_id: str) -> Any:
        return self.call(CAR_DETAIL_API, {"appId": app_id, "operator": operator, "carId": car_id})

    def get_car_pictures(self, *, app_id: str, car_id: str) -> Any:
        return self.call(CAR_PICTURES_API, {"appId": app_id, "carId": car_id})


class DafengcheOpenPlatformClient(DafengcheReadOnlyClient):
    """Additive client for explicitly authorized Dafengche write operations.

    The mirror sync service still depends on :class:`DafengcheReadOnlyClient`
    and never calls this method.  Hosts must wire this class only inside an
    operator-confirmed writeback workflow.
    """

    def update_car(self, *, update_param: Mapping[str, Any]) -> Any:
        if not isinstance(update_param, Mapping):
            raise ValueError("Dafengche update_car requires update_param to be a mapping")
        return self.call(CAR_UPDATE_API, {"updateParam": copy.deepcopy(dict(update_param))})
