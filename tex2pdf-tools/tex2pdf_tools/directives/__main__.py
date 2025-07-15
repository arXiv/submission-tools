"""Command line interface to DirectiveManager."""

import argparse
import json
import os.path
import sys
from ..zerozeroreadme import ZeroZeroReadMe, ZZRMKeyError, ZZRMMultipleFilesError
from . import DirectiveManager

import logging

DEFAULT_BASE = "/data/new"
DEFAULT_PREFLIGHT_NAME = "gcp_preflight.json"

def main():
    """Provide the main cli entry point."""
    # Set up logging
    stream_handler = None
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(logging.WARNING)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    # Accumulate all output in result
    result ={}

    # Set up argument parser
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
    parser.add_argument("-M", "--migrate", action="store_true", help="Migrate 00README to new format, "
                                                                     "and delete source format.")

    parser.add_argument("-o", "--output_file", type=str, help="Path to directives results output (JSON).")
    parser.add_argument(
        "-p", "--preflight", action="store_true", help="Process the PreFlight data and return summary (JSON)."
    )
    parser.add_argument("-P", "--preflight_file", type=str, help="Path to PreFlight result.")
    parser.add_argument("-r", "--root_dir", type=str, required=False, help="Root directory for directives.")
    parser.add_argument("-s", "--set_active", type=str,
                        help="Set the specified file as the active directives file.")
    parser.add_argument(
        "-S", "--src_dir", type=str, required=False, help="Src directory for directives and document files."
    )
    parser.add_argument("-T", "--tree", action="store_true", help="Print document tree as "
                                                                  "represented in preflight report.")
    parser.add_argument("-u", "--upgrade_file", type=str,
                        help="Upgrade the specified v1 directives file to v2.")
    parser.add_argument("-U", "--upgrade_or_update", action="store_true",
                        help="Upgrade to JSON or update the latest directives.")

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
    try:
        generate_directives = False

        if args.base and args.base is not DEFAULT_BASE and args.root_dir:
            raise ValueError("Arguments --base_dir and --root_dir cannot be used together.")

        if args.root_dir and not os.path.exists(args.root_dir):
            raise ValueError(
                f"Arguments root directory does not exist {args.root_dir}"
            )

        if not args.root_dir and args.base and not os.path.exists(args.base)\
                and not (args.preflight_file and args.src_dir):
            # Allow override when both preflight file and src directory are specified.
            raise ValueError(
                f"Arguments base directory does not exist {args.base}: Use --root_dir or both --base and --identifier."
            )

        if not args.root_dir and args.base and not args.identifier:
            raise ValueError("Arguments --base_dir and --identifier must be used together.")

        if args.root_dir:
            root_dir = args.root_dir
        elif args.base:
            root_dir = os.path.join(args.base, args.identifier[:4], args.identifier)

        log_path = os.path.join(root_dir, "directives.log")
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG if args.debug else logging.WARNING)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        # Get rid of default handler
        if stream_handler:
            logger.removeHandler(stream_handler)

        logger.debug(f"Parsed arguments: {args}")

        # Create DirectiveManager with specified root directory
        manager = None

        manager = DirectiveManager(root_dir, args.src_dir, args.migrate, args.debug)

        # Quick checks - return response immediately
        if args.v1_exists:
            result["v1_file"] = manager.v1_exists()
            print(json.dumps(result, indent=2))
            sys.exit(0)
        if args.v2_exists:
            result["v2_file"] = manager.v2_exists()
            print(json.dumps(result, indent=2))
            sys.exit(0)
        if args.active_file:
            result["active_file"] = manager.get_active_directives_file()
            print(json.dumps(result, indent=2))
            sys.exit(0)
        if args.list_files or args.details:
            files = manager.list_directives_files()
            if args.details:
                result["files"] = [{"file": f, "version": "v1" if manager.is_v1_file(f) else "v2"} for f in files]
            else:
                result["files"] = files
            print(json.dumps(result, indent=2))
            sys.exit(0)

        if args.upgrade_file:
            if manager.is_v1_file(args.upgrade_file):
                manager.upgrade_directives_file(args.upgrade_file, args.format, args.force, args.migrate)
                result["upgrade"] = f"Upgraded {args.upgrade_file} to {args.format or 'json'}"
            else:
                result["error"] = f"{args.upgrade_file} is not a valid v1 directives file."

        if args.upgrade_or_update:
            manager.upgrade_or_update(args.force, args.migrate)
            result["upgrade_or_update"] = "Success"


        if args.create_file:
            created_file = manager.create_directives_file(args.create_file, format=args.format,
                                                                  force=args.force)
            result["created"] = created_file

        preflight_path = ""
        if args.preflight_file:
            preflight_path = args.preflight_file
            if not os.path.exists(args.preflight_file):
                possible_preflight_path = os.path.join(root_dir, preflight_path)
                if os.path.exists(possible_preflight_path):
                    preflight_path = possible_preflight_path
                else:
                    result["error"] = f"Invalid path to preflight report: {args.preflight_file}"
                    print(json.dumps(result, indent=2))
                    sys.exit(0)
        elif args.preflight: # no path
            # look in root directory for preflight report
            default_preflight_path = os.path.join(root_dir, DEFAULT_PREFLIGHT_NAME)
            if os.path.exists(default_preflight_path):
                preflight_path = default_preflight_path
            else:
                result["error"] = "No preflight report found. Use -P optione to specify <path>"
                print(json.dumps(result, indent=2))
                sys.exit(0)

        if args.preflight and preflight_path:
            preflight_data = manager.load_preflight_data(preflight_path)
            if args.tree:
                result["document_tree"] = preflight_data.get("document_tree", {})
            else:
                result["preflight"] = preflight_data

            print(json.dumps(result, indent=2))
            sys.exit(0)

        if args.set_active:
            if manager.is_v1_file(args.set_active) or manager.is_v2_file(args.set_active):
                if manager.make_active_directives_file(args.set_active):
                    result["set_active"] = args.set_active
                else:
                    result["error"] = f"Failed to set {args.set_active} as active."
            else:
                result["error"] = f"{args.set_active} is not a recognized directives file."

        if args.write_file:
            result["can_write"] = manager.can_make_active(args.write_file)

        # re/generate the directives file (not required on all requests)
        if not result or generate_directives:

            # Collect and digest information we need from 00README
            directives = {}
            #    node = {
            #        "ignore": []
            #    }

            #    ignore_list = manager.readme_list_ignore()
            #    for ignore in ignore_list:
            #        node['ignore'].append({'filename': ignore})
            serial = None
            try:
                serial = manager.process_directives()
            except ZZRMMultipleFilesError as e:
                active_file = manager.get_active_directives_file()
                active_directives_path = os.path.join(manager.src_dir, active_file)
                print(f"WARNING: Setting directives path to {active_directives_path}.")
                manager = DirectiveManager(active_directives_path, args.src_dir, args.migrate, args.debug)
                serial = manager.process_directives()
                #print(f"Error: process(): {e}")
            except ValueError as e:
                result["error"] = f"Error: process(): {e}"

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

            if args.verbose:
                sources = []
                if "directives" in directives:
                    sources = directives["directives"].get("sources", [])

                if sources:
                    print("Sources:")
                    print(json.dumps(sources, indent=2))
                else:
                    print("There are no sources available\n")

    except ZZRMMultipleFilesError as e:
        emsg = f"Detected multiple 00README files: {e}."
        logger.exception(emsg)
        result["error"] = emsg
    except ZZRMKeyError as e:
        emsg = f"00README syntax error: key error: {e}."
        logger.exception(emsg)
        result["error"] = emsg
    except ValueError as e:
        emsg = f"ValueError exception occurred: {e}"
        logger.exception(emsg)
        result["error"] = emsg
    #except Exception as e:
    #    emsg = f"Unhandled exception occurred: {e}"
    #    logger.exception(emsg)
    #    result["error"] = emsg

    # Final output
    print("FINAL OUTPUT")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
