import logging
import uuid
import xml.etree.ElementTree as ET

# Assuming util.py and factory.py are in the same directory
import util
import factory
import HIA_Com_merger_ref as hair
from test import read_arxml_contents
import copy

# --- Helper Class ---
class ArxmlFile:
    """A simple wrapper to hold the XML tree and parent map, replacing the MagicMock."""
    def __init__(self, tree):
        self.xml = tree
        # The parent map is populated by the util functions as elements are added.
        self.parents = {}

# --- Refactored Functions ---
# This section contains the functions we are testing.

_COMMUNICATION_PACKAGES_ = ['ISignal', 'ISignalGroup', 'Pdu', 'Frame']

def _find_or_create_subpackage(parent_pkg, subpackage_name, dst_arxml):
    """
    Finds a sub-package by name within a parent's 'AR-PACKAGES' element.
    If not found, it creates and appends it with the correct XML namespace.
    """
    dst_ar_packages_container = util.xml_elem_find(parent_pkg, 'AR-PACKAGES')
    if dst_ar_packages_container is None:
        parent_name_el = parent_pkg.find('SHORT-NAME')
        parent_name = parent_name_el.text if parent_name_el is not None else "[Unknown Package]"
        logging.error(f"Destination package '{parent_name}' is missing <AR-PACKAGES> container.")
        return None

    dst_pkg = util.xml_ar_package_find(dst_ar_packages_container, subpackage_name)
    if dst_pkg is None:
        parent_name_el = parent_pkg.find('SHORT-NAME')
        parent_name = parent_name_el.text if parent_name_el is not None else "[Unknown Parent]"
        logging.info(f"Creating missing destination package: {parent_name}/{subpackage_name}")
        uuid_val = f"{str(uuid.uuid4())}-Communication-{subpackage_name}"
        
        # Create elements programmatically to handle namespaces correctly
        # and avoid XML ParseError.
        namespace_uri = util.xml_get_namespace(parent_pkg)
        
        if namespace_uri:
            ar_pkg_tag = f"{{{namespace_uri}}}AR-PACKAGE"
            short_name_tag = f"{{{namespace_uri}}}SHORT-NAME"
            elements_tag = f"{{{namespace_uri}}}ELEMENTS"
        else:
            ar_pkg_tag = "AR-PACKAGE"
            short_name_tag = "SHORT-NAME"
            elements_tag = "ELEMENTS"

        # Create the parent AR-PACKAGE element
        dst_pkg = ET.Element(ar_pkg_tag, attrib={'UUID': uuid_val})
        
        # Create and append the SHORT-NAME child
        short_name_el = ET.Element(short_name_tag)
        short_name_el.text = subpackage_name
        dst_pkg.append(short_name_el)
        
        # Create and append the ELEMENTS child
        elements_el = ET.Element(elements_tag)
        dst_pkg.append(elements_el)
        
        util.xml_elem_append(dst_ar_packages_container, dst_pkg, dst_arxml.parents)
    return dst_pkg

def _validate_pdu_frame_lengths(src_com_pkg):
    """
    Validates that I-SIGNAL-I-PDU lengths match their corresponding CAN-FRAME lengths.
    This version is more robust and checks for the existence of elements before access.
    """
    isig_pdus = util.xml_elem_findall(src_com_pkg, 'I-SIGNAL-I-PDU')
    frames = util.xml_elem_findall(src_com_pkg, 'CAN-FRAME')

    if not frames or not isig_pdus:
        return

    # Robustly gather PDU lengths and names
    isig_pdus_len = []
    for pdu in isig_pdus:
        length_el = util.xml_elem_find(pdu, "LENGTH")
        name_el = pdu.find('SHORT-NAME')
        if length_el is not None and name_el is not None:
            isig_pdus_len.append((length_el.text, name_el.text))

    # Robustly gather Frame lengths and names
    frame_len = []
    for frame in frames:
        length_el = util.xml_elem_find(frame, "FRAME-LENGTH")
        pdu_ref_el = util.xml_elem_find(frame, "PDU-REF")
        if length_el is not None and pdu_ref_el is not None and pdu_ref_el.text:
            frame_len.append((length_el.text, pdu_ref_el.text.split("/")[-1]))

    # Sort lists to ensure correct comparison
    isig_pdus_len.sort(key=lambda x: x[1])
    frame_len.sort(key=lambda x: x[1])

    for pdu_cfg, frame_cfg in zip(isig_pdus_len, frame_len):
        # Ensure PDU names match before comparing lengths
        if pdu_cfg[1] == frame_cfg[1] and pdu_cfg[0] != frame_cfg[0]:
            logging.warning(
                f"Mismatch found for PDU: {pdu_cfg[1]}. "
                f"Frame length: {frame_cfg[0]}, PDU length: {pdu_cfg[0]}"
            )

