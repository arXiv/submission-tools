"""
FastAPI utilities
"""

from io import BufferedIOBase
from typing import BinaryIO, TextIO

from fastapi import BackgroundTasks

from tex2pdf.service_logger import get_logger


def close_stream(it: BufferedIOBase | BinaryIO | TextIO, filename: str, extra: dict) -> None:
    """Close the stream."""
    it.close()
    get_logger().debug("closed stream for %s", filename, extra=extra)
    pass


def closer(it: BufferedIOBase | BinaryIO | TextIO, filename: str, extra: dict) -> BackgroundTasks:
    """Create a background task to close the stream."""
    tasks = BackgroundTasks()
    tasks.add_task(close_stream, it, filename, extra)
    return tasks
