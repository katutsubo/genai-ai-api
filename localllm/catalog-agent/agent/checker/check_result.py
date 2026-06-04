from typing import Literal

from agent.models import CheckResult


def make_result(
    rule_id: str,
    rule_name: str,
    severity: Literal["error", "warning", "info"],
    passed: bool,
    message: str,
    location: str,
) -> CheckResult:
    return CheckResult(
        rule_id=rule_id,
        rule_name=rule_name,
        severity=severity,
        passed=passed,
        message=message,
        location=location,
    )
