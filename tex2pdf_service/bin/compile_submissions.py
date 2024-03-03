import os
import time
import click
import requests
import logging
import sqlite3
from multiprocessing.pool import ThreadPool
import tarfile
import json
import threading

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')

thread_local = threading.local()

def score_db(score_path: str):
    """Open scorecard database"""
    db = sqlite3.connect(score_path)
    db.execute("create table if not exists score (source varcha primary key, outcome varchar, pdf varchar, status int, success bool)")
    return db

@click.group()
def cli():
    pass


def tarball_to_outcome_path(tarball):
    parent_dir, filename = os.path.split(tarball)
    stem = filename[:-7]
    return os.path.join(parent_dir, "outcomes", "outcome-" + stem + ".tar.gz")


@cli.command()
@click.argument('submissions', nargs=1)
@click.option('--service',  default="http://localhost:6301/convert/")
@click.option('--score',  default="score.db", help="Score card db path")
def compile(submissions: str, service: str, score: str):
    """Compile submissions in a directory"""

    def submit_tarball(tarball: str) -> None:
        outcome_file = tarball_to_outcome_path(tarball)
        if os.path.exists(outcome_file):
            return
        os.makedirs(os.path.dirname(outcome_file), exist_ok=True)
        logging.info("File: %s", os.path.basename(tarball))
        meta = {}
        status_code = None

        with open(tarball, "rb") as data_fd:
            uploading = {'incoming': (os.path.basename(tarball), data_fd, 'application/gzip')}
            while True:
                try:
                    res = requests.post(service, files=uploading, timeout=300, allow_redirects=False)
                    status_code = res.status_code
                    if status_code == 504:
                        logging.warning("Got 504 for %s", service)
                        time.sleep(1)
                        continue

                    if status_code == 200:
                        if res.content:
                            with open(outcome_file, "wb") as out:
                                out.write(res.content)
                            with tarfile.open(outcome_file, "r:gz") as tar:
                                meta_file = [name for name in tar.getnames() if name.startswith("outcome-") and name.endswith(".json")]
                                if meta_file:
                                    # Extract the specified file
                                    meta_contents: bytes = tar.extractfile(meta_file[0])
                                    meta = json.load(meta_contents)
                except Exception as exc:
                    logging.warning("%s: %s", service, str(exc))
                break

        success = meta.get("status") == "success"
        logging.log(logging.INFO if success else logging.WARNING,
                    "submit: %s (%s) %s", os.path.basename(tarball), str(status_code), success)

    source_dir = os.path.expanduser(submissions)
    tarballs = [os.path.join(source_dir, tarball) for tarball in os.listdir(source_dir) if tarball.endswith(".tar.gz") and not tarball.startswith("outcome-")]
    logging.info("Got %d tarballs", len(tarballs))
    with ThreadPool(processes=int(16)) as pool:
        pool.map(submit_tarball, tarballs)


@cli.command("harvest")
@click.argument('submissions', nargs=1)
@click.option('--score',  default="score.db", help="Score card db path")
def register_outcomes(submissions: str, score: str) -> None:
    """Register the outcomes to a score card db"""
    submissions = os.path.expanduser(submissions)
    sdb = score_db(score)
    outcomes_dir = os.path.join(submissions, "outcomes")
    if not os.path.exists(outcomes_dir):
        logging.error("No outcomes")
        return

    tarballs = [tgz for tgz in os.listdir(submissions) if tgz.endswith(".tar.gz")]
    logging.info("Got %d tarballs", len(tarballs))
    for tarball in tarballs:
        outcome_file = tarball_to_outcome_path(os.path.join(submissions, tarball))
        meta = {"status": "fail"}
        pdf_file = None
        if os.path.exists(outcome_file):
            try:
                with tarfile.open(outcome_file, "r:gz") as tar:
                    meta_file = [name for name in tar.getnames() if
                                 name.startswith("outcome-") and name.endswith(".json")]
                    if meta_file:
                        # Extract the specified file
                        meta_contents: bytes = tar.extractfile(meta_file[0])
                        meta = json.load(meta_contents)
                    pdf_file = meta.get("pdf_file")
                    if pdf_file:
                        tar_pdf_path = meta["out_directory"] + "/" + pdf_file
                        pdf_contents: bytes = tar.extractfile(tar_pdf_path)

            except Exception as exc:
                logging.warning("%s: %s - deleting outcome", outcome_file, str(exc))
                os.unlink(outcome_file)
        success = meta.get("status") == "success"
        key = os.path.join(submissions, tarball)
        cursor = sdb.cursor()
        cursor.execute("begin")
        cursor.execute("insert into score (source, outcome, pdf, success) values (?, ?, ?, ?) on conflict(source) do update set outcome=excluded.outcome, pdf=excluded.pdf, success=excluded.success", (key, json.dumps(meta, indent=2), pdf_file, success))
        cursor.execute("commit")
        cursor.close()


if __name__ == '__main__':
    cli()
