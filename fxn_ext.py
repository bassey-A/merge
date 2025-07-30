import logging
import uuid
import xml.etree.ElementTree as ET
import copy

# Assuming util.py and factory.py are available
import util
import factory
import HIA_Com_merger_ref as har
import common_fxn as cf

# --- Constants for Testing ---
_COMMUNICATION_PACKAGES_ = ('Pdu', 'ISignal', 'ISignalGroup', 'ISignalPduGroup')
_CHANNEL_MAPPING_ = ('CAN-PHYSICAL-CHANNEL', 'ETHERNET-PHYSICAL-CHANNEL')

# --- Helper Class for Testing ---
class ArxmlFile:
    """A simple wrapper to hold the XML tree and parent map for testing."""
    def __init__(self, tree):
        self.xml = tree
        self.parents = {}
        self.filename = "test.arxml"

# --- New Generic Helper Function ---
def _get_or_create_container(parent_element, tag_name, factory_function, arxml_parents):
    """
    Finds a child element by tag name. If not found, creates it using the
    factory function, appends it, and updates the parent map.
    """
    container = util.xml_elem_find(parent_element, tag_name)
    if container is None:
        logging.info(f"Creating missing container '{tag_name}' in '{parent_element.tag}'.")
        container = factory_function()
        util.xml_elem_append(parent_element, container, arxml_parents)
    return container

# --- Updated Functions with Integrated Helper ---

def copy_communication_packages(src_arxml, dst_arxml):
    """
    Merges communication-related packages from a source to a destination ARXML.
    ### CHANGES
    * Replaced index-based access with name-based lookups using util.xml_elem_find
        and util.xml_elem_find_assert_exists
    * PDU/Frame Validation now checks if elements are found before trying to access
        their text
    """
    src_com = util.xml_ar_package_find(src_arxml.xml.getroot(), 'Communication')
    assert src_com is not None, "Source Communication package is not found!"
    dst_com = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'Communication')
    assert dst_com is not None, "Destination Communication package is not found!"

    pdus = []
    for pkg_name in _COMMUNICATION_PACKAGES_:
        src_pkg = util.xml_ar_package_find(src_com, pkg_name)
        if src_pkg is None:
            logging.warning(f"Missing source package Communication/{pkg_name}")
            continue

        # Find the destination package using the correct function
        dst_pkg = util.xml_ar_package_find(dst_com, pkg_name)
        if dst_pkg is None:
            # If it's missing, create it 
            dst_pkg = factory.xml_ar_package_create(
                pkg_name, f"{uuid.uuid4()}-Communication-{pkg_name}"
            )
            dst_pkg_container = util.xml_elem_find_assert_exists(dst_com, 'AR-PACKAGES')
            util.xml_elem_append(dst_pkg_container, dst_pkg, dst_arxml.parents)
        
        if pkg_name == 'Pdu':
            isig_pdus = util.xml_elem_findall(src_com, 'I-SIGNAL-I-PDU')
            # Use safe, name-based find instead of index dst[1]
            dst_elements = util.xml_elem_find_assert_exists(dst_pkg, 'ELEMENTS')

            util.xml_elem_extend(isig_pdus, dst_elements, src_arxml, dst_arxml)
            pdus = [pdu[0].text for pdu in isig_pdus if pdu[0] is not None]

            # --- Reinstated PDU/Frame Length Validation Logic (safer version) ---
            isig_pdus_len = []
            for pdu in isig_pdus:
                name_el = util.xml_elem_find(pdu, "SHORT-NAME")
                len_el = util.xml_elem_find(pdu, "LENGTH")
                if name_el is not None and len_el is not None:
                    isig_pdus_len.append((len_el.text, name_el.text))
            isig_pdus_len.sort(key=lambda x: x[1])

            frames = util.xml_elem_findall(src_com, 'CAN-FRAME')
            if frames:
                frame_len = []
                for frame in frames:
                    len_el = util.xml_elem_find(frame, "FRAME-LENGTH")
                    ref_el = util.xml_elem_find(frame, "PDU-REF")
                    if len_el is not None and ref_el is not None and ref_el.text:
                        frame_len.append((len_el.text, ref_el.text.split("/")[-1]))
                frame_len.sort(key=lambda x: x[1])

                if len(frame_len) > 0 and len(isig_pdus_len) > 0:
                    for i, pdu_cfg in enumerate(isig_pdus_len):
                        if i < len(frame_len) and frame_len[i] != pdu_cfg:
                            logging.warning("Found a mismatch: in PDU: %s, frame length: %s, PDU length: %s",
                                            pdu_cfg[1], frame_len[i][0], pdu_cfg[0])
                            break
            continue
        
        src_elements = util.xml_elem_find_assert_exists(src_pkg, 'ELEMENTS')
        dst_elements = util.xml_elem_find_assert_exists(dst_pkg, 'ELEMENTS')

        util.xml_elem_extend(src_elements, dst_elements, src_arxml, dst_arxml)
            
    return pdus


