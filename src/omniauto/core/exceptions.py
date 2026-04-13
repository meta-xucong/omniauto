"""OmniAuto 自定义异常类."""


class OmniAutoError(Exception):
    """OmniAuto 基础异常."""

    pass


class ValidationError(OmniAutoError):
    """原子步骤结果校验失败时抛出."""

    pass


class GuardianBlockedError(OmniAutoError):
    """人工审核节点阻止继续执行时抛出."""

    pass


class EngineNotAvailableError(OmniAutoError):
    """引擎不可用或未正确初始化时抛出."""

    pass
