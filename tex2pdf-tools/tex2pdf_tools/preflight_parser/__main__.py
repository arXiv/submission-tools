"""GenPDF preflight parser - command line interface."""

import argparse
import logging

from . import generate_preflight_response

parser = argparse.ArgumentParser()
parser.add_argument(
    "--log",
    type=str,
    default="INFO",
    help="minimal log level (ERROR, INFO, DEBUG)",
)
parser.add_argument(
    "subdir",
    type=str,
    help="subdirectory from where to start the kpse search",
)
args = parser.parse_args()
if args.log:
    loglevel = getattr(logging, args.log.upper(), None)
    logging.basicConfig(level=loglevel)
print(generate_preflight_response(args.subdir, json=True))
