import xml.etree.ElementTree as ET
import uuid
import logging
from typing import Optional
from xml.dom import minidom
from pathlib import Path
import util
import HIA_Com_merger_ref as hair

def read_files():
    return [item for item in Path('.').iterdir() if item.is_file() and '.arxml' in item.name]

def read_arxml_contents(file_path: str) -> Optional[ET.ElementTree]:
    """
    Reads an arxml file and returns it as a ET.Element.

    Args:
        file_path: The full string path to the file to be read.
                change ...(e.g., "C:/Users/user/Documents/config.arxml" or "/home/user/config.arxml")

    Returns:
        xml.etree.ElementTree
    """

    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            root_element = ET.parse(file)
            return root_element

    except FileNotFoundError:
        print(f"\n[ERROR] The file could not be found at the specified path: {file_path}")
    
    except IOError as e:
        print(f"\n[ERROR] An error occurred while reading the file: {e}")
    
    except Exception as e:
        print(f"\n[ERROR] An unexpected error occurred: {e}")

# --- Helper function for logging, as provided by you ---
def xml_elem_str(elem: ET.Element, *, indent_with:str ="    ") -> str:
    """
    Returns a pretty formated string representation of the specified element.

    Args:
        elem (ET.Element): The element to stringify.
        indent_with (str, optional): Indent nested tags with this. Defaults to "    ".
    Returns:
        str: The string representation of the specified element.
    """
    if elem is None:
        return ""
    if isinstance(elem, ET.Element):
        raw_elem_str = ET.tostring(elem,
                                   encoding='utf-8',
                                   short_empty_elements=False)
        minidom_elem = minidom.parseString(raw_elem_str)
        pretty_elem_str = minidom_elem.toprettyxml(indent=indent_with)
        # Remove (potential) empty lines and the initial
        # <?xml version="1.0" ?> added by minidom
        return "\n".join([s for s in pretty_elem_str.split("\n")
                          if s.strip()][1:])

    raise TypeError



def old_replace_uuid(elem):
    """
        Given an Autosar element, replace its UUID with a newly generated one.
        Used to avoid duplicate UUIDs in .arxmls since DaVinci tools complain
        about this problem. Instead of completely removing UUIDs we should
        replace them and keep track of the replacement in order to have Autosar
        element tracebility back to the tools that produced them initially.
    """

    elem_uuid = elem.attrib['UUID']
    if elem_uuid:
        new_uuid = str(uuid.uuid4())
        logging.debug("Replacing UUID of element %s with new UUID %s",
            xml_elem_str(elem).split('\n', 2)[0:2],
            new_uuid
        )
        elem.attrib.pop("UUID", None)
        elem.set("UUID", new_uuid)
    else:
        logging.warning("Trying to replace UUID of element %s with no UUID",
            xml_elem_str(elem).split('\n', 2)[0:2]
        )
    return new_uuid

# --- Improved Function with Original Signature ---

def replace_uuid(elem: ET.Element) -> Optional[str]:
    """
    Given an Autosar element, replace its UUID with a newly generated one.

    This improved version safely handles elements that may not have a UUID
    attribute, preventing crashes and providing clearer logging.

    Args:
        elem: The XML element whose UUID should be replaced.

    Returns:
        The new UUID as a string if a replacement was made, otherwise None.
    """
    # Safely get the original UUID. elem.get() returns None if 'UUID' does not exist,
    # preventing a KeyError. This fixes the main bug in the original function.
    original_uuid = elem.get("UUID")

    if original_uuid is not None:
        new_uuid = str(uuid.uuid4())
        
        logging.debug(
            "Replacing UUID of element %s with new UUID %s",
            xml_elem_str(elem).split('\n', 2)[0:2],
            new_uuid
        )
        
        # Directly set the new UUID. This is simpler and more efficient than
        # popping the old attribute first.
        elem.set("UUID", new_uuid)
        
        return new_uuid
    else:
        # This warning is now correctly triggered if the attribute is missing.
        logging.warning(
            "Trying to replace UUID of element %s with no UUID",
            xml_elem_str(elem).split('\n', 2)[0:2]
        )
        # Return None to indicate no action was taken. The original function
        # would have crashed with a NameError here.
        return None
    

def ensure_unique_uuids(arxml):
    """
    Ensures every XML element with a UUID attribute has a unique UUID.
    Updates duplicate UUIDs and writes changes back to the ARXML file.
    """
    #root = arxml.xml.getroot()
    root = arxml
    seen = {}
    for i, elem in enumerate(root.findall('.//*[@UUID]')):
        print(f"{i}: {elem.get('UUID')}")
        # current_uuid = elem.attrib['UUID']
        # #current_uuid = elem.get('UUID')
        # logging.debug("Checking UUID %s", current_uuid)
        # if current_uuid in seen:
        #     new_uuid = replace_uuid(elem)
        #     seen[new_uuid] = elem
        # else:
        #     seen[current_uuid] = elem

class ArxmlDoc:
        __slots__ = ['xml']
        def __init__(self, element_tree):
            self.xml = element_tree

def main():
    # Configure basic logging to see the output
    logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

    # arxmls = read_files()
    # target = ET.parse(arxmls[1])
    # source_one = read_arxml_contents('SRC_one.arxml')
    # target_one = read_arxml_contents('Target_one.arxml')
    # source_two = read_arxml_contents('SRC_one.arxml')
    # target_two = read_arxml_contents('Target_one.arxml')


    # ensure_unique_uuids(target)
    with open('HIA_com_merger.py', '+r') as a:
        a_merge = a.readlines()
    with open('HIB_com_merger.py', '+r') as b:
        b_merge = b.readlines()
    with open('HIC_com_merger.py', '+r') as c:
        c_merge = c.readlines()
    a_fxns = [line.strip() for line in a_merge if line.startswith('def')]
    b_fxns = [line.strip() for line in b_merge if line.startswith('def')]
    c_fxns = [line.strip() for line in c_merge if line.startswith('def')]
    print(f"A: {len(a_fxns)}\tB: {len(b_fxns)}\tC: {len(c_fxns)}")
    for x, (y, z) in enumerate(zip(sorted(a_fxns), sorted(b_fxns)), start=1):
        print(f'{x:3}:    {y.ljust(85)}{z}')
    for fxn in a_fxns:
        if fxn not in b_fxns:
            print(f"{fxn}: {fxn in b_fxns}")

    for fxn in b_fxns:
        if fxn not in a_fxns:
            print(f"{fxn}: {fxn in a_fxns}")
    
    common_fxns = [fxn for fxn in c_fxns if fxn in a_fxns and fxn in b_fxns]




    print('COMMON FUNCTIONS'.center(200, '-'))
    for i, j in enumerate(common_fxns):
        print(f"{i:3} ---> {j}")
    # print(f"TYpeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee{type(source_one)}")
    # print(dir(ET.Element))
    # print(dir(ET.ElementTree))
    # pdus = (hair.fetch_pdu(source_one))
    # print(pdus)
    # hair.copy_fibex_elements_old(source_one, target_one, pdus)
    # hair.copy_fibex_elements(source_two, target_two, pdus)
    # print(util.xml_elem_str(target_one) == util.xml_elem_str(target_two))


if __name__ == '__main__':
    main()
