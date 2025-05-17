import os
import re
import subprocess

import click
from ruamel.yaml import YAML
from src.pdf_profile import PdfProfile


@click.group()
def cli():
    pass


def list_outcome_yymms(yymms: list[str], bucket: str):
    postfix = ".outcome.tar.gz"
    result = []
    for yymm in yymms:
        prefix = f"gs://{bucket}/ps_cache/arxiv/pdf/{yymm}/"
        ls_outcome = subprocess.Popen(
            ["gsutil", "ls", prefix + "*" + postfix], encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        out, err = ls_outcome.communicate()
        result.extend([entry.strip()[len(prefix) : -len(postfix)] for entry in out.splitlines()])
    return result


vers_line = re.compile("^\s*([0-9]+)\s+([\d\-T:]+Z)\s+(gs://.+#\d+)\s+metageneration=([\d\-T:])")


def list_blob_versions(blob_path: str):
    ls_outcome = subprocess.Popen(
        ["gsutil", "ls", "-al", blob_path], encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    out, err = ls_outcome.communicate()
    result = []
    for entry in out.splitlines():
        blob_variant = entry.strip()
        matched = vers_line.search(blob_variant)
        if matched:
            result.append((matched.group(3), matched.group(4)))
    return result


@cli.command()
@click.argument("yymm", nargs=-1, type=click.STRING)
@click.option("--bucket", type=click.STRING, default="arxiv-production-data")
def list_outcome(yymm, bucket) -> None:
    yymms = [yymm] if isinstance(yymm, str) else yymm
    click.echo("\n".join(list_outcome_yymms(yymms, bucket)))


@cli.command()
@click.argument("xid", nargs=-1, type=click.STRING)
@click.option("--bucket", type=click.STRING, default="arxiv-production-data")
@click.option("--profile", type=click.BOOL, default=True)
def download_pdf_variants(xid, bucket, profile) -> None:
    xids = [xid] if isinstance(xid, str) else xid
    for xid in xids:
        yymm = xid[0:4]
        prefix = f"gs://{bucket}/ps_cache/arxiv/pdf/{yymm}/"
        postfix = ".pdf"
        blob_path = prefix + xid + postfix
        paths = list_blob_versions(blob_path)
        for pdf_path, vers in paths:
            dest_dir = os.path.join(".", xid[0:4], xid)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, f"{xid}.{vers}.pdf")
            subprocess.run(["gsutil", "cp", pdf_path, dest], encoding="utf-8", check=False)
            if profile:
                profiled = PdfProfile().profile_pdf(dest)
                prof_path = dest + ".profile"
                with open(prof_path, "w", encoding="utf-8") as prof_fd:
                    yaml = YAML()
                    yaml.dump(profiled, prof_fd)


@cli.command()
@click.argument("xid", nargs=-1, type=click.STRING)
@click.option("--bucket", type=click.STRING, default="arxiv-production-data")
def list_pdf_variants(xid, bucket) -> None:
    xids = [xid] if isinstance(xid, str) else xid
    for xid in xids:
        yymm = xid[0:4]
        prefix = f"gs://{bucket}/ps_cache/arxiv/pdf/{yymm}/"
        postfix = ".pdf"
        os.makedirs(xid, exist_ok=True)
        blob_path = prefix + xid + postfix
        paths = list_blob_versions(blob_path)
        print("\n".join([ppath[0] for ppath in paths]))


if __name__ == "__main__":
    cli()
