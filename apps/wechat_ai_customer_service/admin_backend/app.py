"""FastAPI entry point for the local WeChat customer-service knowledge admin."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.candidates import router as candidates_router
from .api.diagnostics import router as diagnostics_router
from .api.drafts import router as drafts_router
from .api.generator import router as generator_router
from .api.knowledge import router as knowledge_router
from .api.learning import router as learning_router
from .api.rag import router as rag_router
from .api.system import router as system_router
from .api.uploads import router as uploads_router
from .api.versions import router as versions_router


APP_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(
        title="WeChat AI Customer Service Admin",
        version="0.1.0",
        description="Local knowledge admin console for the OmniAuto WeChat customer-service app.",
    )

    app.include_router(candidates_router)
    app.include_router(diagnostics_router)
    app.include_router(drafts_router)
    app.include_router(generator_router)
    app.include_router(knowledge_router)
    app.include_router(learning_router)
    app.include_router(rag_router)
    app.include_router(system_router)
    app.include_router(uploads_router)
    app.include_router(versions_router)

    if STATIC_ROOT.exists():
        app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "app": "wechat_ai_customer_service_admin",
            "version": "0.1.0",
            "app_root": str(APP_ROOT),
        }

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_ROOT / "index.html")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("apps.wechat_ai_customer_service.admin_backend.app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
