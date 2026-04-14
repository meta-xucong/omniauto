"""模板注册表：维护 task_type -> 模板路径映射."""

from pathlib import Path
from typing import Dict, Optional


DEFAULT_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


class TemplateRegistry:
    """管理内置和自定义 workflow/report 模板."""

    def __init__(self, template_dir: Optional[Path] = None) -> None:
        self.template_dir = template_dir or DEFAULT_TEMPLATE_DIR
        self._workflows: Dict[str, Path] = {}
        self._reports: Dict[str, Path] = {}
        self._discover()

    def _discover(self) -> None:
        """自动扫描 templates/workflows 和 templates/reports 目录."""
        wf_dir = self.template_dir / "workflows"
        if wf_dir.exists():
            for f in wf_dir.glob("*.j2"):
                key = f.stem.replace(".py", "")
                self._workflows[key] = f

        rp_dir = self.template_dir / "reports"
        if rp_dir.exists():
            for f in rp_dir.glob("*.j2"):
                key = f.stem.replace(".html", "")
                self._reports[key] = f

    def list_workflows(self) -> Dict[str, Path]:
        """返回已注册 workflow 模板列表."""
        return self._workflows.copy()

    def list_reports(self) -> Dict[str, Path]:
        """返回已注册 report 模板列表."""
        return self._reports.copy()

    def get_workflow(self, task_type: str) -> Optional[Path]:
        """获取指定 workflow 模板路径."""
        return self._workflows.get(task_type)

    def get_report(self, report_type: str) -> Optional[Path]:
        """获取指定 report 模板路径."""
        return self._reports.get(report_type)

    def register_workflow(self, task_type: str, path: Path) -> None:
        """手动注册 workflow 模板."""
        self._workflows[task_type] = path

    def register_report(self, report_type: str, path: Path) -> None:
        """手动注册 report 模板."""
        self._reports[report_type] = path