def copy_isignal_and_pdu_triggerings(src_arxml, dst_arxml, pdus, dst_eth_physical_channel, graceful):
    """
    Copies, filters, and transforms I-SIGNAL and PDU triggerings.
    """
    path_map = {}
    is_ethernet = "Eth" in src_arxml.filename
    channel_type = _CHANNEL_MAPPING_[1] if is_ethernet else _CHANNEL_MAPPING_[0]
    src_ch = util.xml_elem_find(src_arxml.xml.getroot(), channel_type)
    assert src_ch is not None, f"Source element {channel_type} not found!"

    dst_ch = util.xml_elem_type_find(dst_arxml.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL', dst_eth_physical_channel)
    assert dst_ch is not None, f"Destination ETHERNET-PHYSICAL-CHANNEL '{dst_eth_physical_channel}' not found!"

    # ... (path transformation logic remains the same)
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

    # Sync I-SIGNAL-TRIGGERINGS using the helper
    src_isig_trig = util.xml_elem_find_assert_exists(src_ch, 'I-SIGNAL-TRIGGERINGS')
    dst_isig_trig = _get_or_create_container(dst_ch, 'I-SIGNAL-TRIGGERINGS', factory.xml_isignal_triggerings_create, dst_arxml.parents)
    
    refs_to_transform_isig = util.xml_elem_findall(src_isig_trig, 'I-SIGNAL-PORT-REF')
    util.xml_ref_transform_all(refs_to_transform_isig, src_port_path, dst_port_path)
    path_map.update(util.xml_elem_extend([copy.deepcopy(el) for el in list(src_isig_trig)], dst_isig_trig, src_arxml, dst_arxml))

    # Sync PDU-TRIGGERINGS using the helper
    src_pdu_trig_container = util.xml_elem_find_assert_exists(src_ch, 'PDU-TRIGGERINGS')
    dst_pdu_trig_container = _get_or_create_container(dst_ch, 'PDU-TRIGGERINGS', factory.xml_pdu_triggerings_create, dst_arxml.parents)
    
    # ... (rest of the PDU triggering logic remains the same)
    pdus_to_match = set(pdus)
    filtered_src_pdu_trigs = [trig for trig in src_pdu_trig_container if util.xml_elem_find(trig, 'SHORT-NAME') is not None and any(p in util.xml_elem_find(trig, 'SHORT-NAME').text for p in pdus_to_match)]
    if filtered_src_pdu_trigs:
        for trig in filtered_src_pdu_trigs:
            refs = util.xml_elem_findall(trig, 'I-PDU-PORT-REF')
            util.xml_ref_transform_all(refs, src_port_path, dst_port_path)
        
        src_isig_trig_path = util.xml_elem_get_abs_path(src_isig_trig, src_arxml)
        dst_isig_trig_path = util.xml_elem_get_abs_path(dst_isig_trig, dst_arxml)
        for trig in filtered_src_pdu_trigs:
            refs = util.xml_elem_findall(trig, 'I-SIGNAL-TRIGGERING-REF')
            util.xml_ref_transform_all(refs, src_isig_trig_path, dst_isig_trig_path)
        
        path_map.update(util.xml_elem_extend([copy.deepcopy(el) for el in filtered_src_pdu_trigs], dst_pdu_trig_container, src_arxml, dst_arxml, graceful=graceful))

    return path_map


def prepare_ethernet_physical_channel(dst_arxml, dst_eth_physical_channel):
    """
    This function is NOT modified to use the helper because its primary
    purpose is to insert elements in a specific schema order, which the
    simple 'append' logic of the helper would violate.
    """
    dst_ch = util.xml_elem_type_find(dst_arxml.xml.getroot(),'ETHERNET-PHYSICAL-CHANNEL', dst_eth_physical_channel)
    assert dst_ch is not None, "Destination element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"

    # ... (original, order-dependent logic is preserved)
    channel_schema = [
        ('COMM-CONNECTORS', None), 
        ('I-SIGNAL-TRIGGERINGS', factory.xml_isignal_triggerings_create),
        ('PDU-TRIGGERINGS', factory.xml_pdu_triggerings_create),
        ('NETWORK-ENDPOINTS', None),
        ('SO-AD-CONFIG', factory.xml_soad_config_create)
    ]
    last_known_element = None
    for tag_name, factory_fn in channel_schema:
        found_element = util.xml_elem_find(dst_ch, tag_name)
        if found_element is None:
            if factory_fn:
                new_element = factory_fn()
                try:
                    children = list(dst_ch)
                    insert_index = children.index(last_known_element) + 1 if last_known_element else 0
                    dst_ch.insert(insert_index, new_element)
                    dst_arxml.parents[new_element] = dst_ch
                    last_known_element = new_element
                except (ValueError, TypeError):
                    dst_ch.append(new_element)
                    dst_arxml.parents[new_element] = dst_ch
                    last_known_element = new_element
        else:
            last_known_element = found_element
    
    dst_soad_config = util.xml_elem_find_assert_exists(dst_ch, 'SO-AD-CONFIG')
    soad_schema = [
        ('CONNECTION-BUNDLES', factory.xml_conn_bundles_create),
        ('SOCKET-ADDRESSS', factory.xml_socket_addresss_create)
    ]
    last_known_soad_child = None
    for tag_name, factory_fn in soad_schema:
        found_element = util.xml_elem_find(dst_soad_config, tag_name)
        if found_element is None:
            if factory_fn:
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


def create_socket_connection_bundle(bundle_data, src_arxml, dst_arxml,
                                    frames, pdus, dst_eth_physical_channel):
    """
    Creates a full set of socket connection elements from a configuration.
    """
    ecu_dst = util.xml_ecu_sys_name_get(dst_arxml)
    ecu_src = util.xml_ecu_sys_name_get(src_arxml)
    name_transformer = lambda s: s.replace('Hix', ecu_dst).replace('ECUx', ecu_src)

    dst_com = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'Communication')
    assert dst_com is not None, "Destination Communication package is not found!"

    # Use the helper to create the SoAdRoutingGroup package
    factory_fn = lambda: factory.xml_ar_package_create(
        'SoAdRoutingGroup', f"{uuid.uuid4()}-Communication-SoAdRoutingGroup"
    )
    dst_rgroups_pkg = _get_or_create_container(util.xml_elem_find_assert_exists(dst_com, 'AR-PACKAGES'), 'SoAdRoutingGroup', factory_fn, dst_arxml.parents)

    # ... (rest of the function logic remains the same)
    rgroup = factory.xml_soad_routing_group_create(name_transformer(bundle_data['routing_group']))
    elements_container = util.xml_elem_find_assert_exists(dst_rgroups_pkg, 'ELEMENTS')
    util.xml_elem_append(elements_container, rgroup, dst_arxml.parents)
    rgroup_path = util.xml_elem_get_abs_path(rgroup, dst_arxml)
    dst_ch = util.xml_elem_type_find(dst_arxml.xml.getroot(), 'ETHERNET-PHYSICAL-CHANNEL', dst_eth_physical_channel)
    assert dst_ch is not None, f"Destination ETHERNET-PHYSICAL-CHANNEL '{dst_eth_physical_channel}' is not found!"
    dst_net_ends = util.xml_elem_find_assert_exists(dst_ch, 'NETWORK-ENDPOINTS')
    dst_soads = util.xml_elem_find_assert_exists(dst_ch, 'SOCKET-ADDRESSS')
    connector_ref = util.xml_elem_find_assert_exists(dst_ch, 'COMMUNICATION-CONNECTOR-REF')
    connector_ref_path = connector_ref.text
    assert connector_ref_path is not None, "Destination channel is missing COMMUNICATION-CONNECTOR-REF text."
    server_port_data = bundle_data['server_port']
    server_net_end = util.xml_elem_type_find(dst_net_ends, 'NETWORK-ENDPOINT', name_transformer(server_port_data['network_endpoint']['name']))
    if server_net_end is None:
        server_net_end = factory.xml_network_endpoint_ipv4_create(name_transformer(server_port_data['network_endpoint']['name']), server_port_data['network_endpoint']['address'], server_port_data['network_endpoint']['source'], server_port_data['network_endpoint']['mask'])
        util.xml_elem_append(dst_net_ends, server_net_end, dst_arxml.parents)
    server_net_end_path = util.xml_elem_get_abs_path(server_net_end, dst_arxml)
    server_sock_addr = factory.xml_socket_address_udp_create(name_transformer(server_port_data['name']), name_transformer(server_port_data['app_endpoint_name']), server_net_end_path, server_port_data['udp_port'], connector_ref_path)
    util.xml_elem_append(dst_soads, server_sock_addr, dst_arxml.parents)
    server_ref = util.xml_elem_get_abs_path(server_sock_addr, dst_arxml)
    client_port_data = bundle_data['client_port']
    client_net_end = util.xml_elem_type_find(dst_net_ends, 'NETWORK-ENDPOINT', name_transformer(client_port_data['network_endpoint']['name']))
    if client_net_end is None:
        client_net_end = factory.xml_network_endpoint_ipv4_create(name_transformer(client_port_data['network_endpoint']['name']), client_port_data['network_endpoint']['address'], client_port_data['network_endpoint']['source'], client_port_data['network_endpoint']['mask'])
        util.xml_elem_append(dst_net_ends, client_net_end, dst_arxml.parents)
    client_net_end_path = util.xml_elem_get_abs_path(client_net_end, dst_arxml)
    client_sock_addr = factory.xml_socket_address_udp_create(name_transformer(client_port_data['name']), name_transformer(client_port_data['app_endpoint_name']), client_net_end_path, client_port_data['udp_port'], connector_ref_path)
    util.xml_elem_append(dst_soads, client_sock_addr, dst_arxml.parents)
    client_ref = util.xml_elem_get_abs_path(client_sock_addr, dst_arxml)
    dst_pdu_trigs_container = util.xml_elem_find_assert_exists(dst_ch, 'PDU-TRIGGERINGS')
    pdus_to_match = set(pdus)
    filtered_dst_trigs = [trig for trig in dst_pdu_trigs_container if util.xml_elem_find(trig, 'SHORT-NAME') is not None and any(p in util.xml_elem_find(trig, 'SHORT-NAME').text for p in pdus_to_match)]
    ipdu_identifiers = []
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
        ipdu = factory.xml_socket_connection_ipdu_id_create(frame_data['id'], ipdu_port_ref_text, trig_path, rgroup_path)
        ipdu_identifiers.append(ipdu)
    new_bundle = factory.xml_socket_connection_bundle_create(name_transformer(bundle_data['name']), client_ref, server_ref)
    bpdus_container = util.xml_elem_find_assert_exists(new_bundle, 'PDUS')
    for ipdu in ipdu_identifiers:
        bpdus_container.append(ipdu)
    dst_bundles_container = util.xml_elem_find_assert_exists(dst_ch, 'CONNECTION-BUNDLES')
    util.xml_elem_append(dst_bundles_container, new_bundle, dst_arxml.parents)


