#!/usr/bin/python3

import logging
import sys
import uuid
import copy
import xml.etree.ElementTree as ET
import re
import autosar
import factory
# import mrc_abstraction as mrc
import util
# import swc_patcher
# from update_routing_groups import update_all_routing_refs

# This script's version
VERSION = '0.1.1'

# Add here list of root packages to copy
_ROOT_PACKAGES_ = (('Signal',      util.NAME_CLASH_IS_ERROR),
                   ('SignalGroup', util.NAME_CLASH_IS_ERROR))


# Data sync communication packages
_COMMUNICATION_PACKAGES_ = ('Pdu',
                            'ISignal',
                            'ISignalGroup',
                            'ISignalPduGroup')

_VLAN_ = ('HIASystemEthernetMRVlan'
          ,'HIASystemCoreInternal')

# MR COM ISignals init values (from CAN frames)
#
# NOTE: The PDU in which the MRC header resides expects the same endianness for all included signals
#       (otherwise DVCfg throws an error)
#       When we determine the PDU's endianness we look at the CAN Frame's endianness in the Device Proxy
#       However, the MRC header never makes it to the CAN Nodes, it is only used by the VIU. Which means
#       that its endianness needs to be the same as the VIU's (which is big endian)
#       So we have to make sure that the MRC header is big endian so that the VIU interprets it correctly,
#       no matter which endianness the originating CAN Frame might have.
#
#       The solution provided here is to keep using the same endianness as the CAN Frame for the MRC header
#       but changing the init value in such a way that when it gets on the bus, the order of the bytes are correct.
#
#       See https://jira-vira.volvocars.biz/browse/ARTCSP-27578 for details
# _ISIGNAL_INIT_VAL_LTLEND_ =\
#  {('CAN',    'STANDARD'): (mrc.MRC_CAN_STANDARD_INIT_LE,    'isMrCommHdrPartB_Can_'),
#   ('CAN',    'EXTENDED'): (mrc.MRC_CAN_EXTENDED_INIT_LE,    'isMrCommHdrPartB_Can_'),
#   ('CAN-20', 'STANDARD'): (mrc.MRC_CAN_20_STANDARD_INIT_LE, 'isMrCommHdrPartB_Can_'),
#   ('CAN-20', 'EXTENDED'): (mrc.MRC_CAN_20_EXTENDED_INIT_LE, 'isMrCommHdrPartB_Can_'),
#   ('CAN-FD', 'STANDARD'): (mrc.MRC_CAN_FD_STANDARD_INIT_LE, 'isMrCommHdrPartB_CanFd_'),
#   ('CAN-FD', 'EXTENDED'): (mrc.MRC_CAN_FD_EXTENDED_INIT_LE, 'isMrCommHdrPartB_CanFd_')}

# _ISIGNAL_INIT_VAL_BIGEND =\
#  {('CAN',    'STANDARD'): (mrc.MRC_CAN_STANDARD_INIT_BE,    'isMrCommHdrPartB_Can_'),
#   ('CAN',    'EXTENDED'): (mrc.MRC_CAN_EXTENDED_INIT_BE,    'isMrCommHdrPartB_Can_'),
#   ('CAN-20', 'STANDARD'): (mrc.MRC_CAN_20_STANDARD_INIT_BE, 'isMrCommHdrPartB_Can_'),
#   ('CAN-20', 'EXTENDED'): (mrc.MRC_CAN_20_EXTENDED_INIT_BE, 'isMrCommHdrPartB_Can_'),
#   ('CAN-FD', 'STANDARD'): (mrc.MRC_CAN_FD_STANDARD_INIT_BE, 'isMrCommHdrPartB_CanFd_'),
#   ('CAN-FD', 'EXTENDED'): (mrc.MRC_CAN_FD_EXTENDED_INIT_BE, 'isMrCommHdrPartB_CanFd_')}

