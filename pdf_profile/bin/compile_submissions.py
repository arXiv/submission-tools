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

def score_db(score_path):
    db = sqlite3.connect(score_path)
    db.execute("create table if not exists score (source varcha primary key, outcome varchar, status int, success bool)")
    return db

@click.group()
def cli():
    pass

@cli.command()
@click.argument('submissions', nargs=1)
@click.option('--service',  default="http://localhost:6301/convert/")
@click.option('--score',  default="score.db", help="Score card db path")
def compile(submissions, service, score):

    def submit_tarball(tarball: str):
        sdb = getattr(thread_local, "sdb", None)
        if sdb is None:
            sdb = score_db(score)
            setattr(thread_local, "sdb", sdb)

        logging.info("File: %s", os.path.basename(tarball))
        parent_dir, filename = os.path.split(tarball)
        os.makedirs(os.path.join(parent_dir, "outcomes"), exist_ok=True)
        outcome_file = os.path.join(parent_dir, "outcomes", "outcome-" + os.path.splitext(filename)[0] + ".tar.gz")
        meta = {}
        status_code = None

        with open(tarball, "rb") as data_fd:
            uploading = {'incoming': (filename, data_fd, 'application/gzip')}
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
        sdb.execute("insert into score (source, outcome, status, success) values (?, ?, ?, ?) on conflict(source) do update set outcome=excluded.outcome, status=excluded.status, success=excluded.success", (tarball, json.dumps(meta, indent=2), status_code, success))
        logging.log(logging.INFO if success else logging.WARNING,
                    "submit: %s (%s) %s", os.path.basename(tarball), str(status_code), success)

    source_dir = os.path.expanduser(submissions)
    tarballs = [os.path.join(source_dir, tarball) for tarball in os.listdir(source_dir) if tarball.endswith(".tar.gz") and not tarball.startswith("outcome-")]
    logging.info("Got %d tarballs", len(tarballs))
    with ThreadPool(processes=int(16)) as pool:
        pool.map(submit_tarball, tarballs)


if __name__ == '__main__':
    cli()
