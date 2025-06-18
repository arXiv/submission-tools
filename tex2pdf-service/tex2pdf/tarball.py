"""Handle submission tarballs.

Sets up the tempdir for unpacking the archive file, and unpacks the archive.

"""

import os
import shlex
import stat
import subprocess

from fastapi import UploadFile

from .service_logger import get_logger


class UnsupportedArchive(Exception):
    """Submitted archive file extension is not recognized."""

    pass


class RemovedSubmission(Exception):
    """Submitted archive contains the removed.txt and cannot proceed."""

    pass


class ZZRMUnderspecified(Exception):
    """Submitted archive either misses a 00README file or it is underspecified."""

    pass


class ZZRMUnsupportedCompiler(Exception):
    """Submitted archive contains 00Readme but compiler is not supported."""

    pass


def chmod_775(root_dir: str) -> None:
    """Recursively chmod 775 the directory."""
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        os.chmod(dirpath, 0o0775)
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            current_permissions = stat.S_IMODE(os.lstat(filepath).st_mode)

            # Set the permissions to 0o0775
            new_permissions = current_permissions | 0o0775
            os.chmod(filepath, new_permissions)
            pass
        pass
    pass


def prep_tempdir(tempdir: str) -> tuple[str, str]:
    """Prepare the tempdir for unpacking the archive file."""
    in_dir = os.path.join(tempdir, "in")
    out_dir = os.path.join(tempdir, "out")
    os.mkdir(in_dir, mode=0o0775)
    os.mkdir(out_dir, mode=0o0775)
    # chmod_775(tempdir)
    return in_dir, out_dir


async def save_stream(in_dir: str, incoming: UploadFile, filename: str, _log_extra: dict) -> None:
    """Save the incoming stream to a file. Used for receiving the submission archive file.

    Technically
    """
    local_file = os.path.join(in_dir, filename)
    with open(local_file, "wb") as fd:
        while chunk := await incoming.read(8192):  # Read and write in chunks
            fd.write(chunk)
        pass
    pass


def unpack_tarball(in_dir: str, filename: str, log_extra: dict) -> None:
    """Unpack the submission archive file."""
    if filename.endswith(".tar.gz"):
        args = ["tar", "xzf", filename]
    elif filename.endswith(".tar"):
        args = ["tar", "xf", filename]
    elif filename.endswith(".zip"):
        args = ["unzip", filename, "-d", in_dir]
    else:
        raise UnsupportedArchive(f"Unknown file type: {os.path.basename(filename)}")
    logger = get_logger()
    logger.debug(f"Unpacking: {shlex.join(args)}", extra=log_extra)
    subprocess.call(args, cwd=in_dir)
    logger.debug(f"in_dir: {in_dir}: " + repr(os.listdir(in_dir)), extra=log_extra)
    # os.unlink(filename)
    if "removed.txt" in os.listdir(in_dir):
        raise RemovedSubmission("This archive cannot be processed.")
    pass
