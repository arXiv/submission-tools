"""Command line interface to Preflight."""

import argparse
import json

from . import PreflightParser


def main():
    """Provide the main cli entry point."""
    parser = argparse.ArgumentParser(description="Parse a preflight JSON file.")
    parser.add_argument("preflight_file", type=str, help="Path to the preflight JSON file")
    parser.add_argument(
        "-a", "--include_all_files", action="store_true", help="Include used_other_files and used_bib_files"
    )
    parser.add_argument("-d", "--details", action="store_true", help="Show detailed issues information in the summary.")
    parser.add_argument("-j", "--json_output", action="store_true", help="Generate hierarchical JSON output")
    parser.add_argument("-s", "--summary", action="store_true", help="Generate brief summary of preflight information.")
    parser.add_argument("-t", "--top_level_files", type=str, nargs="+", help="List of top-level files")
    args = parser.parse_args()

    details = args.details
    include_all_files = args.include_all_files
    json_output = args.json_output
    preflight_file = args.preflight_file
    top_level_files = args.top_level_files if args.top_level_files else []

    summary = args.summary

    parser = PreflightParser(preflight_file)

    if summary:
        summary_data = {"Top Level Files": parser.list_top_level_files(), "TeX Files": parser.list_tex_files()}

        if details:
            # Include detailed issues
            summary_data["Top Level File Issues"] = parser.get_top_level_file_issues()
            summary_data["TeX File Issues"] = parser.get_tex_file_issues()
        else:
            # Only include the number of issues
            summary_data["Top Level File Issues"] = {
                filename: len(issues) for filename, issues in parser.get_top_level_file_issues().items()
            }
            summary_data["TeX File Issues"] = {
                filename: len(issues) for filename, issues in parser.get_tex_file_issues().items()
            }

        if top_level_files:
            if include_all_files:
                summary_data["Files Used by Specified Top Level Files"] = parser.tex_files_used_recursive(
                    top_level_files, include_all_files
                )
            else:
                summary_data["TeX Files Used by Specified Top Level Files"] = parser.tex_files_used_recursive(
                    top_level_files, include_all_files
                )

        if json_output:
            print(json.dumps(summary_data, indent=2))
        else:
            # Print summary in plain text
            print("Top Level Files:")
            print(summary_data["Top Level Files"])
            print("\nTop Level File Issues:")
            for filename, issues in summary_data["Top Level File Issues"].items():
                if details:
                    print(f"{filename}:")
                    for issue in issues:
                        print(f"  - {issue}")
                else:
                    print(f"{filename}: {issues} issues")
            print("\nTeX Files:")
            print(summary_data["TeX Files"])
            print("\nTeX File Issues:")
            for filename, issues in summary_data["TeX File Issues"].items():
                if details:
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
        hierarchy = parser.build_hierarchy(
            specified_top_level_files=top_level_files, include_all_files=include_all_files
        )
        print(json.dumps(hierarchy, indent=2))


if __name__ == "__main__":
    main()
