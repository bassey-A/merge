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

    Args:
        arxml (ArxmlFile): The ARXML file wrapper object to search within.
        ch_type (str): The tag name of the channel type to find 
                       (e.g., 'ETHERNET-PHYSICAL-CHANNEL').
        name (str): The text value of the <SHORT-NAME> tag to match.

    Returns:
        xml.etree.ElementTree.Element: The found channel element, or None if no
        match is found
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

    Args:
        src_arxml (ArxmlFile): The source ARXML file wrapper object.

    Returns:
        list[str]: A list of all found I-SIGNAL-I-PDU short names.

    """
    src_com = util.xml_ar_package_find(src_arxml.xml.getroot(), 'Communication')
    
    isig_pdus = util.xml_elem_findall(src_com, 'I-SIGNAL-I-PDU')
    
    pdus = []
    for pdu in isig_pdus:
        # Safely get the name from each PDU
        short_name_el = util.xml_get_child_elem_by_tag(pdu, 'SHORT-NAME')
        if short_name_el is not None and short_name_el.text:
            pdus.append(short_name_el.text)
    return pdus


def copy_communication_packages(src_arxml, dst_arxml):
    """
    Merges communication-related packages from a source to a destination ARXML.
    This function copies packages enlisted in _COMMUNICATION_PACKAGES_ from the 'Communication'
    AR-PACKAGE of the source ARXML to the destination.
    It explicitly logs name clashes for 'Pdu' packages and validates PDU versus frame lengths.

    Args:
        src_arxml (ArxmlFile): Source ARXML wrapper object.
        dst_arxml (ArxmlFile): Destination ARXML wrapper object.

    Returns:
        list: List of I-SIGNAL-I-PDU short-names found during copy (mainly from 'Pdu' package).

    Raises:
        AssertionError: if required packages or elements are not found.
    """
    src_com = util.xml_ar_package_find(src_arxml.xml.getroot(), 'Communication')
    assert src_com is not None, "Source Communication package is not found!"
    dst_com = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'Communication')
    assert dst_com is not None, "Destination Communication package is not found!"
    pdus = []
    for name in _COMMUNICATION_PACKAGES_:
        src = util.xml_ar_package_find(src_com, name)
        dst = util.xml_ar_package_find(dst_com, name)
        if src is None:
            logging.warning("Missing source package Communication/%s", name)
            continue
        if dst is None:
            dst = factory.xml_ar_package_create(name, str(uuid.uuid4()) +
                                        '-Communication-' + name)
            util.assert_elem_tag(dst_com[1], 'AR-PACKAGES')
            util.xml_elem_append(dst_com[1], dst, dst_arxml.parents)
        if name == 'Pdu':
            isig_pdus = util.xml_elem_findall(src_com, 'I-SIGNAL-I-PDU')
            util.assert_elem_tag(dst[1], 'ELEMENTS')
            util.xml_elem_extend(isig_pdus, dst[1], src_arxml, dst_arxml)
            pdus = [pdu[0].text for pdu in isig_pdus if pdu[0] is not None]
            isig_pdus_len = [(util.xml_elem_find(pdu, "LENGTH").text, pdu[0].text) for pdu in isig_pdus if pdu[0] is not None and util.xml_elem_find(pdu, "LENGTH") is not None]
            isig_pdus_len = sorted(isig_pdus_len, key=lambda x: x[1])
            frames = util.xml_elem_findall(src_com, 'CAN-FRAME')
            if frames is not None:
                frame_len = [(util.xml_elem_find(frame, "FRAME-LENGTH").text,
                              util.xml_elem_find(frame, "PDU-REF").text.split("/")[-1]) \
                             for frame in frames if util.xml_elem_find(frame, "FRAME-LENGTH") is not None and util.xml_elem_find(frame, "PDU-REF") is not None]
                frame_len = sorted(frame_len, key=lambda x: x[1])
                if len(frame_len) > 0 and len(isig_pdus_len) > 0:
                    for i, pdu_cfg in enumerate(isig_pdus_len):
                        if i < len(frame_len) and frame_len[i] != pdu_cfg:
                            logging.warning("Found a mismatch: in PDU: %s, frame length: %s, PDU length: %s",\
                                pdu_cfg[1], frame_len[i][0], pdu_cfg[0])
                            break
            continue
        util.assert_elem_tag(src[1], 'ELEMENTS')
        util.assert_elem_tag(dst[1], 'ELEMENTS')
        util.xml_elem_extend(src[1], dst[1], src_arxml, dst_arxml)
    return pdus


def copy_fibex_elements(src_arxml, dst_arxml, pdus):
    """
    Copies Communication-related FIBEX elements from a source to a destination
    ARXML file, filtering by package paths and a provided list of PDU names.
    It finds all <FIBEX-ELEMENT-REF> and <FIBEX-ELEMENT-REF-CONDITIONAL> elements 
    within the source's 'VehicleProject/FIBEX-ELEMENTS' container and  copies only 
    those references whose paths match either a standard communication package 
    path or one of the PDU names provided in the `pdus` list.

    Args:
        src_arxml (ArxmlFile): The source ARXML file wrapper object.
        dst_arxml (ArxmlFile): The destination ARXML file wrapper object.
        pdus (list[str]): A list of PDU short names to use for filtering.

    Side Effects:
        - Modifies the `dst_arxml` object by adding the filtered FIBEX elements.

    Raises:
        AssertionError: If the 'VehicleProject' or 'FIBEX-ELEMENTS' containers
                        are not found in either the source or destination.

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

    This function performs two main operations:
    1.  Copies all <I-SIGNAL-TRIGGERING> elements from the source channel to
        the destination channel, transforming their internal <I-SIGNAL-PORT-REF>
        paths to be valid in the destination context.
    2.  Filters the <PDU-TRIGGERING> elements in the source channel based on the
        `pdus` list, transforms their internal references, and copies the 
        filtered results to the destination.

    Args:
        src_arxml (ArxmlFile): The source ARXML file wrapper object.
        dst_arxml (ArxmlFile): The destination ARXML file wrapper object.
        pdus (list[str]): A list of PDU short names to filter PDU-TRIGGERINGS.
        dst_eth_physical_channel (str): The short name of the destination 
                                        ETHERNET-PHYSICAL-CHANNEL.
        graceful (bool): If True, name clashes during the copy are ignored. 
                         If False, they may cause an error depending on the
                         implementation of `util.xml_elem_extend`.

    Returns:
        dict: A mapping of old (source) element paths to their new (destination)
              paths for all copied elements.

    Side Effects:
        - Modifies the `dst_arxml` object by adding new triggering elements.
        - Modifies the `src_arxml` object by transforming reference paths
          within its elements before they are copied.
        - Modifies the `src_arxml` object by removing the <FRAME-TRIGGERINGS>
          container from the source channel.
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
    other sub-elements which require specific ordering.

    Args:
        dst_arxml (ArxmlFile): The destination ARXML file wrapper to be modified.
        dst_eth_physical_channel (str): The short name of the channel to prepare.

    Side Effects:
        - Modifies the `dst_arxml` object by inserting missing elements into the
          specified channel to enforce a correct schema order.

    Raises:
        AssertionError: If the specified ETHERNET-PHYSICAL-CHANNEL is not found.
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

    This function finds all <NETWORK-ENDPOINT> elements in the source Ethernet
    channel and copies them to the destination channel, avoiding duplicates.
    Duplicates are identified by comparing the text of the <IPV-4-ADDRESS> tag.

    Args:
        src_arxml (ArxmlFile): The source ARXML file wrapper object.
        dst_arxml (ArxmlFile): The destination ARXML file wrapper object.
        dst_eth_physical_channel (str): The short name of the destination channel.

    Returns:
        dict: A path map of the old source paths to the new destination paths
              for the elements that were successfully copied.

    Side Effects:
        - Modifies the `dst_arxml` object by adding new NETWORK-ENDPOINT elements.

    Raises:
        AssertionError: If the source or destination channels or their
                        NETWORK-ENDPOINTS containers are not found.
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