# Socket connection bundles
_SOCKET_CONNECTION_BUNDLE_ =\
    {'name':          'HixECUxBundle',
     'server_port':  {'name':               'ECUx2Hix',
                      'app_endpoint_name':  'ECUx2Hix_AEP',
                      'network_endpoint':  {'name':     'HixCoreInternal',
                                            'address':  '127.0.0.1',
                                            'source':   'FIXED',
                                            'mask':     '255.255.255.0'},
                      'udp_port':           '1001'},
     'client_port':  {'name':               'HixECUx',
                      'app_endpoint_name':  'HixECUx_AEP',
                      'network_endpoint':  {'name':     'Hix_ECUx_TEST_NE',
                                            'address':  '127.0.0.1',
                                            'source':   'FIXED',
                                            'mask':     '255.255.255.0'},
                      'udp_port':           '1001'},
     'routing_group': 'HixECUx_RoutingGroup'}

# Data sync physical channels mapping
_CHANNEL_MAPPING_ = 'CAN-PHYSICAL-CHANNEL', 'ETHERNET-PHYSICAL-CHANNEL'

NAMESPACE = {'ns': 'http://autosar.org/schema/r4.0'}

### Changes:
# * Replaced index access (`channel[0].text`) with `util.xml_get_child_element_by_tag` call.
# * This provides error handling if a channel is missing a `SHORT-NAME`.
# * Explicitly returns `None` if no matching channel is found
def xml_get_physical_channel(arxml, ch_type, name):
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


### Changes:
# * Replaced `assert` with a call to the new `util.find_ar_package` helper, which provides error handling.
# * Replaced index access (`pdu[0].text`) safer loop that uses `util.xml_get_child_element_by_tag`.
def fetch_pdu(src_arxml):
    """
    Fetches all I-SIGNAL-I-PDU names from the Communication package.
    """
    # Use the helper to find the package. Raises an error if not found.
    src_com = util.xml_ar_package_find(src_arxml.getroot(), 'Communication')
### change    src_com = util.find_ar_package(src_arxml.xml.getroot(), 'Communication')
    
    isig_pdus = util.xml_elem_findall(src_com, 'I-SIGNAL-I-PDU')
    
    pdus = []
    for pdu in isig_pdus:
        # Safely get the name from each PDU
        short_name_el = util.xml_get_child_elem_by_tag(pdu, 'SHORT-NAME')
        if short_name_el is not None and short_name_el.text:
            pdus.append(short_name_el.text)
    return pdus



def copy_communication_packages_old(src_arxml, dst_arxml):
    pass


