"""This module implements QA checks for general files."""

import logging
from dataclasses import dataclass

logger = logging.getLogger("[preflight/checks]")


@dataclass
class CheckResult:
    check_passed: bool
    info: str
    long_info: str
