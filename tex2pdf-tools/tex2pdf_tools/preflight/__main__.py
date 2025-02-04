"""GenPDF preflight parser - command line interface."""

import argparse
import json
import logging
import sys
import typing

from . import PreflightParser, generate_preflight_response

parser = argparse.ArgumentParser(
    description="""
Parse a TeX source directory to JSON, or a JSON to high-level information.

When called with subcommand parse, the dir parameter must point to the
directory with TeX documents to be parsed. In this case, a JSON object
is printed to stdout.

When called with subcommand report, the preflight_file parameter points to
a file containing the JSON object.
"""
)
parser.add_argument(
    "--log",
    type=str,
    default="INFO",
    help="minimal log level (ERROR, INFO, DEBUG)",
)

subparsers = parser.add_subparsers(help="sub-command help", dest="command")

parser_parse = subparsers.add_parser("parse", help="Parse a TeX source directory")
parser_parse.add_argument(
    "dir",
    type=str,
    help="subdirectory containing TeX documents to be parsed",
)

parser_report = subparsers.add_parser("report", help="Generate a report from the parse result")
parser_report.add_argument("preflight_file", type=str, help="Path to the preflight JSON file")
parser_report.add_argument(
    "-a", "--include_all_files", action="store_true", help="Include used_other_files and used_bib_files"
)
parser_report.add_argument(
    "-d", "--details", action="store_true", help="Show detailed issues information in the summary."
)
parser_report.add_argument("-j", "--json_output", action="store_true", help="Generate hierarchical JSON output")
parser_report.add_argument(
    "-s", "--summary", action="store_true", help="Generate brief summary of preflight information."
)
parser_report.add_argument("-t", "--top_level_files", type=str, nargs="+", help="List of top-level files")

args = parser.parse_args()

if args.log:
    loglevel = getattr(logging, args.log.upper(), None)
    logging.basicConfig(level=loglevel)


if args.command == "parse":
    print(generate_preflight_response(args.dir, json=True))
elif args.command == "report":
    top_level_files = args.top_level_files if args.top_level_files else []
    pp = PreflightParser(args.preflight_file)

    if args.summary:
        summary_data: dict[str, typing.Any] = {
            "Top Level Files": pp.list_top_level_files(),
            "TeX Files": pp.list_tex_files(),
        }

        if args.details:
            # Include detailed issues
            summary_data["Top Level File Issues"] = pp.get_top_level_file_issues()
            summary_data["TeX File Issues"] = pp.get_tex_file_issues()
        else:
            # Only include the number of issues
            summary_data["Top Level File Issues"] = {
                filename: len(issues) for filename, issues in pp.get_top_level_file_issues().items()
            }
            summary_data["TeX File Issues"] = {
                filename: len(issues) for filename, issues in pp.get_tex_file_issues().items()
            }

        if top_level_files:
            if args.include_all_files:
                summary_data["Files Used by Specified Top Level Files"] = pp.tex_files_used_recursive(
                    top_level_files, args.include_all_files
                )
            else:
                summary_data["TeX Files Used by Specified Top Level Files"] = pp.tex_files_used_recursive(
                    top_level_files, args.include_all_files
                )

        if args.json_output:
            print(json.dumps(summary_data, indent=2))
        else:
            # Print summary in plain text
            print("Top Level Files:")
            print(summary_data["Top Level Files"])
            print("\nTop Level File Issues:")
            for filename, issues in summary_data["Top Level File Issues"].items():
                if args.details:
                    print(f"{filename}:")
                    for issue in issues:
                        print(f"  - {issue}")
                else:
                    print(f"{filename}: {issues} issues")
            print("\nTeX Files:")
            print(summary_data["TeX Files"])
            print("\nTeX File Issues:")
            for filename, issues in summary_data["TeX File Issues"].items():
                if args.details:
                    print(f"{filename}:")
                    for issue in issues:
                        print(f"  - {issue}")
                else:
                    print(f"{filename}: {issues} issues")
            if "Files Used by Specified Top Level Files" in summary_data:
                print("\nFiles Used by Specified Top Level Files:")
                print(summary_data["Files Used by Specified Top Level Files"])
            elif "TeX Files Used by Specified Top Level Files" in summary_data:
                print("\nTeX Files Used by Specified Top Level Files:")
                print(summary_data["TeX Files Used by Specified Top Level Files"])

    else:
        # Print filters preflight data we need as JSON
        # Always default to including all files used as this will assist with features
        # like the identification of extraneous files.
        hierarchy = pp.build_hierarchy(
            specified_top_level_files=top_level_files, include_all_files=args.include_all_files
        )
        print(json.dumps(hierarchy, indent=2))
else:
    parser.print_help(sys.stderr)
    sys.exit(1)