def copy_fibex_elements(src_arxml, dst_arxml, pdus):
    """
    Copies Communication-related FIBEX elements from a source to a destination
    ARXML file, filtering by package paths and a provided list of PDU names.

    * Changes: removed external dependencies.
    """
    # Find containers and assert their existence
    src_vp = util.xml_ar_package_find(src_arxml.xml.getroot(), 'VehicleProject')
    assert src_vp is not None, "Source VehicleProject package not found!"
    dst_vp = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'VehicleProject')
    assert dst_vp is not None, "Destination VehicleProject package not found!"
    src_fibex_container = util.xml_elem_find(src_vp, 'FIBEX-ELEMENTS')
    assert src_fibex_container is not None, "Source VehicleProject:FIBEX-ELEMENTS not found!"
    dst_fibex_container = util.xml_elem_find(dst_vp, 'FIBEX-ELEMENTS')
    assert dst_fibex_container is not None, "Destination VehicleProject:FIBEX-ELEMENTS not found!"


    # --- 2. Build Filter Criteria ---
    # Create a list of path prefixes for general communication packages.
    comm_path_prefixes = ['/Communication/' + name for name in _COMMUNICATION_PACKAGES_ if name != 'Pdu']
    # Create a set of PDU names for efficient lookup.
    pdu_names_to_match = set(pdus)
    logging.debug(f"FIBEX filter paths: {comm_path_prefixes}")
    logging.debug(f"FIBEX PDU names: {pdu_names_to_match}")

    elements_to_copy = []

    # --- 3. Find and Filter All Potential FIBEX Elements ---
    # Find all direct and conditional references within the source container.
    all_refs = util.xml_elem_findall(src_fibex_container, 'FIBEX-ELEMENT-REF')
    all_cond_refs = util.xml_elem_findall(src_fibex_container, 'FIBEX-ELEMENT-REF-CONDITIONAL')
    
    logging.info(f"Found {len(all_cond_refs)} FIBEX-ELEMENT-REF-CONDITIONALs to check.")

    # Process conditional references first
    for cond_ref in all_cond_refs:
        # The actual reference path is inside the inner FIBEX-ELEMENT-REF
        inner_ref = util.xml_elem_find(cond_ref, 'FIBEX-ELEMENT-REF')
        if inner_ref and inner_ref.text:
            ref_text = inner_ref.text.strip()
            # Check if the path matches any of our filter criteria
            if any(ref_text.startswith(prefix) for prefix in comm_path_prefixes) or \
               any(ref_text.endswith(f'/{pdu_name}') for pdu_name in pdu_names_to_match):
                # If it matches, we copy the entire <FIBEX-ELEMENT-REF-CONDITIONAL> element
                elements_to_copy.append(cond_ref)

    # Process direct references
    for ref in all_refs:
        if ref.text:
            ref_text = ref.text.strip()
            if any(ref_text.startswith(prefix) for prefix in comm_path_prefixes) or \
               any(ref_text.endswith(f'/{pdu_name}') for pdu_name in pdu_names_to_match):
                elements_to_copy.append(ref)

    # --- 4. Copy All Filtered Elements at Once ---
    if elements_to_copy:
        # Using a set to remove potential duplicates before copying
        unique_elements = list({el.attrib.get('UUID', id(el)): el for el in elements_to_copy}.values())
        logging.info(f"Copying {len(unique_elements)} unique, filtered FIBEX elements.")
        
        # FIX: Define a safe name extractor to handle different FIBEX element structures.
        def fibex_name_extractor(elem):
            """Safely extracts the reference path from direct or conditional FIBEX refs."""
            # If the element has children, it's a conditional ref.
            if list(elem):
                inner_ref = util.xml_elem_find(elem, 'FIBEX-ELEMENT-REF')
                return inner_ref.text if inner_ref and inner_ref.text else ''
            # Otherwise, it's a direct ref.
            return elem.text if elem.text else ''

        # Use deepcopy to prevent modifying the source tree during the operation.
        util.xml_elem_extend(
            [copy.deepcopy(el) for el in unique_elements],
            dst_fibex_container,
            src_arxml,
            dst_arxml,
            src_name=fibex_name_extractor,
            dst_name=fibex_name_extractor,
            graceful=True
        )
    else:
        logging.info("No matching FIBEX elements found to copy.")


