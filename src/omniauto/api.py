"""OmniAuto FastAPI REST API.

为 Telegram Bot、微信 Bot 以及非 MCP 环境提供 HTTP 接口.
"""

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .service import OmniAutoService

app = FastAPI(title="OmniAuto API", version="0.1.0")
service = OmniAutoService()


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


# ----------------------------------------------------------------------
# Request/Response Models
# ----------------------------------------------------------------------
class PlanRequest(BaseModel):
    description: str


class GenerateRequest(BaseModel):
    description: str
    output_path: str


class ValidateRequest(BaseModel):
    script_path: str


class RunRequest(BaseModel):
    script_path: str
    headless: bool = True
    task_id: Optional[str] = None


class ScreenshotRequest(BaseModel):
    engine: str = "browser"


class ScheduleRequest(BaseModel):
    script_path: str
    task_name: str
    cron_expr: str
    headless: bool = True


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------
@app.post("/plan")
def plan(req: PlanRequest):
    return service.plan_task(req.description)


@app.post("/generate")
def generate(req: GenerateRequest):
    return service.generate_script(req.description, req.output_path)


@app.post("/validate")
def validate(req: ValidateRequest):
    return service.validate_script(req.script_path)


@app.post("/run")
async def run(req: RunRequest):
    try:
        result = await service.run_workflow(
            script_path=req.script_path,
            headless=req.headless,
            task_id=req.task_id,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/screenshot")
async def screenshot(req: ScreenshotRequest):
    return await service.get_screenshot(req.engine)


@app.get("/task/{task_id}")
def task_status(task_id: str):
    return service.get_task_status(task_id)


@app.get("/queue")
def queue():
    return service.get_queue()


@app.post("/schedule")
def schedule(req: ScheduleRequest):
    try:
        return service.schedule_task(
            req.script_path, req.task_name, req.cron_expr, req.headless
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/schedules")
def list_schedules():
    return service.list_scheduled_tasks()


@app.get("/steps")
def steps():
    return service.list_available_steps()


@app.get("/health")
def health():
    return {"status": "ok"}
