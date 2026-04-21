"""OmniAuto CLI 入口."""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import click

from .core.state_machine import Workflow, StateStore
from .core.context import TaskContext
from .engines.browser import StealthBrowser
from .orchestration.generator import ScriptGenerator
from .orchestration.validator import ScriptValidator
from .orchestration.guardian import GuardianNode
from .utils.logger import get_logger
from .agent_runtime import OmniAutoAgent
from .service import OmniAutoService

logger = get_logger("omniauto.cli")


@click.group()
@click.version_option(version="0.1.0", prog_name="omni")
def cli() -> None:
    """OmniAuto: 通用AI自动化框架 CLI."""
    pass


@cli.command()
@click.argument("description")
@click.option("--output", "-o", required=True, help="输出脚本文件路径")
def generate(description: str, output: str) -> None:
    """根据自然语言描述生成原子脚本."""
    gen = ScriptGenerator()
    try:
        path = gen.generate(description, output)
        click.echo(f"[OK] 脚本已生成: {path}")
        click.echo(f"提示: 使用 omni validate {path} 检查脚本安全性，然后 omni run --script {path} 执行。")
    except Exception as exc:
        click.echo(f"[ERR] 生成失败: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("script_path")
def validate(script_path: str) -> None:
    """校验脚本安全性."""
    validator = ScriptValidator()
    ok = validator.validate(script_path)
    click.echo(validator.report().replace("✅", "[OK]").replace("❌", "[ERR]"))
    if not ok:
        sys.exit(1)


@cli.command()
@click.option("--script", "-s", required=True, help="要执行的脚本路径")
@click.option("--headless/--no-headless", default=True, help="是否使用无头模式（默认开启）")
@click.option("--task-id", help="指定任务 ID（用于断点续传）")
@click.option("--notify", help="任务完成后发送通知（预留）")
def run(script: str, headless: bool, task_id: str, notify: str) -> None:
    """执行自动化脚本."""
    script_path = Path(script)
    if not script_path.exists():
        click.echo(f"[ERR] 脚本不存在: {script}", err=True)
        sys.exit(1)

    validator = ScriptValidator()
    if not validator.validate(script):
        click.echo(validator.report().replace("✅", "[OK]").replace("❌", "[ERR]"), err=True)
        sys.exit(1)

    asyncio.run(_run_script(str(script_path), headless=headless, task_id=task_id))


@cli.command()
@click.option("--script", "-s", required=True, help="任务脚本路径")
@click.option("--task-id", required=True, help="任务 ID")
@click.option("--state", "final_state", required=True, help="任务最终状态")
@click.option("--description", default="", help="任务说明")
@click.option("--note", default="", help="补充说明")
@click.option("--domain", default="", help="知识领域覆盖值")
def closeout(script: str, task_id: str, final_state: str, description: str, note: str, domain: str) -> None:
    """手动触发一次兜底结项，适合未走受控入口的任务."""

    svc = OmniAutoService()
    summary = svc.closeout_task(
        script,
        task_id=task_id,
        final_state=final_state,
        description=description,
        note=note,
        domain=domain,
    )
    click.echo(f"[OK] 已生成知识结项: {summary.get('task_record', '')}")


@cli.command(name="queue")
@click.option("--show-pending", is_flag=True, help="显示待处理异常队列")
def show_queue(show_pending: bool) -> None:
    """查看异常处理队列."""
    store = StateStore()
    import sqlite3
    conn = sqlite3.connect(store.db_path)
    rows = conn.execute(
        "SELECT task_id, state, current_step, updated_at FROM workflow_state WHERE state IN ('PAUSED', 'ESCALATED', 'FAILED') ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    if not rows:
        click.echo("[OK] 当前没有待处理任务。")
        return
    click.echo(f"{'Task ID':<36} {'State':<12} {'Step':<6} {'Updated At'}")
    click.echo("-" * 80)
    for row in rows:
        click.echo(f"{row[0]:<36} {row[1]:<12} {row[2]:<6} {row[3]}")


@cli.command()
@click.option("--headless", is_flag=True, help="无头模式")
def demo(headless: bool) -> None:
    """运行内置 Demo 工作流（访问 httpbin 并提取标题）."""
    from .steps.navigate import NavigateStep
    from .steps.extract import ExtractTextStep

    async def _demo():
        browser = StealthBrowser(headless=headless)
        await browser.start()
        try:
            ctx = TaskContext(task_id="demo_task", browser_state={"browser": browser})
            wf = Workflow(task_id="demo_task")
            wf.add_step(NavigateStep("https://httpbin.org/html"))
            wf.add_step(ExtractTextStep("h1"))
            state = await wf.run(ctx)
            click.echo(f"[DONE] 工作流结束: {state.name}")
            click.echo(f"[DATA] 提取结果: {ctx.outputs.get('extract_text_h1', '')}")
        finally:
            await browser.close()

    asyncio.run(_demo())


@cli.command()
@click.option("--host", default="127.0.0.1", help="绑定地址")
@click.option("--port", default=8000, help="端口")
def api(host: str, port: int) -> None:
    """启动 FastAPI REST API 服务."""
    import uvicorn
    from .api import app
    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.argument("description")
@click.option("--headless/--no-headless", default=True, help="是否使用无头模式（默认开启）")
def agent(description: str, headless: bool) -> None:
    """通过 Agent Runtime 直接执行自然语言指令."""
    async def _agent():
        omni_agent = OmniAutoAgent(headless=headless)
        result = await omni_agent.process(description)
        click.echo(f"[RESULT] {'成功' if result.success else '失败'}: {result.message}")
        if result.data:
            click.echo("[DATA] 输出数据:")
            for k, v in result.data.items():
                click.echo(f"  {k}: {v}")

    asyncio.run(_agent())


async def _run_script(script_path: str, headless: bool, task_id: Optional[str] = None) -> None:
    """内部：加载并执行脚本."""
    service = OmniAutoService()
    result = await service.run_workflow(
        script_path=script_path,
        headless=headless,
        task_id=task_id,
        entrypoint="cli.run",
    )
    if result.get("final_state") in {"ERROR", "VALIDATION_FAILED"}:
        click.echo(f"[ERR] 执行失败: {result.get('error') or result.get('validation_report', '')}", err=True)
        sys.exit(1)

    click.echo(f"[DONE] 工作流结束，最终状态: {result.get('final_state')}")
    if result.get("outputs"):
        click.echo("[DATA] 输出数据:")
        for k, v in result["outputs"].items():
            click.echo(f"  {k}: {v}")
    knowledge_closeout = result.get("knowledge_closeout", {})
    if knowledge_closeout.get("applied"):
        click.echo(f"[KNOWLEDGE] 已更新: {knowledge_closeout.get('task_record', '')}")


if __name__ == "__main__":
    cli()
