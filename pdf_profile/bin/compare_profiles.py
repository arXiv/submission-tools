import os
import typing

import click

from src.diff_profiles import DiffProfiles
from src.pdf_profile import PdfProfile, PdfTextSimilarity


@click.group()
def cli():
    pass


@cli.command()
@click.argument('start_dir', nargs=1, type=click.STRING)
def compare_profiles(start_dir):
    root_dir: str
    dirs: typing.List[str]
    files: typing.List[str]
    good = 0
    bad = 0
    for root_dir, dirs, files in os.walk(start_dir):
        pdf1 = [prof for prof in files if prof.endswith('.1.pdf')]
        pdf2 = [prof for prof in files if prof.endswith('.2.pdf')]
        prof1 = [prof for prof in files if prof.endswith('.1.pdf.profile')]
        prof2 = [prof for prof in files if prof.endswith('.2.pdf.profile')]

        if prof1 and prof2:
            print(f"\n{prof1[0]} : {prof2[0]}")
            differ = DiffProfiles(os.path.join(root_dir, prof1[0]),
                                  os.path.join(root_dir, prof2[0]))
            differ.print_diff()
            if differ.diffs:
                bad += 1
                p1, p2 = PdfProfile(), PdfProfile()
                p1.profile_pdf(os.path.join(root_dir, pdf1[0]))
                p2.profile_pdf(os.path.join(root_dir, pdf2[0]))
                sim = PdfTextSimilarity(p1, p2)
                print("Overall similarities %0.3f" % sim.compare_texts())
            else:
                good += 1
    print(f"Summary - Total {good + bad} good: {good} bad: {bad}")


if __name__ == '__main__':
    cli()
