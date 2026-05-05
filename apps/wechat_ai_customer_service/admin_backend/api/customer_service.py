"""Customer-service workbench APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..services.customer_service_settings import CustomerServiceSettings
from ..services.customer_service_runtime import CustomerServiceRuntime


router = APIRouter(prefix="/api/customer-service", tags=["customer-service"])


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return {"ok": True, "item": CustomerServiceSettings().summary()}


@router.put("/settings")
def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    service = CustomerServiceSettings()
    settings = service.save(payload or {})
    return {"ok": True, "item": service.summary() | {"settings": settings}}


@router.get("/runtime/status")
def runtime_status() -> dict[str, Any]:
    return {"ok": True, "item": CustomerServiceRuntime().status()}


@router.post("/runtime/start")
def start_runtime() -> dict[str, Any]:
    return CustomerServiceRuntime().start()


@router.post("/runtime/stop")
def stop_runtime() -> dict[str, Any]:
    return CustomerServiceRuntime().stop()
