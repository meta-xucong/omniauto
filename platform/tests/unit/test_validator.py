"""ScriptValidator 单元测试."""

from pathlib import Path

from omniauto.orchestration.validator import ScriptValidator


def test_validator_passes_safe_code(tmp_path):
    code = """
async def run(ctx):
    return StepResult(success=True)
"""
    p = tmp_path / "safe.py"
    p.write_text(code, encoding="utf-8")
    v = ScriptValidator()
    assert v.validate(str(p)) is True
    assert "通过" in v.report()


def test_validator_catches_eval(tmp_path):
    code = """
eval("1+1")
"""
    p = tmp_path / "bad.py"
    p.write_text(code, encoding="utf-8")
    v = ScriptValidator()
    assert v.validate(str(p)) is False
    assert "eval" in v.report()


def test_validator_catches_password(tmp_path):
    code = """
password = "123456"
"""
    p = tmp_path / "pwd.py"
    p.write_text(code, encoding="utf-8")
    v = ScriptValidator()
    assert v.validate(str(p)) is False
    assert "硬编码密码" in v.report()


def test_validator_catches_aliased_subprocess(tmp_path):
    code = """
import subprocess as sp

sp.Popen(["cmd", "/c", "echo test"])
"""
    p = tmp_path / "aliased_subprocess.py"
    p.write_text(code, encoding="utf-8")
    v = ScriptValidator()
    assert v.validate(str(p)) is False
    assert "subprocess.Popen" in v.report()