def copy_socket_connection_bundles(src_arxml, dst_arxml,
                                   dst_eth_physical_channel,
                                   sock_addr_map, isig_pdu_path_map):
    """
    Copies SocketConnectionBundles to a destination channel, safely updating
    all necessary references and failing fast if data is inconsistent.
    
    WARNING: This function modifies the `src_arxml` object in place by
    updating reference paths before copying the elements.

    The function iterates through all <SOCKET-CONNECTION-BUNDLE> elements in the
    source channel, transforms their internal references using the provided
    path maps, and then copies the modified elements to the destination channel.

    Args:
        src_arxml (ArxmlFile): The source ARXML file wrapper. It is MODIFIED IN PLACE.
        dst_arxml (ArxmlFile): The destination ARXML file wrapper.
        dst_eth_physical_channel (str): The short name of the destination channel.
        sock_addr_map (dict): A map of old socket address paths to new paths.
        isig_pdu_path_map (dict): A map of old PDU triggering paths to new paths.

    Side Effects:
        - Modifies `src_arxml` by rewriting reference paths.
        - Modifies `dst_arxml` by adding the transformed bundles.

    Raises:
        AssertionError: If required elements are missing or if a path in a
                        reference is not found as a key in the provided maps.
    """
    # Get source and destination containers, asserting their existence.
    src_ch = util.xml_elem_find(src_arxml.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL')
    assert src_ch is not None, "Source element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"
    dst_ch = xml_get_physical_channel(dst_arxml, 'ETHERNET-PHYSICAL-CHANNEL', dst_eth_physical_channel)
    assert dst_ch is not None, f"Destination element 'ETHERNET-PHYSICAL-CHANNEL' named '{dst_eth_physical_channel}' is not found!"

    # Get Socket Connection
    src_sock_conn_bundles = util.xml_elem_find(src_ch, 'CONNECTION-BUNDLES')
    assert src_sock_conn_bundles is not None, "Source element 'CONNECTION-BUNDLES' is not found!"
    
    dst_sock_conn_bundles = util.xml_elem_find(dst_ch, 'CONNECTION-BUNDLES')
    assert dst_sock_conn_bundles is not None, "Destination element 'CONNECTION-BUNDLES' is not found!"

    # Loop through the bundles and transform their internal references.
    for bundle in src_sock_conn_bundles:
        # --- Update CLIENT-PORT-REF ---
        client_port_ref = util.xml_elem_find(bundle, 'CLIENT-PORT-REF')
        assert client_port_ref is not None, f"Bundle '{bundle.findtext('SHORT-NAME')}' is missing CLIENT-PORT-REF"
        assert client_port_ref.text in sock_addr_map, \
            f"Path '{client_port_ref.text}' not found in the provided sock_addr_map."
        client_port_ref.text = sock_addr_map[client_port_ref.text]

        # --- Update SERVER-PORT-REF ---
        server_port_ref = util.xml_elem_find(bundle, 'SERVER-PORT-REF')
        assert server_port_ref is not None, f"Bundle '{bundle.findtext('SHORT-NAME')}' is missing SERVER-PORT-REF"
        assert server_port_ref.text in sock_addr_map, \
            f"Path '{server_port_ref.text}' not found in the provided sock_addr_map."
        server_port_ref.text = sock_addr_map[server_port_ref.text]

        # --- Update all PDU-TRIGGERING-REFs ---
        pdu_trig_refs = util.xml_elem_findall(bundle, 'PDU-TRIGGERING-REF')
        for pdu_trig_ref in pdu_trig_refs:
            assert pdu_trig_ref.text in isig_pdu_path_map, \
                f"Path '{pdu_trig_ref.text}' not found in the provided isig_pdu_path_map."
            pdu_trig_ref.text = isig_pdu_path_map[pdu_trig_ref.text]

    # Extend the destination with the elements.
    util.xml_elem_extend(
        src_sock_conn_bundles,
        dst_sock_conn_bundles,
        src_arxml,
        dst_arxml,
        src_name=lambda el: util.xml_elem_find(el, 'HEADER-ID').text,
        dst_name=lambda el: util.xml_elem_find(el, 'SHORT-NAME').text
    )


def copy_socket_addresses(src_arxml, dst_arxml,
                          dst_eth_physical_channel,
                          net_ends_path_map):
    """
    Copies Ethernet DP's SocketAddresses to a destination channel, safely updating all necessary
    references and failing fast if data is inconsistent.

    ASSUMPTIONS
    * EthernetPhysicalChannels only contain one COMMUNICATION-CONNECTOR-REF
    """
    # Find source and destination containers, asserting their existence.
    src_ch = util.xml_elem_find(src_arxml.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL')
    assert src_ch is not None, "Source element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"

    dst_ch = util.xml_elem_type_find(dst_arxml.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL', dst_eth_physical_channel)
    assert dst_ch is not None, f"Destination element 'ETHERNET-PHYSICAL-CHANNEL' named '{dst_eth_physical_channel}' is not found!"

    src_sock_addrs_container = util.xml_elem_find(src_ch, 'SOCKET-ADDRESSS')
    assert src_sock_addrs_container is not None, "Source element 'SOCKET-ADDRESSS' is not found!"

    dst_sock_addrs_container = util.xml_elem_find(dst_ch, 'SOCKET-ADDRESSS')
    assert dst_sock_addrs_container is not None, "Destination element 'SOCKET-ADDRESSS' is not found!"

    # Get the destination connector reference, which will be used for transformations.
    comm_connector_ref_el = util.xml_elem_find(dst_ch, 'COMMUNICATION-CONNECTOR-REF')
    assert comm_connector_ref_el is not None and comm_connector_ref_el.text is not None, \
        "Destination channel is missing a valid COMMUNICATION-CONNECTOR-REF."
    comm_connector_ref_text = comm_connector_ref_el.text

    # Get a list of the source elements to be processed.
    source_socket_addresses = util.xml_elem_findall(src_sock_addrs_container, 'SOCKET-ADDRESS')
    
    # Loop through the ORIGINAL source addresses and transform their internal references.
    # NOTE: This modifies the source tree in place.
    for sock_addr in source_socket_addresses:
        # --- Update NETWORK-ENDPOINT-REF ---
        net_end_ref = util.xml_elem_find(sock_addr, 'NETWORK-ENDPOINT-REF')
        assert net_end_ref is not None, f"Socket Address '{util.xml_elem_find(sock_addr, 'SHORT-NAME').text}' is missing NETWORK-ENDPOINT-REF."
        assert net_end_ref.text in net_ends_path_map, f"Path '{net_end_ref.text}' not found in the provided net_ends_path_map."
        net_end_ref.text = net_ends_path_map[net_end_ref.text]

        # --- Update MULTICAST-CONNECTOR-REF (if it exists) ---
        multicast_ref = util.xml_elem_find(sock_addr, 'MULTICAST-CONNECTOR-REF')
        if multicast_ref is not None:
            multicast_ref.text = comm_connector_ref_text

        # --- Update CONNECTOR-REF (if it exists) ---
        connector_ref = util.xml_elem_find(sock_addr, 'CONNECTOR-REF')
        if connector_ref is not None:
            connector_ref.text = comm_connector_ref_text

    # Extend the destination with the modified source elements.
    path_map = util.xml_elem_extend(
        source_socket_addresses,
        dst_sock_addrs_container,
        src_arxml,
        dst_arxml,
        src_name=lambda el: util.xml_elem_find(el, 'PORT-NUMBER').text,
        dst_name=lambda el: util.xml_elem_find(el, 'SHORT-NAME').text
    )

    return path_map

### Incomplete
def create_socket_connection_bundle(bundle_data, src_arxml, dst_arxml,
                                    frames, pdus, dst_eth_physical_channel):
    """
    Creates various socket adapter elements and a SOCKET-CONNECTION-BUNDLE.
    
    """
    # Self-Contained Helper Functions
    def _get_or_create_ar_package(parent_pkg, pkg_name, arxml_parents):
        """Finds or creates a generic AR-PACKAGE within a parent's AR-PACKAGES container."""
        pkg = util.xml_ar_package_find(parent_pkg, pkg_name)
        if pkg is None:
            logging.info(f"Creating missing AR-PACKAGE: {pkg_name}")
            container = parent_pkg[1] # Assumes container is the second child
            util.assert_elem_tag(container, 'AR-PACKAGES')
            pkg = factory.xml_ar_package_create(pkg_name, str(uuid.uuid4()) +
                                                '-Communication-' + pkg_name)
            util.xml_elem_append(container, pkg, arxml_parents)
        return pkg

    def _get_or_create_network_endpoint(dst_net_ends_container, endpoint_data, name_transformer):
        """Finds an existing NETWORK-ENDPOINT or creates a new one."""
        endpoint_name = name_transformer(endpoint_data['name'])
        net_end = util.xml_elem_type_find(dst_net_ends_container, 'NETWORK-ENDPOINT', endpoint_name)
        if net_end is None:
            logging.info(f"Creating missing NETWORK-ENDPOINT: {endpoint_name}")
            net_end = factory.xml_network_endpoint_ipv4_create(
                endpoint_name,
                endpoint_data['address'],
                endpoint_data['source'],
                endpoint_data['mask']
            )
            util.xml_elem_append(dst_net_ends_container, net_end, dst_arxml.parents)
        return net_end

    # Main Function Logic

    # Setup and Name Transformation
    ecu_dst = util.xml_ecu_sys_name_get(dst_arxml)
    ecu_src = util.xml_ecu_sys_name_get(src_arxml)
    name_transformer = lambda s: s.replace('Hix', ecu_dst).replace('ECUx', ecu_src)

    dst_com = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'Communication')
    assert dst_com is not None, "Destination Communication package is not found!"

    # Create SoAd Routing Group
    dst_rgroups_pkg = _get_or_create_ar_package(dst_com, 'SoAdRoutingGroup', dst_arxml.parents)
    rgroup = factory.xml_soad_routing_group_create(name_transformer(bundle_data['routing_group']))
    elements_container = util.xml_elem_find_assert_exists(dst_rgroups_pkg, 'ELEMENTS')
    util.xml_elem_append(elements_container, rgroup, dst_arxml.parents)
    rgroup_path = util.xml_elem_get_abs_path(rgroup, dst_arxml)

    # Get Destination Channel and Containers
    dst_ch = util.xml_elem_type_find(dst_arxml.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL', dst_eth_physical_channel)
    assert dst_ch is not None, f"Destination ETHERNET-PHYSICAL-CHANNEL '{dst_eth_physical_channel}' is not found!"
    dst_net_ends = util.xml_elem_find_assert_exists(dst_ch, 'NETWORK-ENDPOINTS')
    dst_soads = util.xml_elem_find_assert_exists(dst_ch, 'SOCKET-ADDRESSS')
    
    # Create Server and Client Network Endpoints and Socket Addresses
    # The original function's lookup for always failed this assertion, will investigate fyrther
    # The correct reference path is the COMMUNICATION-CONNECTOR-REF from the destination channel.
    connector_ref = util.xml_elem_find_assert_exists(dst_ch, 'COMMUNICATION-CONNECTOR-REF')
    connector_ref_path = connector_ref.text
    assert connector_ref_path is not None, "Destination channel is missing COMMUNICATION-CONNECTOR-REF text."

    # Server Port
    server_port_data = bundle_data['server_port']
    server_net_end = _get_or_create_network_endpoint(dst_net_ends, server_port_data['network_endpoint'], name_transformer)
    server_net_end_path = util.xml_elem_get_abs_path(server_net_end, dst_arxml)
    server_sock_addr = factory.xml_socket_address_udp_create(
        name_transformer(server_port_data['name']),
        name_transformer(server_port_data['app_endpoint_name']),
        server_net_end_path,
        server_port_data['udp_port'],
        connector_ref_path
    )
    util.xml_elem_append(dst_soads, server_sock_addr, dst_arxml.parents)
    server_ref = util.xml_elem_get_abs_path(server_sock_addr, dst_arxml)

    # Client Port
    client_port_data = bundle_data['client_port']
    client_net_end = _get_or_create_network_endpoint(dst_net_ends, client_port_data['network_endpoint'], name_transformer)
    client_net_end_path = util.xml_elem_get_abs_path(client_net_end, dst_arxml)
    client_sock_addr = factory.xml_socket_address_udp_create(
        name_transformer(client_port_data['name']),
        name_transformer(client_port_data['app_endpoint_name']),
        client_net_end_path,
        client_port_data['udp_port'],
        connector_ref_path
    )
    util.xml_elem_append(dst_soads, client_sock_addr, dst_arxml.parents)
    client_ref = util.xml_elem_get_abs_path(client_sock_addr, dst_arxml)

    # Create Socket Connection IPDU Identifiers
    dst_pdu_trigs_container = util.xml_elem_find_assert_exists(dst_ch, 'PDU-TRIGGERINGS')
    pdus_to_match = set(pdus)
    filtered_dst_trigs = [
        trig for trig in dst_pdu_trigs_container
        if util.xml_elem_find(trig, 'SHORT-NAME') is not None and any(pdu in util.xml_elem_find(trig, 'SHORT-NAME').text for pdu in pdus_to_match)
    ]
    
    ipdus = []
    for trig in filtered_dst_trigs:
        short_name_el = util.xml_elem_find(trig, 'SHORT-NAME')
        assert short_name_el is not None, "PDU-TRIGGERING is missing SHORT-NAME"
        
        pdu_name = short_name_el.text.replace('PduTr', '')
        frame_data = frames.get(pdu_name)
        assert frame_data is not None, f"The PDU-TRIGGERING '{short_name_el.text}' cannot be matched to a frame!"

        ipdu_port_refs_container = util.xml_elem_find_assert_exists(trig, 'I-PDU-PORT-REFS')
        assert len(ipdu_port_refs_container) == 1, f"Invalid number of I-PDU-PORT-REFs in PDU-TRIGGERING: {short_name_el.text}"
        
        ipdu_port_ref_text = ipdu_port_refs_container[0].text
        trig_path = util.xml_elem_get_abs_path(trig, dst_arxml)

        ipdu = factory.xml_socket_connection_ipdu_id_create(
            frame_data['id'],
            ipdu_port_ref_text,
            trig_path,
            rgroup_path
        )
        ipdus.append(ipdu)

    # Create and Finalize the Socket Connection Bundle
    new_bundle = factory.xml_socket_connection_bundle_create(name_transformer(bundle_data['name']), client_ref, server_ref)
    bpdus = util.xml_elem_find_assert_exists(new_bundle, 'PDUS')
    for ipdu in ipdus:
        bpdus.append(ipdu)

    dst_bundles = util.xml_elem_find_assert_exists(dst_ch, 'CONNECTION-BUNDLES')
    util.xml_elem_append(dst_bundles, new_bundle, dst_arxml.parents)


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
