"""
compile_submissions.

Given submissions directory, sends them to tex2pdf API, gets the outcome back and
writes it out to "outcomes" subdirectory of give submissions directory.

eg:
python3 compile_submissions.py compile ~/tarballs

When the outcome exists, the submission compilation skips the tarball.

The default endpoint is `http://localhost:6301/convert/`.

"harvest" command opens up the outcome and stores outcome in a sqlite3 database named "score.db"

python3 compile_submissions.py harvest --purge-fails=true ~/tarballs

which in turn creates or updates "score.db".

For example,
sqlite3 score.db 'select outcome from score where not success' > bad.txt

gives you the all of outcome json files to single file once you run the harvest.
"""

import hashlib
import json
import logging
import os
import sqlite3
import tarfile
import threading
from multiprocessing.pool import ThreadPool
from sqlite3 import Connection
from typing import IO

import click
import pikepdf
from tex2pdf.remote_call import service_process_tarball
from tqdm import tqdm

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s: %(message)s")

thread_local = threading.local()


def score_db(score_path: str) -> Connection:
    """Open scorecard database."""
    db = sqlite3.connect(score_path)
    db.execute(
        "create table if not exists score (source varchar primary key, outcome TEXT, "
        "arxivfiles TEXT, clsfiles TEXT, styfiles TEXT, pdf varchar, pdfchecksum TEXT, "
        "nrpages int, removed_unused_files TEXT, status int, success bool)"
    )
    db.execute("create table if not exists touched (filename varchar primary key)")
    return db


@click.group()
def cli() -> None:
    pass


def tarball_to_outcome_path(tarball: str) -> str:
    """Map tarball to outcome file path."""
    parent_dir, filename = os.path.split(tarball)
    stem = filename[:-7]
    return os.path.join(parent_dir, "outcomes", "outcome-" + stem + ".tar.gz")


def get_outcome_meta_and_files_info(outcome_file: str) -> tuple[dict, list[str], list[str], list[str], str, int]:
    """Open a compressed outcome tar archive and get the metadata."""
    meta = {}
    files = set()
    clsfiles = set()
    styfiles = set()
    with tarfile.open(outcome_file, "r:gz") as outcome:
        for name in outcome.getnames():
            if name.startswith("outcome-") and name.endswith(".json"):
                meta_contents = outcome.extractfile(name)
                if meta_contents:
                    meta.update(json.load(meta_contents))
            if name.endswith(".fls"):
                files_fd = outcome.extractfile(name)
                for files_line in files_fd.readlines():
                    filename = files_line.decode("utf-8").strip()
                    if (
                        filename.startswith("INPUT /usr/local/texlive/2023/texmf-arxiv")
                        or filename.startswith("INPUT /usr/local/texlive/2024/texmf-arxiv")
                        or filename.startswith("INPUT /usr/local/texlive/2023/texmf-local")
                        or filename.startswith("INPUT /usr/local/texlive/2024/texmf-local")
                    ):
                        files.add(
                            filename.split()[1]
                            .removeprefix("/usr/local/texlive/2023/")
                            .removeprefix("/usr/local/texlive/2024/")
                        )
                    # only collect class and style files from the texlive tree, not files included in the submission
                    elif filename.startswith("INPUT /usr/local/texlive/") and filename.endswith(".cls"):
                        clsfiles.add(
                            filename.split()[1]
                            .removeprefix("/usr/local/texlive/2023/")
                            .removeprefix("/usr/local/texlive/2024/")
                        )
                    elif filename.startswith("INPUT /usr/local/texlive/") and filename.endswith(".sty"):
                        styfiles.add(
                            filename.split()[1]
                            .removeprefix("/usr/local/texlive/2023/")
                            .removeprefix("/usr/local/texlive/2024/")
                        )
        arxiv_id = meta.get("arxiv_id")
        pdfchecksum = hashlib.sha256()
        nr_pages = 0
        for name in outcome.getnames():
            if name == f"out/{arxiv_id}.pdf":
                pdffile: IO[bytes] = outcome.extractfile(name)
                pdfchecksum.update(pdffile.read())
                pdf = pikepdf.open(pdffile)
                nr_pages = len(pdf.pages)
        # this is the checksum of the empty hash
        pdfchecksum_digest = pdfchecksum.hexdigest()
        if pdfchecksum_digest == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855":
            pdfchecksum_digest = ""

    return meta, list(files), list(clsfiles), list(styfiles), pdfchecksum_digest, nr_pages


