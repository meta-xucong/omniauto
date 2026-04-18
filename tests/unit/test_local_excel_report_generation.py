from pathlib import Path

from omniauto.agent_runtime import OmniAutoAgent
from omniauto.high_level.task_planner import TaskPlanner
from omniauto.orchestration.generator import ScriptGenerator


TASK_DESCRIPTION = (
    r"读取 D:\AI\AI_RPA\data\reports\1688_single_rocking_chair_5\report_data.json，"
    r"用WPS表格整理成一个直观、方便观看的Excel报表，"
    r"并保存到 D:\AI\AI_RPA\data\reports\1688_single_rocking_chair_5\1688_单人摇椅_价格排序表_skill_rpa.xlsx。"
)


def test_task_planner_detects_local_excel_report_task() -> None:
    planner = TaskPlanner()
    steps = planner.plan(TASK_DESCRIPTION)

    assert steps[0]["type"] == "load_json_report"
    assert steps[0]["path"].endswith("report_data.json")
    assert steps[1]["type"] == "build_excel_report"
    assert steps[1]["output_path"].endswith("1688_单人摇椅_价格排序表_skill_rpa.xlsx")


def test_script_generator_emits_local_excel_report_workflow(tmp_path: Path) -> None:
    generator = ScriptGenerator()
    output_path = tmp_path / "local_excel_report.py"

    path = generator.generate(TASK_DESCRIPTION, str(output_path))
    code = Path(path).read_text(encoding="utf-8")

    assert "requires_browser = False" in code
    assert "AtomicStep(" in code
    assert "openpyxl" in code
    assert "build_excel_report" in code


def test_agent_runtime_classifies_local_excel_report_as_task() -> None:
    agent = OmniAutoAgent()
    assert agent._classify_intent(TASK_DESCRIPTION) == "task"
