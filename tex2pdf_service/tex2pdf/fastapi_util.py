"""
FastAPI utilities
"""

from typing import BinaryIO, TextIO
from fastapi import BackgroundTasks
from google.cloud.storage.blob import BlobReader
from tex2pdf.service_logger import get_logger


def close_stream(it: BlobReader | BinaryIO | TextIO, filename: str, extra: dict) -> None:
    """Close the stream."""
    it.close()
    get_logger().debug("closed stream for %s", filename, extra=extra)
    pass


def closer(it: BlobReader | BinaryIO | TextIO, filename: str, extra: dict) -> BackgroundTasks:
    """Create a background task to close the stream."""
    tasks = BackgroundTasks()
    tasks.add_task(close_stream, it, filename, extra)
    return tasks