@cli.command()
@click.argument("submissions", nargs=1)
@click.option("--service", default="http://localhost:6301/convert/")
@click.option("--score", default="score.db", help="Score card db path")
@click.option("--tex2pdf-timeout", default=100, help="timeout passed to tex2pdf")
@click.option("--post-timeout", default=600, help="timeout for the complete post")
@click.option("--threads", default=64, help="Number of threads requested for threadpool")
@click.option("--auto-detect", is_flag=True, help="Auto detect ZZRM")
@click.option("--auto-detect-delete", is_flag=True, help="Auto delete unused files")
def compile(
    submissions: str,
    service: str,
    score: str,
    tex2pdf_timeout: int,
    post_timeout: int,
    threads: int,
    auto_detect: bool,
    auto_detect_delete: bool,
) -> None:
    """Compile submissions in a directory."""

    def local_submit_tarball(tarball: str) -> None:
        outcome_file = tarball_to_outcome_path(tarball)
        try:
            service_process_tarball(
                service,
                tarball,
                outcome_file,
                tex2pdf_timeout,
                post_timeout,
                auto_detect=auto_detect,
                auto_detect_delete=auto_detect_delete,
            )
        except FileExistsError:
            logging.info(f"Not recreating already existing {outcome_file}.")
            pass

    source_dir = os.path.expanduser(submissions)
    tarballs = [
        os.path.join(source_dir, tarball)
        for tarball in os.listdir(source_dir)
        if tarball.endswith(".tar.gz") and not tarball.startswith("outcome-")
    ]
    logging.info("Got %d tarballs", len(tarballs))
    with ThreadPool(processes=int(threads)) as pool:
        pool.map(local_submit_tarball, tarballs)
    logging.info("Finished")


@cli.command("harvest")
@click.argument("submissions", nargs=1)
@click.option("--score", default="score.db", help="Score card db path")
@click.option("--update", default=False, help="Update scores")
@click.option("--purge-failed", default=False, help="Purge failed outcomes")
def register_outcomes(submissions: str, score: str, update: bool, purge_failed: bool) -> None:
    """Register the outcomes to a score card db."""
    submissions = os.path.expanduser(submissions)
    sdb = score_db(score)
    outcomes_dir = os.path.join(submissions, "outcomes")
    if not os.path.exists(outcomes_dir):
        logging.error("No outcomes")
        return

    tarballs = [tgz for tgz in os.listdir(submissions) if tgz.endswith(".tar.gz")]
    logging.info("Got %d tarballs", len(tarballs))
    skipped = 0
    updated = 0
    good = 0
    for tarball in tqdm(tarballs):
        tarball_path = os.path.join(submissions, tarball)
        if not update:
            # If the success is already reported, no need to update
            cursor = sdb.cursor()
            cursor.execute("select success from score where source = ?", (tarball_path,))
            row = cursor.fetchone()
            cursor.close()
            if row is not None:
                success_in_db = row[0]
                if success_in_db and not update:
                    skipped += 1
                    continue

        outcome_file = tarball_to_outcome_path(tarball_path)
        if os.path.exists(outcome_file):
            try:
                meta, files, clsfiles, styfiles, pdfchecksum, nr_pages = get_outcome_meta_and_files_info(outcome_file)
                pdf_file = meta.get("pdf_file")
            except Exception as exc:
                logging.warning("%s: %s - deleting outcome", outcome_file, str(exc))
                os.unlink(outcome_file)
                skipped += 1
                continue
        else:
            skipped += 1
            continue
        success = meta.get("status") == "success"
        removed_unused_files = meta.get("removed_unused_files", [])
        # Upsert the result
        cursor = sdb.cursor()
        cursor.execute("begin")
        cursor.execute(
            "insert into score (source, outcome, arxivfiles, clsfiles, styfiles, pdf,"
            " pdfchecksum, nrpages, removed_unused_files, success)"
            " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " on conflict(source) do update set outcome=excluded.outcome, arxivfiles=excluded.arxivfiles,"
            " clsfiles=excluded.clsfiles, styfiles=excluded.styfiles, pdf=excluded.pdf,"
            " pdfchecksum=excluded.pdfchecksum, nrpages=excluded.nrpages,"
            " removed_unused_files=excluded.removed_unused_files, success=excluded.success",
            (
                tarball_path,
                json.dumps(meta, indent=2),
                json.dumps(files, indent=2),
                json.dumps(clsfiles, indent=2),
                json.dumps(styfiles, indent=2),
                pdf_file,
                pdfchecksum,
                nr_pages,
                ",".join(removed_unused_files),
                success,
            ),
        )
        cursor.executemany("insert or ignore into touched(filename) values (?) ", [(filename,) for filename in files])
        cursor.execute("commit")
        cursor.close()

        updated += 1
        if success:
            good += 1
        elif purge_failed:
            if os.path.exists(outcome_file):
                os.unlink(outcome_file)
    logging.info(
        "Total: %d, skipped: %d, updated: %d, good: %d, bad: %d",
        len(tarballs),
        skipped,
        updated,
        good,
        len(tarballs) - skipped - good,
    )


def find_tex_errors(outcome):
    arxiv_id = outcome.get("arxiv_id")
    for converter in outcome.get("converters", []):
        for run in converter.get("runs", []):
            for tex_log in run.get("log", "").splitlines():
                if tex_log.find("LaTeX Error: File") >= 0:
                    print(f"{arxiv_id}; {tex_log}")


@cli.command("extract-errors")
@click.option("--score", default="score.db", help="Score card db path")
def extract_tex_errors(score):
    sdb = score_db(score)
    cursor = sdb.cursor()
    try:
        cursor.execute("SELECT outcome FROM score")
        for row in cursor.fetchall():
            # Parse the outcome column (assumed to be in JSON format) from the current row
            outcome = json.loads(row[0])
            find_tex_errors(outcome)
    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
    except Exception as e:
        logging.error(f"Exception in _query: {e}")

    finally:
        sdb.close()


if __name__ == "__main__":
    cli()
