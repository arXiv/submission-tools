"""This module implements QA checks for general files."""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("[preflight/checks]")


class CheckSeverity(str, Enum):
    """Severity level for check results."""

    error = "error"
    warning = "warning"


@dataclass
class CheckResult:
    check_passed: bool
    info: str
    long_info: str
    severity: CheckSeverity = CheckSeverity.error
    metadata: dict | None = None  # For additional structured data
