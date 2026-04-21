"""根据配置生成确定性 Workflow 脚本."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .registry import TemplateRegistry


class TemplateGenerator:
    """基于 Jinja2 模板生成可直接执行的 Workflow 脚本."""

    def __init__(
        self,
        template_dir: Optional[Path] = None,
        output_dir: str = "workflows/generated",
    ) -> None:
        self.registry = TemplateRegistry(template_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._env = Environment(
            loader=FileSystemLoader(str(self.registry.template_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(
        self,
        task_type: str,
        config: Dict[str, Any],
        report_type: Optional[str] = None,
    ) -> Path:
        """生成 workflow 脚本并返回路径.

        Args:
            task_type: workflow 模板类型（如 ecom_product_research）.
            config: 模板渲染配置字典.
            report_type: 可选的 report 模板类型.

        Returns:
            生成的 .py 脚本路径.
        """
        wf_path = self.registry.get_workflow(task_type)
        if wf_path is None:
            raise ValueError(f"未找到 workflow 模板: {task_type}")

        rel_path = wf_path.relative_to(self.registry.template_dir).as_posix()
        template = self._env.get_template(rel_path)

        # 将 report 模板路径也注入配置（如果存在）
        ctx = dict(config)
        if report_type:
            rp_path = self.registry.get_report(report_type)
            if rp_path is None:
                raise ValueError(f"未找到 report 模板: {report_type}")
            ctx["report_template_path"] = str(rp_path.resolve()).replace("\\", "/")

        rendered = template.render(**ctx)

        safe_name = config.get("task_name", task_type).replace(" ", "_").replace("-", "_")
        target_dir = self._resolve_workflow_output_dir(task_type)
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / f"{safe_name}.py"
        out_path.write_text(rendered, encoding="utf-8")
        return out_path

    def generate_report_html(
        self,
        report_type: str,
        data: Dict[str, Any],
    ) -> Path:
        """基于 report 模板生成 HTML 报告.

        Args:
            report_type: report 模板类型.
            data: 模板渲染数据.

        Returns:
            生成的 .html 路径.
        """
        rp_path = self.registry.get_report(report_type)
        if rp_path is None:
            raise ValueError(f"未找到 report 模板: {report_type}")

        rel_path = rp_path.relative_to(self.registry.template_dir).as_posix()
        template = self._env.get_template(rel_path)
        rendered = template.render(**data)

        safe_name = data.get("report_name", report_type).replace(" ", "_").replace("-", "_")
        out_path = self.output_dir / f"{safe_name}.html"
        out_path.write_text(rendered, encoding="utf-8")
        return out_path

    def _resolve_workflow_output_dir(self, task_type: str) -> Path:
        """根据任务类型返回更易理解的生成目录."""
        marketplace_types = {"ecom_product_research"}
        if task_type in marketplace_types:
            return self.output_dir / "marketplaces"
        return self.output_dir / "browser"
