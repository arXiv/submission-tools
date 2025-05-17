import sys

import click
from ruamel.yaml import YAML
from src.pdf_profile import PdfProfile


@click.command()
@click.argument("pdf_paths", nargs=-1, type=click.Path(exists=True))
def main(pdf_paths):
    """Profiles PDF files, extracting the text length and counting pages as a proxy for images."""
    profiles = [{"name": pdf_path, "profile": PdfProfile().profile_pdf(pdf_path)} for pdf_path in pdf_paths]
    yaml = YAML()
    if profiles:
        yaml.dump(profiles, sys.stdout)


if __name__ == "__main__":
    main()
