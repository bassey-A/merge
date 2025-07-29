import xml.etree.ElementTree as ET
import logging
import uuid
from typing import List, Optional, Tuple, Union


# This document assumes your util.py file contains the functions from
# the 'documented_util_py' artifact, and that you have a 'factory' object.
# It also assumes a global list _COMMUNICATION_PACKAGES_ exists.

# --- New Helper Functions (can be added to util.py) ---

def get_pdu_names(isignal_pdus: List[ET.Element]) -> List[str]:
    """Safely extracts the SHORT-NAME text from a list of I-SIGNAL-I-PDU elements."""
    pdu_names = []
    for pdu in isignal_pdus:
        # Assumes xml_get_child_value_by_tag is in your util.py
        name = xml_get_child_value_by_tag(pdu, 'SHORT-NAME')
        if name:
            pdu_names.append(name)
    return pdu_names

def get_pdu_and_frame_lengths(src_com: ET.Element):
    """
    Safely extracts and sorts the lengths of PDUs and their corresponding CAN frames.
    """
    isig_pdus = xml_elem_findall(src_com, 'I-SIGNAL-I-PDU')
    pdu_lengths = []
    for pdu in isig_pdus:
        length = xml_get_child_value_by_tag(pdu, "LENGTH")
        name = xml_get_child_value_by_tag(pdu, "SHORT-NAME")
        if length and name:
            pdu_lengths.append((length, name))
    
    frames = xml_elem_findall(src_com, 'CAN-FRAME')
    frame_lengths = []
    if frames:
        for frame in frames:
            length = xml_get_child_value_by_tag(frame, "FRAME-LENGTH")
            pdu_ref = xml_get_child_value_by_tag(frame, "PDU-REF")
            if length and pdu_ref:
                frame_lengths.append((length, pdu_ref.split("/")[-1]))

    return sorted(pdu_lengths, key=lambda x: x[1]), sorted(frame_lengths, key=lambda x: x[1])


# --- Refactored Main Function ---

def copy_communication_packages(src_arxml, dst_arxml):
    """
    Copies and merges communication packages from a source to a destination ARXML.
    """
    # Get source and destination packages safely
    src_com = xml_ar_package_find(src_arxml.xml.getroot(), 'Communication')
    if src_com is None:
        raise ValueError("Source Communication package is not found!")
    
    dst_com = xml_ar_package_find(dst_arxml.xml.getroot(), 'Communication')
    if dst_com is None:
        raise ValueError("Destination Communication package is not found!")

    pdus = []
    for name in _COMMUNICATION_PACKAGES_:
        src = xml_ar_package_find(src_com, name)
        dst = xml_ar_package_find(dst_com, name)
        
        if src is None:
            logging.warning("Missing source package Communication/%s", name)
            # This part still uses a global, as per the original code
            MISSING_SRC_PACKAGE.append(True)
            continue
            
        if dst is None:
            # This block depends on the factory class and is kept as is.
            dst = factory.xml_ar_package_create(name, str(uuid.uuid4()) +
                                        '-Communication-' + name)
            # The fragile index access is kept here as it depends on the factory's output
            assert_elem_tag(dst_com[1], 'AR-PACKAGES')
            xml_elem_append(dst_com[1], dst, dst_arxml.parents)

        if name == 'Pdu':
            isig_pdus = xml_elem_findall(src_com, 'I-SIGNAL-I-PDU')
            
            # Safely find the ELEMENTS container
            dst_elements = xml_get_child_elem_by_tag(dst, 'ELEMENTS')
            if dst_elements is None:
                raise ValueError(f"Destination package '{name}' is missing its ELEMENTS container.")
            
            xml_elem_extend(isig_pdus, dst_elements, src_arxml, dst_arxml)
            
            # Use helper functions to safely extract data
            pdus = get_pdu_names(isig_pdus)
            isig_pdus_len, frame_len = get_pdu_and_frame_lengths(src_com)

            # Compare lengths
            for pdu_cfg, frame_cfg in zip(isig_pdus_len, frame_len):
                if pdu_cfg != frame_cfg:
                    logging.warning("Found a mismatch: in PDU: %s, frame length: %s, PDU length: %s",
                                    frame_cfg[1], frame_cfg[0], pdu_cfg[0])
            continue

        # Safely find and extend other elements
        src_elements = xml_get_child_elem_by_tag(src, 'ELEMENTS')
        dst_elements = xml_get_child_elem_by_tag(dst, 'ELEMENTS')
        if src_elements is not None and dst_elements is not None:
            xml_elem_extend(list(src_elements), dst_elements, src_arxml, dst_arxml)

    # Safely find and extend the PDU group refs
    src_group = xml_elem_find(src_arxml.xml.getroot(), 'ASSOCIATED-COM-I-PDU-GROUP-REFS')
    if src_group is None:
        raise ValueError("Source element ASSOCIATED-COM-I-PDU-GROUP-REFS is not found!")
        
    dst_group = xml_elem_find(dst_arxml.xml.getroot(), 'ASSOCIATED-COM-I-PDU-GROUP-REFS')
    if dst_group is None:
        raise ValueError("Destination element ASSOCIATED-COM-I-PDU-GROUP-REFS is not found!")
        
    xml_elem_extend(list(src_group), dst_group, src_arxml, dst_arxml,
                    src_name=lambda el: el.text,
                    dst_name=lambda el: el.text)
    return pdus