def copy_isignal_and_pdu_triggerings(src_arxml, dst_arxml, pdus, dst_eth_physical_channel, graceful):
    """
    Copies I-SIGNAL-TRIGGERINGS and PDU-TRIGGERINGS from a source to a destination,
    handling path transformations and filtering in a single function.
    """
    path_map = {}

    # 1. Determine source and destination channels
    is_ethernet = "Eth" in src_arxml.filename
    channel_type = _CHANNEL_MAPPING_[1] if is_ethernet else _CHANNEL_MAPPING_[0]
    src_ch = util.xml_elem_find(src_arxml.xml.getroot(), channel_type)
    assert src_ch is not None, f"Source element {channel_type} not found!"

    dst_ch = xml_get_physical_channel(dst_arxml, 'ETHERNET-PHYSICAL-CHANNEL', dst_eth_physical_channel)
    assert dst_ch is not None, f"Destination ETHERNET-PHYSICAL-CHANNEL '{dst_eth_physical_channel}' not found!"

    # 2. Remove FRAME-TRIGGERINGS from source to simplify logic
    frame_trig = util.xml_elem_find(src_ch, 'FRAME-TRIGGERINGS')
    if frame_trig and src_arxml.parents.get(frame_trig) is not None:
        src_arxml.parents.get(frame_trig).remove(frame_trig)

    # 3. Calculate path transformations for port references
    src_ecu_instance = util.xml_elem_find(src_arxml.xml.getroot(), 'ECU-INSTANCE')
    assert src_ecu_instance is not None, "Source ECU-INSTANCE not found!"
    connector_type = 'ETHERNET-COMMUNICATION-CONNECTOR' if 'ETHERNET' in src_ch.tag else 'CAN-COMMUNICATION-CONNECTOR'
    src_connector = util.xml_elem_find(src_ecu_instance, connector_type)
    assert src_connector is not None, f"Source {connector_type} not found!"
    src_ecpi = util.xml_elem_find(src_connector, 'ECU-COMM-PORT-INSTANCES')
    assert src_ecpi is not None, "Source ECU-COMM-PORT-INSTANCES not found!"
    dst_ecpi = util.xml_elem_find(dst_arxml.xml.getroot(), 'ECU-COMM-PORT-INSTANCES')
    assert dst_ecpi is not None, "Destination element ECU-COMM-PORT-INSTANCES is not found!"
    dst_connector_ref = util.xml_elem_find(dst_ch, 'COMMUNICATION-CONNECTOR-REF')
    assert dst_connector_ref is not None and dst_connector_ref.text, "Destination COMMUNICATION-CONNECTOR-REF not found or is empty!"
    src_port_path = util.xml_elem_get_abs_path(src_ecpi, src_arxml)
    dst_port_path = dst_connector_ref.text

    # 4. Sync I-SIGNAL-TRIGGERINGS
    src_isig_trig = util.xml_elem_find(src_ch, 'I-SIGNAL-TRIGGERINGS')
    assert src_isig_trig is not None, f"Source {src_ch.tag}:I-SIGNAL-TRIGGERINGS not found!"
    dst_isig_trig = util.xml_elem_find(dst_ch, 'I-SIGNAL-TRIGGERINGS')
    if not dst_isig_trig:
        logging.info("Destination I-SIGNAL-TRIGGERINGS not found, creating new one.")
        dst_isig_trig = factory.xml_isignal_triggerings_create()
        util.xml_elem_append(dst_ch, dst_isig_trig, dst_arxml.parents)
    
    # Transform port refs within the source signal triggerings
    refs_to_transform_isig = util.xml_elem_findall(src_isig_trig, 'I-SIGNAL-PORT-REF')
    util.xml_ref_transform_all(refs_to_transform_isig, src_port_path, dst_port_path)
    
    # Extend destination and update path map
    path_map.update(util.xml_elem_extend(
        [copy.deepcopy(el) for el in list(src_isig_trig)],
        dst_isig_trig,
        src_arxml,
        dst_arxml
    ))

    # 5. Sync PDU-TRIGGERINGS
    src_pdu_trig_container = util.xml_elem_find(src_ch, 'PDU-TRIGGERINGS')
    assert src_pdu_trig_container is not None, f"Source {src_ch.tag}:PDU-TRIGGERINGS not found!"
    dst_pdu_trig_container = util.xml_elem_find(dst_ch, 'PDU-TRIGGERINGS')
    if not dst_pdu_trig_container:
        logging.info("Destination PDU-TRIGGERINGS not found, creating new one.")
        dst_pdu_trig_container = factory.xml_pdu_triggerings_create()
        util.xml_elem_append(dst_ch, dst_pdu_trig_container, dst_arxml.parents)

    # Filter source PDU triggerings based on the provided pdus list
    pdus_to_match = set(pdus)
    filtered_src_pdu_trigs = []
    for trig in src_pdu_trig_container:
        short_name_el = util.xml_elem_find(trig, 'SHORT-NAME')
        if short_name_el is not None and any(pdu in short_name_el.text for pdu in pdus_to_match):
            filtered_src_pdu_trigs.append(trig)

    if not filtered_src_pdu_trigs:
        logging.info("No matching PDU-TRIGGERINGS found after filtering.")
    else:
        # Transform I-PDU-PORT-REFs for the filtered triggerings
        for trig in filtered_src_pdu_trigs:
            refs_to_transform_pdu_port = util.xml_elem_findall(trig, 'I-PDU-PORT-REF')
            util.xml_ref_transform_all(refs_to_transform_pdu_port, src_port_path, dst_port_path)
        
        # Transform I-SIGNAL-TRIGGERING-REFs for the filtered triggerings
        src_isig_trig_path = util.xml_elem_get_abs_path(src_isig_trig, src_arxml)
        dst_isig_trig_path = util.xml_elem_get_abs_path(dst_isig_trig, dst_arxml)
        for trig in filtered_src_pdu_trigs:
            refs_to_transform_isig_ref = util.xml_elem_findall(trig, 'I-SIGNAL-TRIGGERING-REF')
            util.xml_ref_transform_all(refs_to_transform_isig_ref, src_isig_trig_path, dst_isig_trig_path)
        
        # Extend destination with filtered triggerings and update path map
        path_map.update(util.xml_elem_extend(
            [copy.deepcopy(el) for el in filtered_src_pdu_trigs],
            dst_pdu_trig_container,
            src_arxml,
            dst_arxml,
            graceful=graceful
        ))

    return path_map