def _copy_isignal_pdus(src_com_pkg, dst_pdu_pkg, src_arxml, dst_arxml):
    """
    Copies I-SIGNAL-I-PDU elements and validates their lengths.
    """
    isig_pdus = util.xml_elem_findall(src_com_pkg, 'I-SIGNAL-I-PDU')
    if not isig_pdus:
        logging.warning("No 'I-SIGNAL-I-PDU' elements found in source Communication package.")
        return []

    dst_elements_container = util.xml_elem_find_assert_exists(dst_pdu_pkg, 'ELEMENTS')
    # FIX: Pass a deep copy of the elements to avoid modifying the source tree.
    util.xml_elem_extend([copy.deepcopy(el) for el in isig_pdus], dst_elements_container, src_arxml, dst_arxml, graceful=True)
    _validate_pdu_frame_lengths(src_com_pkg)
    
    pdu_names = []
    for pdu in isig_pdus:
        name_el = pdu.find('SHORT-NAME')
        if name_el is not None:
            pdu_names.append(name_el.text)
    return pdu_names

def _copy_associated_pdu_groups(src_arxml, dst_arxml):
    """Copies ASSOCIATED-COM-I-PDU-GROUP-REFS from source to destination."""
    src_root = src_arxml.xml.getroot()
    dst_root = dst_arxml.xml.getroot()
    
    src_group = util.xml_elem_find(src_root, 'ASSOCIATED-COM-I-PDU-GROUP-REFS')
    dst_group = util.xml_elem_find(dst_root, 'ASSOCIATED-COM-I-PDU-GROUP-REFS')

    if src_group is None:
        logging.warning("Source element 'ASSOCIATED-COM-I-PDU-GROUP-REFS' not found!")
        return
    if dst_group is None:
        logging.error("Destination element 'ASSOCIATED-COM-I-PDU-GROUP-REFS' not found!")
        return

    # FIX: Pass a deep copy of the elements to avoid modifying the source tree.
    util.xml_elem_extend(
        [copy.deepcopy(el) for el in list(src_group)], dst_group, src_arxml, dst_arxml,
        src_name=lambda el: el.text,
        dst_name=lambda el: el.text,
        graceful=True
    )

import logging
import uuid
import util
import factory

def copy_communication_packages(src_arxml, dst_arxml):
    """
    Copies Communication packages from src_arxml to dst_arxml as per _COMMUNICATION_PACKAGES_.
    Copies ASSOCIATED-COM-I-PDU-GROUP-REFS element as well.
    Returns list of I-SIGNAL-I-PDU SHORT-NAMEs found.

    Relies on util and factory for element handling.
    """
    # Find root Communication packages in src and dst
    src_com = util.xml_ar_package_find(src_arxml.xml.getroot(), 'Communication')
    assert src_com is not None, "Source Communication package is not found!"
    dst_com = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'Communication')
    assert dst_com is not None, "Destination Communication package is not found!"

    pdus = []

    for pkg in _COMMUNICATION_PACKAGES_:
        src = util.xml_ar_package_find(src_com, pkg)
        dst = util.xml_ar_package_find(dst_com, pkg)

        if src is None:
            logging.warning("Missing source package Communication/%s", pkg)
            util.MISSING_SRC_PACKAGE.append(True)
            continue

        if dst is None:
            # Create missing destination package
            new_uuid = f"{uuid.uuid4()}-Communication-{pkg}"
            dst = factory.xml_ar_package_create(pkg, new_uuid)
            util.assert_elem_tag(dst_com[1], 'AR-PACKAGES')
            util.xml_elem_append(dst_com[1], dst, dst_arxml.parents)

        if pkg == 'Pdu':
            # Copy only I-SIGNAL-I-PDU elements
            isig_pdus = util.xml_elem_findall(src_com, 'I-SIGNAL-I-PDU')
            util.assert_elem_tag(dst[1], 'ELEMENTS')
            util.xml_elem_extend(isig_pdus, dst[1], src_arxml, dst_arxml, graceful=True)

            # Collect PDUs names
            pdus = [pdu[0].text for pdu in isig_pdus]

            # Get PDU lengths and sort by PDU name
            isig_pdus_len = sorted(
                ((util.xml_elem_find(pdu, "LENGTH").text, pdu[0].text) for pdu in isig_pdus),
                key=lambda x: x[1]
            )

            # Get CAN-FRAME lengths and referenced PDUs
            frames = util.xml_elem_findall(src_com, 'CAN-FRAME') or []
            frame_len = sorted(
                ((util.xml_elem_find(frame, "FRAME-LENGTH").text,
                  util.xml_elem_find(frame, "PDU-REF").text.split("/")[-1]) for frame in frames),
                key=lambda x: x[1]
            )

            # Warn if mismatch between PDU and Frame lengths
            for i in range(min(len(isig_pdus_len), len(frame_len))):
                pdu_len, pdu_name = isig_pdus_len[i]
                frame_len_val, frame_pdu_name = frame_len[i]
                if (pdu_name != frame_pdu_name) or (pdu_len != frame_len_val):
                    logging.warning(
                        "Length mismatch found in PDU '%s': FRAME-LENGTH=%s, PDU LENGTH=%s",
                        pdu_name, frame_len_val, pdu_len
                    )
                    break
            continue  # Done with Pdu package, continue loop

        # For other packages, copy entire elements
        util.assert_elem_tag(src[1], 'ELEMENTS')
        util.assert_elem_tag(dst[1], 'ELEMENTS')
        util.xml_elem_extend(src[1], dst[1], src_arxml, dst_arxml)

    # Copy ASSOCIATED-COM-I-PDU-GROUP-REFS
    src_group = util.xml_elem_find(src_arxml.xml.getroot(), 'ASSOCIATED-COM-I-PDU-GROUP-REFS')
    assert src_group is not None, "Source ASSOCIATED-COM-I-PDU-GROUP-REFS is not found!"
    dst_group = util.xml_elem_find(dst_arxml.xml.getroot(), 'ASSOCIATED-COM-I-PDU-GROUP-REFS')
    assert dst_group is not None, "Destination ASSOCIATED-COM-I-PDU-GROUP-REFS is not found!"

    util.xml_elem_extend(
        list(src_group), dst_group, src_arxml, dst_arxml,
        src_name=lambda el: el.text,
        dst_name=lambda el: el.text,
        graceful=True
    )

    return pdus