# --- Main Test Execution ---
def main():
    """
    Main function to load ARXML files and test both versions of the function.
    """
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    # --- File Paths ---
    source_file = 'SRC_one.arxml'
    destination_file = 'Target_one.arxml'
    
    try:
        # --- Load Original Data ONCE ---
        logging.info("Loading original ARXML files once...")
        original_source_tree = ET.parse(source_file)
        original_destination_tree = ET.parse(destination_file)
        logging.info("Files loaded.")

        # --- Test Old Function ---
        print("\n" + "="*20, "TESTING ORIGINAL FUNCTION", "="*20)
        src_arxml_old = ArxmlFile(copy.deepcopy(original_source_tree))
        dst_arxml_old = ArxmlFile(copy.deepcopy(original_destination_tree))
        har.copy_communication_packages(src_arxml_old, dst_arxml_old)
        print("--- Original function finished successfully ---")
        
        # --- Test Refactored Function ---
        print("\n" + "="*18, "TESTING REFACTORED FUNCTION", "="*18)
        src_arxml_new = ArxmlFile(copy.deepcopy(original_source_tree))
        dst_arxml_new = ArxmlFile(copy.deepcopy(original_destination_tree))
        copy_communication_packages(src_arxml_new, dst_arxml_new)
        print("--- Refactored function finished successfully ---")



    except FileNotFoundError as e:
        logging.error(f"Error: File not found. Please ensure '{e.filename}' is in the same directory.")
    except ET.ParseError as e:
        logging.error(f"Error parsing XML file: {e}")
    except AssertionError as e:
        logging.error(f"TEST FAILED: An assertion failed during execution: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
