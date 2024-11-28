"""
tex2pdf logger

The primary reason is to have the CustomJsonFormatter to tailor the log output.

This works in conjunction with the logging configuration - logging.conf.
"""

import logging.config
import logging.handlers
import logging

logger_name: str = "tex2pdf"


def get_logger() -> logging.Logger:
    _logger = logging.getLogger(logger_name)
    return _logger