# --- Main Test Execution ---

def main():
    """
    Main function to load ARXML files and run the copy process.
    """
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(message)s')
    
    source_file = 'SRC_one.arxml'
    target_file = 'Target_one.arxml'
    output_file_old = 'merged_output_old.arxml'
    output_file_new = 'merged_output_new.arxml'

    try:
        source_tree = ET.parse(source_file)
        src_arxml = ArxmlFile(source_tree)

        target_tree = ET.parse(target_file)
        dst_arxml = ArxmlFile(target_tree)

    except FileNotFoundError as e:
        logging.error(f"Error loading file: {e}. Make sure '{source_file}' and '{target_file}' are in the same directory.")
        return
    except ET.ParseError as e:
        logging.error(f"Error parsing XML file: {e}")
        return

    print(f"--- Starting merge from '{source_file}' to '{target_file}' ---")
    
    # Run the function
    copied_pdus_old = hair.copy_communication_packages_old(src_arxml, dst_arxml)    
    print("\n--- Old Merge complete ---")
    print(f"Copied I-SIGNAL-I-PDU names: {copied_pdus_old}")
    print(len(copied_pdus_old))

    # Save the modified target tree to a new file for inspection
    try:
        modified_tree = dst_arxml.xml
        # Register the namespace to ensure it's preserved in the output file
        namespace = util.xml_get_namespace(modified_tree.getroot())
        if namespace:
            ET.register_namespace('', namespace) # The prefix is empty

        modified_tree.write(output_file_old, encoding='utf-8', xml_declaration=True)
        print(f"\nSuccessfully saved modified XML to '{output_file_old}'")
    except Exception as e:
        print(f"\nError saving output file: {e}")

    copied_pdus_new = copy_communication_packages(src_arxml, dst_arxml)    
    print("\n--- New Merge complete ---")
    print(f"Copied I-SIGNAL-I-PDU names: {copied_pdus_old}")
    print(len(copied_pdus_new))

    # Save the modified target tree to a new file for inspection
    try:
        modified_tree = dst_arxml.xml
        # Register the namespace to ensure it's preserved in the output file
        namespace = util.xml_get_namespace(modified_tree.getroot())
        if namespace:
            ET.register_namespace('', namespace) # The prefix is empty

        modified_tree.write(output_file_new, encoding='utf-8', xml_declaration=True)
        print(f"\nSuccessfully saved modified XML to '{output_file_new}'")
    except Exception as e:
        print(f"\nError saving output file: {e}")


    print(f"\tCOmpare: {copied_pdus_old == copied_pdus_new}\t".center(75, '*'))
    # old = read_arxml_contents(output_file_old)
    # new = read_arxml_contents(output_file_new)
    old = read_arxml_contents('SRC_one.arxml')
    new = read_arxml_contents('SRC_two.arxml')
    old = util.xml_elem_str(old.getroot())
    new = util.xml_elem_str(new.getroot())
    print(old == new)

if __name__ == "__main__":
    main()
