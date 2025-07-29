import logging
import uuid
import copy
import xml.etree.ElementTree as ET

# Assuming util.py, factory.py, and other constants are available
import util
import factory
import HIA_Com_merger_ref as hair
from test import read_arxml_contents
import common_fxn as cf

# Constants that would be defined elsewhere in the project
_CHANNEL_MAPPING_ = ['CAN-PHYSICAL-CHANNEL', 'ETHERNET-PHYSICAL-CHANNEL']

# --- Helper Class ---
class ArxmlFile:
    def __init__(self, tree):
        self.xml = tree
        self.parents = {}
        self.filename = ""

def xml_get_physical_channel(arxml: ET.ElementTree, ch_type, name):
    """
    Finds a PhysicalChannel from a given type and name.
    """
    channels = util.xml_elem_findall(arxml.xml.getroot(), ch_type)
    ### change channels = util.xml_elem_findall(arxml.xml.getroot(), ch_type)
    for channel in channels:
        # Safely find the SHORT-NAME element
        short_name_el = util.xml_get_child_elem_by_tag(channel, 'SHORT-NAME')
        if short_name_el is not None and short_name_el.text == name:
            return channel
    return None

################################ --- KEEP --- #######################################

def copy_network_endpoint(src_arxml, dst_arxml, dst_eth_physical_channel):
    """
    Copies NETWORK-ENDPOINT elements from a source to a destination channel,
    avoiding duplicates based on IPV-4-ADDRESS.

    This is a single, monolithic function that incorporates safety improvements.
    """
    # A nested helper function to safely extract the IP address.
    # This keeps the logic self-contained within the main function.
    def _get_ipv4_address(network_endpoint_element):
        """
        Safely finds and returns the IPV-4-ADDRESS text from a NETWORK-ENDPOINT element.
        Returns an empty string if the address is not found, preventing crashes.
        """
        ipv4_address_el = util.xml_elem_find(network_endpoint_element, 'IPV-4-ADDRESS')
        if ipv4_address_el is not None and ipv4_address_el.text:
            return ipv4_address_el.text
        return "" # Return a stable, non-None value for comparison

    # 1. Find source and destination containers, failing fast if not found.
    src_ch = util.xml_elem_find(src_arxml.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL')
    assert src_ch is not None, "Source element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"
    
    dst_ch = xml_get_physical_channel(dst_arxml, 'ETHERNET-PHYSICAL-CHANNEL', dst_eth_physical_channel)
    assert dst_ch is not None, f"Destination element 'ETHERNET-PHYSICAL-CHANNEL' named '{dst_eth_physical_channel}' is not found!"

    src_net_ends_container = util.xml_elem_find(src_ch, 'NETWORK-ENDPOINTS')
    assert src_net_ends_container is not None, "Source element 'NETWORK-ENDPOINTS' is not found!"
    
    dst_net_ends_container = util.xml_elem_find(dst_ch, 'NETWORK-ENDPOINTS')
    assert dst_net_ends_container is not None, "Destination element 'NETWORK-ENDPOINTS' is not found!"

    # 2. Find all direct NETWORK-ENDPOINT children in the source.
    source_endpoints_to_copy = util.xml_elem_findall(src_net_ends_container, 'NETWORK-ENDPOINT')

    if not source_endpoints_to_copy:
        logging.info("No NETWORK-ENDPOINT elements found in the source to copy.")
        return {}

    # 3. Extend the destination list, using the safe helper to check for conflicts.
    logging.info(f"Found {len(source_endpoints_to_copy)} source network endpoints. Checking for duplicates before copying.")
    
    # Use deepcopy to prevent modifying the source tree.
    path_map = util.xml_elem_extend(
        [copy.deepcopy(el) for el in source_endpoints_to_copy],
        dst_net_ends_container,
        src_arxml,
        dst_arxml,
        src_name=_get_ipv4_address,
        dst_name=_get_ipv4_address,
        graceful=True
    )

    return path_map

# --- Main Test Execution ---
def main():
    """
    Main function to load sample ARXML data and run the copy_network_endpoint process.
    This version uses the real util.py functions for testing.
    """
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    # --- Sample Data Setup ---
    namespace = "http://autosar.org/schema/r4.0"
    # FIX: This source XML is intentionally missing the <NETWORK-ENDPOINTS> container
    # to test the assertion that it exists.
    source_xml_str = f"""
    <AUTOSAR xmlns="{namespace}">
      <AR-PACKAGES>
        <AR-PACKAGE>
          <ELEMENTS>
            <ETHERNET-PHYSICAL-CHANNEL>
              <SHORT-NAME>SRC_ETH_CH</SHORT-NAME>
              <!-- The NETWORK-ENDPOINTS container is missing -->
            </ETHERNET-PHYSICAL-CHANNEL>
          </ELEMENTS>
        </AR-PACKAGE>
      </AR-PACKAGES>
    </AUTOSAR>
    """

    destination_xml_str = f"""
    <AUTOSAR xmlns="{namespace}">
      <AR-PACKAGES>
        <AR-PACKAGE>
          <ELEMENTS>
            <ETHERNET-PHYSICAL-CHANNEL>
              <SHORT-NAME>DST_ETH_CH</SHORT-NAME>
              <NETWORK-ENDPOINTS>
                <!-- This endpoint already exists in the destination -->
                <NETWORK-ENDPOINT UUID="ep-dst-1">
                  <SHORT-NAME>HI_Endpoint</SHORT-NAME>
                  <IPV-4-CONFIGURATION><IPV-4-ADDRESS>10.0.0.1</IPV-4-ADDRESS></IPV-4-CONFIGURATION>
                </NETWORK-ENDPOINT>
              </NETWORK-ENDPOINTS>
            </ETHERNET-PHYSICAL-CHANNEL>
          </ELEMENTS>
        </AR-PACKAGE>
      </AR-PACKAGES>
    </AUTOSAR>
    """

    # Create ArxmlFile wrapper objects
    source_element = ET.fromstring(source_xml_str)
    source_tree = ET.ElementTree(source_element)
    source_tree = read_arxml_contents("SRC_one.arxml")
    src_arxml_old = ArxmlFile(source_tree)
    src_arxml_new = ArxmlFile(source_tree)

    target_element = ET.fromstring(destination_xml_str)
    target_tree = ET.ElementTree(target_element)
    target_tree = read_arxml_contents("Target_one.arxml")
    dst_arxml_old = ArxmlFile(target_tree)
    dst_arxml_new = ArxmlFile(target_tree)
    
    output_file_old = 'network_endpoint_merged_old.arxml'
    output_file_new = 'network_endpoint_merged_new.arxml'

    print("--- OLD Destination NETWORK-ENDPOINTS before copy ---")
    dst_ch_before = util.xml_elem_type_find(dst_arxml_old.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL', "HIASystemCoreInternal")
    if dst_ch_before:
        # FIX: Use the namespace-aware util.xml_elem_find for consistency and correctness.
        net_ends_before = util.xml_elem_find(dst_ch_before, "NETWORK-ENDPOINTS")
        if net_ends_before is not None:
            print(ET.tostring(net_ends_before, encoding='unicode').strip())
    print("-" * 40)

    # Run the function
    path_map = hair.copy_network_endpoint(src_arxml_old, dst_arxml_old, "HIASystemCoreInternal")
    
    print("\n--- Destination NETWORK-ENDPOINTS after copy ---")
    dst_ch_after = util.xml_elem_type_find(dst_arxml_old.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL', "HIASystemCoreInternal")
    # Register namespace for clean printing
    ET.register_namespace('', namespace)
    if dst_ch_after:
        # FIX: Use the namespace-aware util.xml_elem_find here as well.
        net_ends_after = util.xml_elem_find(dst_ch_after, "NETWORK-ENDPOINTS")
        if net_ends_after is not None:
            print(ET.tostring(net_ends_after, encoding='unicode').strip())
    print("-" * 40)

    print(f"\nPath map returned: {path_map}")
    
    # Save the result
    dst_arxml_old.xml.write(output_file_old, encoding='utf-8', xml_declaration=True)
    print(f"Successfully saved modified XML to '{output_file_old}'")


    dst_ch_before = util.xml_elem_type_find(dst_arxml_new.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL', "HIASystemCoreInternal")
    if dst_ch_before:
        # FIX: Use the namespace-aware util.xml_elem_find for consistency and correctness.
        net_ends_before = util.xml_elem_find(dst_ch_before, "NETWORK-ENDPOINTS")
        if net_ends_before is not None:
            print(ET.tostring(net_ends_before, encoding='unicode').strip())
    print("-" * 40)

    # Run the function
    path_map_new = cf.copy_network_endpoint(src_arxml_new, dst_arxml_new, "HIASystemCoreInternal")
    
    print("\n--- Destination NETWORK-ENDPOINTS after copy ---")
    dst_ch_after = util.xml_elem_type_find(dst_arxml_new.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL', "HIASystemCoreInternal")
    # Register namespace for clean printing
    ET.register_namespace('', namespace)
    if dst_ch_after:
        # FIX: Use the namespace-aware util.xml_elem_find here as well.
        net_ends_after = util.xml_elem_find(dst_ch_after, "NETWORK-ENDPOINTS")
        if net_ends_after is not None:
            print(ET.tostring(net_ends_after, encoding='unicode').strip())
    print("-" * 40)

    print(f"\nPath map returned: {path_map_new}")
    
    # Save the result
    dst_arxml_new.xml.write(output_file_new, encoding='utf-8', xml_declaration=True)
    print(f"Successfully saved modified XML to '{output_file_new}'")

    old = util.xml_elem_str(read_arxml_contents(output_file_old).getroot())
    new = util.xml_elem_str(read_arxml_contents(output_file_new).getroot())
    print(old == new)


if __name__ == "__main__":
    # This script now relies on the actual util.py functions being available
    # and correctly implemented. No mocks are needed.
    main()
