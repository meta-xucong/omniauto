"""静态代码检查器.

基于 AST 分析 + 正则扫描，禁止危险操作符.
"""

import ast
import re
from pathlib import Path
from typing import List


class ScriptValidator:
    """原子脚本安全校验器."""

    FORBIDDEN_CALLS = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "os.system",
        "subprocess.run",
        "subprocess.call",
        "subprocess.Popen",
    }

    def __init__(self) -> None:
        self.issues: List[str] = []

    def validate(self, script_path: str) -> bool:
        """校验脚本文件.

        Args:
            script_path: 脚本文件路径.

        Returns:
            是否通过校验.
        """
        self.issues = []
        code = Path(script_path).read_text(encoding="utf-8")

        # 1. AST 遍历检查危险调用
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            self.issues.append(f"语法错误: {exc}")
            return False

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = self._get_call_name(node.func)
                if func_name in self.FORBIDDEN_CALLS:
                    self.issues.append(f"禁止调用危险函数: {func_name} (行 {node.lineno})")

        # 2. 正则检查硬编码敏感信息（简单启发式）
        if re.search(r'password\s*=\s*["\'][^"\']+["\']', code, re.IGNORECASE):
            self.issues.append("检测到疑似硬编码密码，请使用凭据管理器")
        if re.search(r'api_key\s*=\s*["\'][^"\']+["\']', code, re.IGNORECASE):
            self.issues.append("检测到疑似硬编码 API Key，请使用凭据管理器")

        return len(self.issues) == 0

    def _get_call_name(self, node: ast.AST) -> str:
        """从 AST 节点中提取调用名称."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return self._get_call_name(node.value) + "." + node.attr
        return ""

    def report(self) -> str:
        """返回校验报告."""
        if not self.issues:
            return "✅ 脚本校验通过，未检测到明显风险。"
        return "\n".join(f"❌ {issue}" for issue in self.issues)