def prepare_ethernet_physical_channel(dst_arxml, dst_eth_physical_channel):
    """
    Ensures that an ETHERNET-PHYSICAL-CHANNEL element has all required
    sub-elements in the correct order as defined by the AUTOSAR schema.

    Note that this function might need some tweaking in case the 
    ETHERNET-PHYSICAL-CHANNEL coming out of Capital Networks has 
    other sub-elements which require specific ordering
    """
    dst_ch = xml_get_physical_channel(dst_arxml,
                                      'ETHERNET-PHYSICAL-CHANNEL',
                                      dst_eth_physical_channel)
    assert dst_ch is not None,\
        "Destination element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"

    # --- 1. Ensure top-level children of the channel are in order ---

    # Define the required order of key elements and their factory functions
    channel_schema = [
        ('COMM-CONNECTORS', None), # This element is expected to exist
        ('I-SIGNAL-TRIGGERINGS', factory.xml_isignal_triggerings_create),
        ('PDU-TRIGGERINGS', factory.xml_pdu_triggerings_create),
        ('NETWORK-ENDPOINTS', None), # This element is also expected to exist
        ('SO-AD-CONFIG', factory.xml_soad_config_create)
    ]

    last_known_element = None
    for tag_name, factory_fn in channel_schema:
        found_element = util.xml_elem_find(dst_ch, tag_name)

        if found_element is None:
            # If the element is missing and has a factory, create and insert it
            if factory_fn:
                logging.info(f"Creating missing element '{tag_name}' in ETHERNET-PHYSICAL-CHANNEL.")
                new_element = factory_fn()
                
                # Find the index of the last known good element to insert after
                try:
                    # The list of children can change, so get a fresh copy
                    children = list(dst_ch)
                    insert_index = children.index(last_known_element) + 1 if last_known_element else 0
                    dst_ch.insert(insert_index, new_element)
                    dst_arxml.parents[new_element] = dst_ch
                    last_known_element = new_element
                except (ValueError, TypeError):
                     # Fallback if the last element is somehow not in the list or is None
                    dst_ch.append(new_element)
                    dst_arxml.parents[new_element] = dst_ch
                    last_known_element = new_element
        else:
            # If the element exists, it becomes the new anchor for subsequent insertions
            last_known_element = found_element
    
    # --- 2. Ensure children of the SO-AD-CONFIG element are in order ---

    dst_soad_config = util.xml_elem_find(dst_ch, 'SO-AD-CONFIG')
    # This assertion is safe because the logic above guarantees it exists.
    assert dst_soad_config is not None, "SO-AD-CONFIG should have been created but was not found."

    # Define the required order for SO-AD-CONFIG children
    soad_schema = [
        ('CONNECTION-BUNDLES', factory.xml_conn_bundles_create),
        ('SOCKET-ADDRESSS', factory.xml_socket_addresss_create) # Note: Misspelled tag is correct
    ]

    last_known_soad_child = None
    for tag_name, factory_fn in soad_schema:
        found_element = util.xml_elem_find(dst_soad_config, tag_name)
        if found_element is None:
            if factory_fn:
                logging.info(f"Creating missing element '{tag_name}' in SO-AD-CONFIG.")
                new_element = factory_fn()
                try:
                    children = list(dst_soad_config)
                    insert_index = children.index(last_known_soad_child) + 1 if last_known_soad_child else 0
                    dst_soad_config.insert(insert_index, new_element)
                    dst_arxml.parents[new_element] = dst_soad_config
                    last_known_soad_child = new_element
                except (ValueError, TypeError):
                    dst_soad_config.append(new_element)
                    dst_arxml.parents[new_element] = dst_soad_config
                    last_known_soad_child = new_element
        else:
            last_known_soad_child = found_element


