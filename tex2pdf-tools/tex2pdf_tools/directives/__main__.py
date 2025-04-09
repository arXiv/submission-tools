"""Command line interface to DirectiveManager."""

import argparse
import json
import os.path

from . import DirectiveManager

DEFAULT_BASE = "/data/new"


def main():
    """Provide the main cli entry point."""
    # Setting up argument parser
    parser = argparse.ArgumentParser(description="Process directives in the specified root directory.")

    parser.add_argument("-a", "--active_file", action="store_true", help="Display the active directives file.")
    parser.add_argument(
        "-b", "--base", default=DEFAULT_BASE, help="Base directory for submissions directories (default:/data/new)"
    )
    parser.add_argument(
        "-c",
        "--create_file",
        nargs="?",
        const="00README",
        help="Create a new directives file with the specified "
        'format. Defaults to creating "00README" if no basename is provided.',
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Debug setting.")
    parser.add_argument("-D", "--details", action="store_true", help="List all directives files with format.")
    parser.add_argument(
        "-f",
        "--format",
        type=str,
        choices=["json", "yaml", "toml"],
        help="Specify the format when creating a new directives file.",
    )
    parser.add_argument("-F", "--force", action="store_true", help="Force overwrite an existing directives file.")
    parser.add_argument("-i", "--identifier", required=False, help="Identifier for the request")
    parser.add_argument("-l", "--list_files", action="store_true", help="List all directives files.")
    parser.add_argument("--v1_exists", action="store_true", help="Check if a version 1 directives file exists.")
    parser.add_argument("--v2_exists", action="store_true", help="Check if a version 2 directives file exists.")
    parser.add_argument("-o", "--output_file", type=str, help="Path to directives results output (JSON).")
    parser.add_argument(
        "-p", "--preflight", action="store_true", help="Process the PreFlight data and return summary (JSON)."
    )
    parser.add_argument("-P", "--preflight_file", type=str, help="Path to PreFlight result.")
    parser.add_argument("-r", "--root_dir", type=str, required=False, help="Root directory for directives.")
    parser.add_argument("-s", "--set_active", type=str, help="Set the specified file as the active directives file.")
    parser.add_argument(
        "-S", "--src_dir", type=str, required=False, help="Src directory for directives and document files."
    )
    parser.add_argument("-u", "--upgrade_file", type=str, help="Upgrade the specified v1 directives file to v2.")
    parser.add_argument(
        "-w",
        "--write_file",
        type=str,
        help="Check if it is safe to write the specified file as the active 00README file.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose mode.")

    args = parser.parse_args()

    # We must have either a complete root_dir path to submission directory that contains src directory or
    # the base_dir with an identifier so we can create the path dynamically
    if args.debug:
        print(f"root:{args.root_dir} base: {args.base} identifier:{args.identifier}")

    if args.base and args.base is not DEFAULT_BASE and args.root_dir:
        parser.error("Arguments --base_dir and --root_dir cannot be used together.")

    if args.root_dir and not os.path.exists(args.root_dir):
        parser.error(
            f"Arguments root directory does not exist {args.root_dir}"
        )

    if not args.root_dir and args.base and not os.path.exists(args.base)\
            and not (args.preflight_file and args.src_dir):
        # Allow override when both preflight file and src directory are specified.
        parser.error(
            f"Arguments base directory does not exist {args.base}: Use --root_dir or both --base and --identifier."
        )

    if not args.root_dir and args.base and not args.identifier:
        parser.error("Arguments --base_dir and --identifier must be used together.")

    if args.root_dir:
        root_dir = args.root_dir
    elif args.base:
        root_dir = os.path.join(args.base, args.identifier[:4], args.identifier)

    # Create DirectiveManager with specified root directory
    manager = DirectiveManager(root_dir, args.src_dir)

    # Process commands
    if args.active_file:
        try:
            active_file = manager.get_active_directives_file()
            print(json.dumps({"active_directives_file": active_file}))
        except ValueError as e:
            msg = f"{e}"
            print(json.dumps({"error": msg}))

    if args.v1_exists:
        print(json.dumps({"v1_file": manager.v1_exists()}))

    if args.v2_exists:
        try:
            print(json.dumps({"v2_file": manager.v2_exists()}))
        except ValueError as e:
            msg = f"{e}"
            print(json.dumps({"error": msg}))

    if args.list_files or args.details:
        directive_files = manager.list_directives_files()
        if args.verbose:
            print("Directives files:")
        directives_list = []
        for file in directive_files:
            if args.details:
                format = "v2"
                if manager.is_v1_file(file):
                    format = "v1"
                directives_list.append(
                    {
                        "file": file,
                        "version": format,
                        #  "active": manager.is_active_directives_file(file)}
                    }
                )
            else:
                directives_list.append(file)

        print(json.dumps(directives_list, indent=2))

    # In the processing section
    if args.preflight_file:
        if os.path.exists(args.preflight_file):
            hierarchy = manager.load_preflight_data(args.preflight_file)
            print(json.dumps(hierarchy, indent=2))
            exit(0)
        else:
            manager.preflight_data_not_found = True
            print(f"Error: Preflight file '{args.preflight_file}' not found.")
    elif args.preflight:
        print("No preflight file path provided. Use -P <path>")

    # if args.preflight:
    #   if not args.preflight_file:
    #        print("Error: Please specify path to Preflight data.")
    #    manager.process_preflight_data(args.preflight_file)

    if args.upgrade_file:
        if manager.is_v1_file(args.upgrade_file):
            additional_directives = None  # Define as needed for your context  # noqa
            format = args.format
            manager.upgrade_directives_file(args.upgrade_file, format, True)
            print(f"Upgraded {args.upgrade_file} to {format} format.")
        else:
            print(f"{args.upgrade_file} is not a valid v1 directives file.")

    if args.create_file:
        try:
            if args.format:
                created_file = manager.create_directives_file(args.create_file, format=args.format, force=args.force)
                print(
                    f"Created new directives file '{args.create_file}' with format '{args.format}' at '{created_file}'."
                )
            else:
                created_file = manager.create_directives_file(args.create_file, force=args.force)
                print(
                    f"Created new directives file '{args.create_file}' with default format 'json' at '{created_file}'."
                )
        except FileExistsError as e:
            print(f"Error: {e}")
        except ValueError as e:
            print(f"Error: {e}")

    if args.set_active:
        if manager.is_v1_file(args.set_active) or manager.is_v2_file(args.set_active):
            if manager.make_active_directives_file(args.set_active):
                print(f"Set {args.set_active} as the active directives file.")
            else:
                print(f"Failed to set {args.set_active} as the active directives file.")
        else:
            print(f"{args.set_active} is not a recognized directives file.")

    if args.write_file:
        try:
            if manager.can_make_active(args.write_file):
                print(f"It is safe to write {args.write_file} as the active 00README file.")
            else:
                print(f"It is not safe to write {args.write_file} as the active 00README file.")
        except ValueError as e:
            print(f"Error: {e}")

    # Collect and digest information we need from 00README
    directives = {}
    #    node = {
    #        "ignore": []
    #    }

    #    ignore_list = manager.readme_list_ignore()
    #    for ignore in ignore_list:
    #        node['ignore'].append({'filename': ignore})

    serial = manager.process_directives()
    directives["directives"] = serial
    # print(f"Serial:{serial}")
    # exit(0)
    # Default behavior will be to examine the root directory and
    # process the active 00README and the preflight information.
    preflight_data = manager.load_preflight_data(args.preflight_file)
    #    directives['ignore'] = node
    directives["preflight"] = preflight_data

    # Direct output to specified output file, otherwise use standard
    # submission directory (if available) to store
    if args.output_file:
        with open(args.output_file, "w") as outfile:
            json.dump(directives, outfile, indent=2)

    elif args.base and args.identifier:
        base_submission_dir = os.path.join(args.base, args.identifier[:4], args.identifier)
        if os.path.exists(base_submission_dir):
            new_filename = "directives.json"
            new_filepath = os.path.join(base_submission_dir, new_filename)
            with open(new_filepath, "w") as outfile:
                json.dump(directives, outfile, indent=2)
    else:
        print(json.dumps(directives, indent=2))

    if args.debug:
        sources = []
        if "directives" in directives:
            sources = directives["directives"].get("sources", [])

        if sources:
            print("Sources:")
            print(json.dumps(sources, indent=2))
        else:
            print("There are no sources available\n")


if __name__ == "__main__":
    main()
