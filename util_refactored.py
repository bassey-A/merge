# replace class ScriptOptions as it uses OptionParser which is deprecated
# parse_script_arguments is a  replacement for ScriptOptions
import argparse
from pathlib import Path

def parse_script_arguments(args, description, version):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        '-v', '--version',
        action='version',
        version=f'%(prog)s {version}'
    )
    parser.add_argument(
        '-i', '--input-arxml',
        required=True,
        type=Path,
        help='Input file to read.'
    )
    parser.add_argument(
        '-o', '--output-arxml',
        type=Path,
        help='Output file to write.'
    )
    
    options = parser.parse_args(args)

    # argparse handles file existence checks better, but a manual one is clear
    if not options.input_arxml.is_file():
        parser.error(f"The file doesn't exist: {options.input_arxml}")

    return options

def removesuffix(string: str, suffix:str) -> str:
    """
    Returns the specified string without the specified suffix.

    Args:
        string (str): The string to remove the suffix from.
        suffix (str): The suffix to remove.

    Returns:
        str: The string without the specified suffix.
    """
    if isinstance(string, str):
        return string.removesuffix(suffix)
    raise TypeError # string must be a str


def removeprefix(string: str, prefix: str) -> str:
    """
    Returns the specified string without the specified prefix.

    Args:
        string (str): The string to remove the prefix from.
        prefix (str): The prefix to remove.

    Returns:
        str: The string without the specified prefix.
    """
    if isinstance(string, str):
        return string.removeprefix(prefix)
    raise TypeError # string must be a str

#def xml_get_child_elem_by_tag(elem: ET.Element, tag: str) -> str:
