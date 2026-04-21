# Auto-generated verification workflow
# Task: Verify automatic knowledge growth closeout

from omniauto.core.state_machine import Workflow, AtomicStep
from omniauto.knowledge import record_knowledge_observation

requires_browser = False


def emit_probe_observations(context):
    record_knowledge_observation(
        context,
        kind="pattern",
        title="Knowledge growth probe pattern",
        summary="Controlled workflows can emit structured knowledge observations during execution and let closeout persist them automatically.",
        domain="general",
        stage="emerging",
        maturity="medium",
        tags=["knowledge", "probe", "automation"],
    )
    record_knowledge_observation(
        context,
        kind="lesson",
        title="Knowledge growth probe lesson",
        summary="If a task already knows a reusable conclusion during execution, it should emit a structured observation instead of relying on a post-hoc human reminder.",
        domain="general",
        trigger="verification_probe",
        tags=["knowledge", "probe", "lesson"],
    )
    record_knowledge_observation(
        context,
        kind="capability",
        title="Automatic knowledge closeout",
        summary="The platform can close out controlled workflows into the knowledge layer without promoting them into skills or platform code.",
        domain="general",
        stage="observed",
        maturity="emerging",
        boundaries="Applies to controlled workflow entrypoints; legacy ad-hoc scripts still need manual closeout.",
        tags=["knowledge", "capability", "probe"],
    )
    return {"probe": "ok"}


workflow = Workflow(task_id="knowledge_growth_probe")
workflow.add_step(
    AtomicStep(
        "knowledge_growth_probe",
        emit_probe_observations,
        lambda result: result.get("probe") == "ok",
        retry=1,
        description="emit structured knowledge observations",
    )
)
