import sys
import typing
from collections import OrderedDict

import dictdiffer

from .props_io import from_dict_to_yaml, from_yaml_to_dict


def _print_value(val, indent):
    if isinstance(val, OrderedDict):
        return "\n".join([_print_value(value, indent + "  ") for key, value in val.items()])
    else:
        return indent + ": " + val


def path_string(path_obj: typing.Any) -> str:
    if isinstance(path_obj, list):
        return "-".join([str(elem) for elem in path_obj])
    return str(path_obj)


class DiffProfiles:
    _profile_files: list[str]
    _profiles: list[OrderedDict]

    def __init__(self, profile_a: str, profile_b: str):
        self._profile_files = [profile_a, profile_b]
        self._profiles = [from_yaml_to_dict(filename) for filename in self._profile_files]
        self.diffs = list(dictdiffer.diff(self._profiles[0], self._profiles[1]))
        pass

    def print_diff(self, file=None):
        if file is None:
            file = sys.stdout
            pass

        if self.diffs:
            print(f"LEFT: {self._profile_files[0]} - RIGHT: {self._profile_files[1]}", file=file)

            adds = [(path, value) for action, path, value in self.diffs if action == "add"]
            removes = [(path, value) for action, path, value in self.diffs if action == "remove"]
            changes = [(path, value) for action, path, value in self.diffs if action == "change"]

            if removes:
                print("\nOnly in LEFT", file=file)
                for path, value in removes:
                    for toplevel, rest in value:
                        if isinstance(rest, str):
                            print(f"{path}.{toplevel}: {rest}", file=file)
                        else:
                            if path:
                                from_dict_to_yaml({path_string(path): {toplevel: rest}}, file)
                            else:
                                from_dict_to_yaml({toplevel: rest}, file)
                                pass
                            pass
                        pass
                    pass

            if adds:
                print("\nOnly in RIGHT", file=file)
                for path, value in adds:
                    for toplevel, rest in value:
                        # print(toplevel, file=file)
                        from_dict_to_yaml({toplevel: rest}, file)
                        pass
                    pass
                pass

            if changes:
                print("\nChanged between LEFT and RIGHT", file=file)
                for path, value in changes:
                    print(f"{path}: {value[0]} --> {value[1]}", file=file)
                    pass
                pass
            pass
        else:
            print("Identical", file=file)
            pass
        pass

    pass