def copy_network_endpoint(src_arxml, dst_arxml, dst_eth_physical_channel):
    """
    Copies NETWORK-ENDPOINT elements from a source to a destination channel,
    avoiding duplicates based on IPV-4-ADDRESS.

    ASSUMPTIONS:
    * src_arxml contains only two NetworkEndpoints (its own and HIx's)
    * dst_arxml always has at least one NetworkEndpoint (HIx's)
    * each NetworkEndpoint only contains one IPV4Configuration
    """
    # A nested helper function to safely extract the IP address.
    # This keeps the logic self-contained within the main function.
    def _get_ipv4_address(network_endpoint_element):
        """
        Finds and returns the IPV-4-ADDRESS text from a NETWORK-ENDPOINT element.
        Asserts that the address element exists, causing the program to crash if it is missing.
        """
        ipv4_address_el = util.xml_elem_find(network_endpoint_element, 'IPV-4-ADDRESS')
        # FIX: Raise an error if the IPV-4-ADDRESS is missing, as requested.
        assert ipv4_address_el is not None and ipv4_address_el.text is not None, \
            f"NETWORK-ENDPOINT '{network_endpoint_element.findtext('SHORT-NAME', 'N/A')}' is missing a required IPV-4-ADDRESS."
        return ipv4_address_el.text

    # Find source and destination containers, failing fast if not found.
    src_ch = util.xml_elem_find(src_arxml.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL')
    assert src_ch is not None, "Source element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"
    
    dst_ch = xml_get_physical_channel(dst_arxml, 'ETHERNET-PHYSICAL-CHANNEL', dst_eth_physical_channel)
    assert dst_ch is not None, f"Destination element 'ETHERNET-PHYSICAL-CHANNEL': '{dst_eth_physical_channel}' is not found!"

    src_net_ends = util.xml_elem_find(src_ch, 'NETWORK-ENDPOINTS')
    assert src_net_ends is not None, "Source element 'NETWORK-ENDPOINTS' is not found!"
    
    dst_net_ends = util.xml_elem_find(dst_ch, 'NETWORK-ENDPOINTS')
    assert dst_net_ends is not None, "Destination element 'NETWORK-ENDPOINTS' is not found!"

    # Find all direct NETWORK-ENDPOINT children in the source.
    # Replaces is_nested_network_endpoint(element)
    source_endpoints_to_copy = util.xml_elem_findall(src_net_ends, 'NETWORK-ENDPOINT')

    ### for testing. remove later
    if not source_endpoints_to_copy:
        logging.info("No NETWORK-ENDPOINT elements found in the source to copy.")
        return {}

    ### for testing. remove later
    logging.info(f"Found {len(source_endpoints_to_copy)} source network endpoints. Checking for duplicates before copying.")
    
    # Use deepcopy to prevent modifying the source tree.
    path_map = util.xml_elem_extend(
        [copy.deepcopy(el) for el in source_endpoints_to_copy],
        dst_net_ends,
        src_arxml,
        dst_arxml,
        src_name=_get_ipv4_address,
        dst_name=_get_ipv4_address,
        graceful=True
    )

    return path_map


def copy_socket_connection_bundles(src_arxml, dst_arxml):
	pass


def copy_socket_addresses(src_arxml, dst_arxml):
	pass


def create_socket_connection_bundle(bundle, src_arxml, dst_arxml):
	pass


def add_mr_com_flavour(dst_arxml, can_frames, can_pdus):
	pass


def fix_ihfa_ihra_naming(src_arxml):
	pass


def add_swbasetype_arpackage(swc_dp_arxmls,dst_arxml):
	pass


def copy_ecpi_to_ethernet_connectors(dst_arxml):
	pass


def add_transfer_property_to_signals(dst_arxml):
	pass


def update_reference(ref):
	pass


def copy_and_append_data_mappings(src_arxml, dest_arxml):
	pass
