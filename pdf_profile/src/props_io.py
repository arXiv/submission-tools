"""
props i/o.

Read/write pdf properties (dict)
"""

import json
import os.path
import typing
from collections import OrderedDict

from ruamel.yaml import YAML, MappingNode, ScalarNode
from ruamel.yaml.representer import RoundTripRepresenter


def repr_str(dumper: RoundTripRepresenter, data: str) -> ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def repr_ordered_dict(dumper: RoundTripRepresenter, data: OrderedDict) -> MappingNode:
    return dumper.represent_mapping("tag:yaml.org,2002:map", dict(data))


def from_yaml_to_dict(filename: str) -> OrderedDict:
    with open(filename, encoding="utf-8") as yamlfile:
        yaml = YAML()
        return OrderedDict(yaml.load(yamlfile))


def from_json_to_dict(filename: str) -> OrderedDict:
    with open(filename, encoding="utf-8") as jsonfile:
        return OrderedDict(json.load(jsonfile))


def from_dict_to_yaml(data: dict | list, output: typing.TextIO) -> None:
    yaml = YAML()
    yaml.representer.add_representer(str, repr_str)
    yaml.representer.add_representer(OrderedDict, repr_ordered_dict)
    yaml.dump(data, output)


def from_dict_to_json(data: dict, output: typing.TextIO) -> None:
    json.dump(data, output, indent=4)


def guess_format(filename: str, designation: str) -> str | None:
    (name, ext) = os.path.splitext(filename)
    if ext in [".yaml", ".json"]:
        if designation == "infer" or designation == ext:
            return ext
    return None
