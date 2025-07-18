# -*- coding: utf-8 -*-

from util import *
from typing import Optional, List
from xml.dom import minidom
import xml.etree.ElementTree as ET


def read_arxml_contents(file_path: str) -> Optional[ET.Element]:
    """
    Opens an arxml file and returns it as a ET.Element.

    Args:
        file_path: The full string path to the file to be read.
                   (e.g., "C:/Users/user/Documents/config.arxml" or "/home/user/config.arxml")

    Returns:
        xml.etree.ElementTree
    """

    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            root_element = ET.parse(file).getroot()
            return root_element

    except FileNotFoundError:
        print(f"\n[ERROR] The file could not be found at the specified path: {file_path}")
    
    except IOError as e:
        print(f"\n[ERROR] An error occurred while reading the file: {e}")
    
    except Exception as e:
        print(f"\n[ERROR] An unexpected error occurred: {e}")

def get_namespace(elem: ET.Element) -> str:
    if '}' in elem.tag:
        return elem.tag.split('}')[0][1:]
    return ''


def find_child_from_tag(elem: ET.Element, tag: str) -> Optional[ET.Element]:
    return elem.find('.//')


def find_all_children(elem: ET.Element) -> List[ET.Element]:
    return list(elem)


def xml_get_child_elem_by_tag_n(elem: ET.Element, tag: str) -> str:
    namespace = get_namespace(elem)
    print(f'Namespace parent: {namespace}')
    full_tag = f"{{{namespace}}}SHORT_NAME"
    print(full_tag)
    for child in list(elem):
        print(child.tag)
        if child.tag == full_tag:
            elem = child
            assert elem is not None
            return elem
    error(f"No child found with tag '{tag}'.")


def print_element_tags_recursively(elem: ET.Element, indent: str = ""):
    """
    Recursively walks through an XML element and prints the tag of each
    element and its children, with indentation to show the hierarchy.

    Args:
        elem: The starting ET.Element to traverse.
        indent: The string used for indentation (managed internally by the recursion).
    """
    # Clean up the tag for printing (removes the long namespace)
    clean_tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
    print(f"{indent}<{clean_tag}>")

    # The recursive step: call the function for each direct child
    for child in find_all_children(elem):
        print_element_tags_recursively(child, indent + "  ")

if __name__ == "__main__":
    source = "SRC.arxml"
    
    try:
        arxml = read_arxml_contents(source)
        # child = find_all_children(arxml)[0]
        # grand_children = find_all_children(child)
        # print(len(grand_children))
        # print(*grand_children)
        # print(f'ECu\n{find_child_from_tag(arxml, "ECUSystem")}')
        # print(xml_get_child_elem_by_tag_n(arxml, "ECUSystem"))
        print_element_tags_recursively(arxml)


    finally:
        print("CLOSING".center(80, "*"))