# --- Test Harness ---

# Global constant needed by the function being tested
_COMMUNICATION_PACKAGES_ = ['Pdu', 'Frame', 'ISignal']
MISSING_SRC_PACKAGE = []

# Mock factory to ensure it's not called
class MockFactory:
    def xml_ar_package_create(self, name: str, uuid_str: str) -> ET.Element:
        # This should not be called in our test scenario
        raise AssertionError("factory.xml_ar_package_create was called unexpectedly!")

factory = MockFactory()

# --- Re-implementations of util functions based on util.py ---
def _get_namespace(elem: ET.Element) -> str:
    return elem.tag.split('}')[0][1:] if '}' in elem.tag else ''

def xml_ar_package_find(parent: ET.Element, name: str) -> Optional[ET.Element]:
    ns = _get_namespace(parent)
    for pkg in parent.findall(f".//{{{ns}}}AR-PACKAGE"):
        short_name_el = pkg.find(f"{{{ns}}}SHORT-NAME")
        if short_name_el is not None and short_name_el.text == name:
            return pkg
    return None

def xml_elem_findall(parent: ET.Element, tag: str) -> List[ET.Element]:
    ns = _get_namespace(parent)
    return parent.findall(f".//{{{ns}}}{tag}")

def xml_elem_find(parent: ET.Element, tag: str) -> Optional[ET.Element]:
    ns = _get_namespace(parent)
    return parent.find(f".//{{{ns}}}{tag}")

def xml_get_child_elem_by_tag(elem: ET.Element, tag: str) -> Optional[ET.Element]:
    ns = _get_namespace(elem)
    return elem.find(f"{{{ns}}}{tag}")

def xml_get_child_value_by_tag(elem: ET.Element, tag: str) -> Optional[str]:
    child = xml_get_child_elem_by_tag(elem, tag)
    return child.text if child is not None else None

def assert_elem_tag(elem: ET.Element, tag: Union[Tuple, str]) -> None:
    pass # Not needed for this test logic

def xml_elem_append(elem: ET.Element, child: ET.Element, parents: dict) -> None:
    pass # Not needed as factory is avoided

def xml_elem_extend(src_elems, dst_elems, src_arxml, dst_arxml, **kwargs):
    for elem in src_elems:
        dst_elems.append(elem)

# Simple wrapper class to simulate the arxml document objects
class ArxmlDoc:
    def __init__(self, file_path):
        self.tree = ET.parse(file_path)
        self.xml = self.tree # to support .xml.getroot()
        self.parents = {} # Simplified for test

def main():
    """
    Main function to test the refactored copy_communication_packages.
    """
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    # Load the ARXML files
    src_arxml_file = 'SRC_one.arxml'
    dst_arxml_file = 'Target_one.arxml'
    
    src_arxml = ArxmlDoc(src_arxml_file)
    dst_arxml = ArxmlDoc(dst_arxml_file)

    print("--- Starting Test ---")
    print(f"Source file: {src_arxml_file}")
    print(f"Destination file: {dst_arxml_file}")

    # Run the function
    returned_pdus = copy_communication_packages(src_arxml, dst_arxml)

    print("\n--- Verification ---")
    print(f"Function returned {len(returned_pdus)} PDUs.")
    
    # Verify that the PDU names were correctly extracted and returned
    assert len(returned_pdus) > 0, "Function should have returned a list of PDUs."
    assert 'SrsSrsRedundantCanSignalIpdu01' in returned_pdus, "Expected PDU not found in return list."
    print("✅ PDU list returned successfully.")

    # Verify that the destination file was modified
    dst_root = dst_arxml.xml.getroot()
    dst_com = xml_ar_package_find(dst_root, 'Communication')
    
    # Check that I-SIGNAL-I-PDU elements were copied to the Pdu package
    dst_pdu_pkg = xml_ar_package_find(dst_com, 'Pdu')
    copied_pdus = xml_elem_findall(dst_pdu_pkg, 'I-SIGNAL-I-PDU')
    assert len(copied_pdus) > 0, "I-SIGNAL-I-PDU elements were not copied to the Pdu package."
    print(f"✅ Copied {len(copied_pdus)} PDUs to the destination.")

    # Check that ASSOCIATED-COM-I-PDU-GROUP-REFS was extended
    dst_group_refs = xml_elem_find(dst_root, 'ASSOCIATED-COM-I-PDU-GROUP-REFS')
    total_refs = dst_group_refs.findall('.//*') # Find all children
    # Original Target file has 53 refs, source has 1. Total should be 54.
    assert len(total_refs) == 54, f"Expected 54 PDU group refs, but found {len(total_refs)}."
    print(f"✅ Merged ASSOCIATED-COM-I-PDU-GROUP-REFS correctly.")
    
    print("\nTest completed successfully!")


if __name__ == '__main__':
    # To run this test, you must have SRC_one.arxml and Target_one.arxml
    # in the same directory as this script.
    main()
