"""DirectivesManager main source."""

import json
import os
from typing import ClassVar

import toml
import yaml

from ..preflight import PreflightReport
from ..zerozeroreadme import ZeroZeroReadMe

# Recognized directives file extensions (formats)
DIRECTIVE_EXTS = [".yml", ".yaml", ".json", ".jsn", ".ndjson", ".toml", ".xxx"]


def serialize_data(data: dict, format: str) -> str:
    """
    Serialize data into the specified format.

    Args:
        data (dict): Data to serialize.
        format (str): Desired format, options are 'yaml', 'json', 'toml'.

    Returns:
        str: Serialized string.
    """
    match format:
        case "yaml":
            return yaml.dump(data)
        case "json":
            return json.dumps(data, indent=4)
        case "toml":
            return toml.dumps(data)
        case _:
            raise ValueError("Unsupported format. Use 'yaml', 'json', or 'toml'.")

def write_readme_file(file_path: str, content: str) -> None:
    """
    Write content to a 00README file.

    Args:
        file_path (str): Path where the file will be saved.
        content (str): Content to write into the file.
    """
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)


class DirectiveManager:
    """Class to manage 00README directives."""

    # Supported v2 formats
    SUPPORTED_FORMATS: ClassVar[list[str]] = ["json", "yaml", "toml"]

    def __init__(self, root_dir: str, src_dir: str | None = None):
        self.root_dir = root_dir
        self.src_dir = src_dir if src_dir is not None else f"{self.root_dir}/src"
        self.directives_files = self.list_directives_files()
        self.preflight_module = None
        self.preflight_hierarchy = None
        self.preflight_data_not_found = False
        self.readme_object = None

    def load_preflight_data(self, preflight_file_arg: str | None = None):
        """Load preflight data and returns a hierarchy."""
        # Assuming the preflight module returns a hierarchy when loading data

        preflight_file = preflight_file_arg if preflight_file_arg is not None else f"{self.root_dir}/gcp_preflight.json"

        if not os.path.exists(preflight_file):
            return None

        if self.preflight_module is None:
            # import from preflight  # Importing preflight only when needed
            self.preflight_module = PreflightReport(preflight_file)  # Save preflight module in the object

        try:
            top_level_files = []
            include_all_files = True
            hierarchy = self.preflight_module.build_hierarchy(
                specified_top_level_files=top_level_files, include_all_files=include_all_files
            )
            return hierarchy
        except FileNotFoundError as e:
            self.preflight_data_not_found = True
            raise e
        except ValueError as e:
            raise e

        return hierarchy

    def list_directives_files(self) -> list[str]:
        """
        List all directives files in the root directory.

        This routine is using the filename to determine whether the file
        is a 00README file. The contents are not validated.

        Note: An active or historical 00README.XXX is allowed. We expect to
        find at most one v2 directives file in all newer articles that rely
        on GenPDF for compilation. Listing all directives files allows file
        upload to detect errors. It should not allow more than one v2 file.
        """
        files = sorted(os.listdir(self.src_dir))
        return [filename for filename in files if self.is_directives_file(filename)]

    @staticmethod
    def is_directives_file(filename: str) -> bool:
        """
        Check if a file is a directives file.

        Args:
            filename (str): Filename to check.

        Returns:
            bool: True if the file is a directives file, False otherwise.
        """
        name, ext = os.path.splitext(filename)
        return name.upper() == "00README" and ext.lower() in DIRECTIVE_EXTS

    def get_active_directives_file(self) -> str:
        """
        Get the active 00README file.

        Returns:
            str: The filename of the active directives file. This will return a v1 for existing
            articles and a v2 file for all recent submissions and articles.

        Raises:
            ValueError: If more than one v2 file is found.
        """
        v2_files = [f for f in self.directives_files if self.is_v2_file(f)]
        if len(v2_files) > 1:
            raise ValueError("Only one v2 00README directives file is allowed.")
        elif v2_files:
            return v2_files[0]

        # If no v2 file, return the v1 file if it exists
        v1_files = [f for f in self.directives_files if self.is_v1_file(f)]
        return v1_files[0] if v1_files else None

    @staticmethod
    def is_v2_file(filename: str) -> bool:
        """
        Check if a file is a v2 directives file.

        Args:
            filename (str): Filename to check.

        Returns:
            bool: True if the file is a v2 directives file, False otherwise.
        """
        name, ext = os.path.splitext(filename)
        return name.upper() == "00README" and ext.lower() in [".yaml", ".yml", ".json", ".toml"]

    @staticmethod
    def is_v1_file(filename: str) -> bool:
        """
        Check if a file is a v1 directives file.

        Args:
            filename (str): Filename to check.

        Returns:
            bool: True if the file is a v1 directives file, False otherwise.
        """
        name, ext = os.path.splitext(filename)
        return name.upper() == "00README" and ext.lower() == ".xxx"

    def v1_exists(self) -> bool:
        """
        Check if there is a version 1 00README file.

        Returns:
            bool: True if a v1 file exists, False otherwise.
        """
        return any(self.is_v1_file(f) for f in self.directives_files)

    def v2_exists(self) -> bool:
        """
        Check if there is a version 2 00README file.

        Returns:
            bool: True if a v2 file exists, False otherwise.
        """
        return any(self.is_v2_file(f) for f in self.directives_files)

    def is_active_directives_file(self, filename: str) -> bool:
        """
        Check if a given file is the active directives file.

        Args:
            filename (str): The name of the file to check.

        Returns:
            bool: True if the file is the active directives file, False otherwise.
        """
        return filename == self.get_active_directives_file()

    def can_make_active(self, filename: str) -> bool:
        """Determine if a specified file can be made the active 00README file.

        Args:
            filename (str): The name of the file to check.

        Returns:
            bool: True if the file can be made active, False otherwise.
        """
        name, ext = os.path.splitext(filename)
        if name.upper() != "00README" or ext.lower() not in DIRECTIVE_EXTS:
            return False

        if self.is_active_directives_file(filename):
            return True

        try:
            active_file = self.get_active_directives_file()  # noqa
        except ValueError:
            return False

        if self.is_v1_file(filename):
            return not self.v2_exists()
        elif self.is_v2_file(filename):
            active_v2 = next((f for f in self.directives_files if self.is_v2_file(f)), None)
            return not active_v2 or active_v2 == filename

        return False

    def upgrade_directives_file(self, src_filename: str, dest_format: str = "json", force: bool = False):
        """
        Upgrade from v1 00README.XXX to modern v2+ directives file.

        This operation will normally occur once to migrate v1 directives to
        v2 format.

        Args:
            src_filename (str): The source v1 filename to upgrade.
            dest_format (str): The desired v2 format (default is 'json').

        Raises:
            ValueError: If there is already an existing v2 file in a different format.
        """
        if not force and self.v2_exists() and not self.is_active_directives_file(src_filename):
            raise ValueError("A v2 directives file already exists.")

        # The current routine does not allow you to select the file, it picks it for
        # you. So we can't do V2.formatA -> v2.formatB
        zzrm = ZeroZeroReadMe(self.root_dir)
        data = zzrm.to_dict()

        new_00readme_path = os.path.join(self.root_dir, f"00README.{dest_format}")
        serialized_data = serialize_data(data, dest_format)
        write_readme_file(new_00readme_path, serialized_data)

        print(f"Upgraded to v2 and saved as {new_00readme_path}")

    def process_directives(self, dest_format: str = "json"):
        """Load a ZZRM file and return it as dictionary."""
        zzrm = ZeroZeroReadMe(self.src_dir)
        self.readme_object = zzrm

        data = zzrm.to_dict()
        return data

    def readme_list_ignore(self):
        """Return the list of ignores."""
        if not self.readme_object:
            self.process_directives()
        return self.readme_object.ignores

    def create_directives_file(
        self, basename: str = "00README", elements: dict | None = None, format: str = "json", force: bool = False
    ):
        """
        Create a new directives file with the specified format.

        Args:
            basename (str, optional): Base name of the file to create (without extension). Defaults to "00README".
            elements (dict, optional): Elements to write to the file.
            format (str, optional): Format of the file (json, yaml, toml). Defaults to "json".
            force (bool, optional): Whether to force creation even if it would not be active. Defaults to False.

        Raises:
            ValueError: If trying to create a second v2 directives file without force.
        """
        if format not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format: {format}. Supported formats are {self.SUPPORTED_FORMATS}")

        new_filename = f"{basename}.{format}"
        new_filepath = os.path.join(self.root_dir, new_filename)

        if not self.can_make_active(new_filename) and not force:
            raise ValueError(f"Cannot create {new_filename} as the active directives file.")

        content = serialize_data(elements, format) if elements else ""
        write_readme_file(new_filepath, content)

        print(f"Created directives file {new_filepath}")
