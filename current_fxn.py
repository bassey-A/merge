import logging
import copy
import xml.etree.ElementTree as ET
import util
import factory
import HIA_Com_merger_ref as hair
import common_fxn as cf
from test import read_arxml_contents

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
_ISIGNAL_INIT_VAL_BIGEND = {('GATEWAY', 'rx'): ('0', 'MrCommHdrPartB'), ('GATEWAY', 'tx'): ('0', 'MrCommHdrPartB')}
_ISIGNAL_INIT_VAL_LTLEND_ = {('GATEWAY', 'rx'): ('0', 'MrCommHdrPartB'), ('GATEWAY', 'tx'): ('0', 'MrCommHdrPartB')}

# --- Helper Class for Testing ---
class ArxmlFile:
    """A simple wrapper to hold the XML tree and parent map for testing."""
    def __init__(self, tree):
        self.xml = tree
        self.parents = {}


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



def create_socket_connection_bundle(bundle, src_arxml, dst_arxml,
                                    frames, pdus, dst_eth_physical_channel):
    """
    Creates socket adapter elements such as SO-AD-ROUTING-GROUP, NETWORK-ENDPOINT,
    SOCKET-ADDRESS, and SOCKET-CONNECTION-BUNDLE along with SOCKET-CONNECTION-IPDU-IDENTIFIERs.

    Keeps all logic in one function but improves clarity with helper inner functions.
    """

    # Get ECU System names for renaming purposes
    ecu_dst = util.xml_ecu_sys_name_get(dst_arxml)
    ecu_src = util.xml_ecu_sys_name_get(src_arxml)

    def get_name(s):
        # Transform system names consistently
        return s.replace('Hix', ecu_dst).replace('ECUx', ecu_src)

    # Get or create AR-PACKAGE helper
    def get_or_create_ar_package(parent_pkg, pkg_name):
        pkg = util.xml_ar_package_find(parent_pkg, pkg_name)
        if pkg is None:
            pkg = factory.xml_ar_package_create(pkg_name, f"{uuid.uuid4()}-Communication-{pkg_name}")
            util.assert_elem_tag(parent_pkg[1], 'AR-PACKAGES')
            util.xml_elem_append(parent_pkg[1], pkg, dst_arxml.parents)
        return pkg

    # Get or create NETWORK-ENDPOINT helper
    def get_or_create_network_endpoint(container, endpoint_data):
        ep_name = get_name(endpoint_data['name'])
        net_end = util.xml_elem_type_find(container, 'NETWORK-ENDPOINT', ep_name)
        if net_end is None:
            net_end = factory.xml_network_endpoint_ipv4_create(
                ep_name,
                endpoint_data['address'],
                endpoint_data['source'],
                endpoint_data['mask']
            )
            util.xml_elem_append(container, net_end, dst_arxml.parents)
        return net_end

    # Create and append SOCKET-ADDRESS helper
    def create_and_append_socket_address(port_info, net_end_path, net_end_ref_path):
        soad = factory.xml_socket_address_udp_create(
            get_name(port_info['name']),
            get_name(port_info['app_endpoint_name']),
            net_end_path,
            port_info['udp_port'],
            net_end_ref_path
        )
        util.xml_elem_extend(soad, dst_soads, src_arxml, dst_arxml, src_name=lambda el: el.text)
        return soad

    # --- Main flow ---

    # Get Communication AR-PACKAGE in destination
    dst_com = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'Communication')
    assert dst_com is not None, "Destination Communication package is not found!"

    # Ensure SoAdRoutingGroup exists or create it
    dst_rgroups = get_or_create_ar_package(dst_com, 'SoAdRoutingGroup')

    # Create routing group element
    rgroup = factory.xml_soad_routing_group_create(get_name(bundle['routing_group']))
    elements_container = util.xml_elem_find_assert_exists(dst_rgroups[1], 'ELEMENTS')
    util.xml_elem_append(elements_container, rgroup, dst_arxml.parents)
    rgroup_path = util.xml_elem_get_abs_path(rgroup, dst_arxml)

    # Get physical channel
    dst_ch = xml_get_physical_channel(dst_arxml, _CHANNEL_MAPPING_[1], dst_eth_physical_channel)
    assert dst_ch is not None, f"Destination element {_CHANNEL_MAPPING_[1]} '{dst_eth_physical_channel}' is not found!"

    # Get containers inside physical channel
    dst_net_ends = util.xml_elem_find_assert_exists(dst_ch, 'NETWORK-ENDPOINTS')
    dst_soads = util.xml_elem_find_assert_exists(dst_ch, 'SOCKET-ADDRESSS')

    # Get COMMUNICATION-CONNECTOR-REF text (used for socket address refs)
    comm_connector_ref = util.xml_elem_find_assert_exists(dst_ch, 'COMMUNICATION-CONNECTOR-REF')
    connector_ref_text = comm_connector_ref.text
    assert connector_ref_text, "Destination channel missing COMMUNICATION-CONNECTOR-REF text"

    # Server port: get or create network endpoint & create socket address
    server_net_end = get_or_create_network_endpoint(dst_net_ends, bundle['server_port']['network_endpoint'])
    server_net_end_path = util.xml_elem_get_abs_path(server_net_end, dst_arxml)
    server_net_end_ref = util.xml_elem_type_find(dst_arxml.xml.getroot(), 'NETWORK-ENDPOINT-REF', server_net_end_path)
    assert server_net_end_ref is not None, f"NETWORK-ENDPOINT-REF not found for {server_net_end_path}"
    server_net_end_ref_path = util.xml_elem_get_abs_path(server_net_end_ref, dst_arxml)
    soad1 = create_and_append_socket_address(bundle['server_port'], server_net_end_path, server_net_end_ref_path)

    # Client port: same steps
    client_net_end = get_or_create_network_endpoint(dst_net_ends, bundle['client_port']['network_endpoint'])
    client_net_end_path = util.xml_elem_get_abs_path(client_net_end, dst_arxml)
    soad2 = create_and_append_socket_address(bundle['client_port'], client_net_end_path, server_net_end_ref_path)

    # Absolute paths for the created socket addresses
    server_ref = util.xml_elem_get_abs_path(soad1, dst_arxml)
    client_ref = util.xml_elem_get_abs_path(soad2, dst_arxml)

    # Filter PDU-TRIGGERINGS in destination by pdus list
    dst_pdu_triggerings = util.xml_elem_find_assert_exists(dst_ch, 'PDU-TRIGGERINGS')
    filtered_trigs = [trig for trig in dst_pdu_triggerings
                      if any(pdu in util.xml_elem_find(trig, 'SHORT-NAME').text for pdu in pdus)]

    ipdu_ids = []
    for trig in filtered_trigs:
        util.assert_elem_tag(trig[1], 'I-PDU-PORT-REFS')
        assert len(trig[1]) == 1, f"Invalid number of I-PDU-PORT-REFs in PDU-TRIGGERING: {util.xml_elem_find(trig, 'SHORT-NAME').text}"

        pdu_name = util.xml_elem_find(trig, 'SHORT-NAME').text.replace('PduTr', '')
        frame_list = [frames[pdu] for pdu in frames.keys() if pdu == pdu_name]
        assert len(frame_list) == 1, f"PDU-TRIGGERING '{pdu_name}' can't be matched uniquely!"

        trig_spec = [
            frame_list[0]['id'],
            trig[1][0].text,
            util.xml_elem_get_abs_path(trig, dst_arxml),
            rgroup_path
        ]
        ipdu_ids.append(factory.xml_socket_connection_ipdu_id_create(*trig_spec))

    # Create and append SOCKET-CONNECTION-BUNDLE element
    bundle_elem = factory.xml_socket_connection_bundle_create(get_name(bundle['name']), client_ref, server_ref)
    pdus_container = util.xml_elem_find_assert_exists(bundle_elem, 'PDUS')
    pdus_container.extend(ipdu_ids)

    dst_bundles = util.xml_elem_find_assert_exists(dst_ch, 'CONNECTION-BUNDLES')
    util.xml_elem_extend(bundle_elem, dst_bundles, src_arxml, dst_arxml, src_name=lambda el: el.text)


import xml.etree.ElementTree as ET
import types

# Minimal XML wrapper class similar to ArxmlFile used
class DummyArxmlFile:
    def __init__(self, xml_string):
        self.xml = ET.ElementTree(ET.fromstring(xml_string))
        self.parents = {}  # Can be empty for testing if not used directly

# Simple utilities to create dummy xml elements for required structure

def create_dummy_physical_channel(name):
    ch = ET.Element('ETHERNET-PHYSICAL-CHANNEL')
    sn = ET.SubElement(ch, 'SHORT-NAME')
    sn.text = name

    conn_ref = ET.SubElement(ch, 'COMMUNICATION-CONNECTOR-REF')
    conn_ref.text = '/CommunicationConnectorPath'

    net_ends = ET.SubElement(ch, 'NETWORK-ENDPOINTS')
    soadds = ET.SubElement(ch, 'SOCKET-ADDRESSS')
    pdu_trig = ET.SubElement(ch, 'PDU-TRIGGERINGS')
    conn_bundles = ET.SubElement(ch, 'CONNECTION-BUNDLES')

    return ch

def create_dummy_network_endpoint(name, address):
    ne = ET.Element('NETWORK-ENDPOINT')
    sn = ET.SubElement(ne, 'SHORT-NAME')
    sn.text = name
    ip_addr = ET.SubElement(ne, 'IPV-4-ADDRESS')
    ip_addr.text = address
    source = ET.SubElement(ne, 'SOURCE')
    source.text = 'FIXED'
    mask = ET.SubElement(ne, 'NETMASK')
    mask.text = '255.255.255.0'
    return ne

def create_dummy_network_endpoint_ref(path):
    ref = ET.Element('NETWORK-ENDPOINT-REF')
    ref.text = path
    return ref

def create_dummy_pdu_triggering(pdu_name, ipdu_port_ref):
    trig = ET.Element('PDU-TRIGGERING')

    sn = ET.SubElement(trig, 'SHORT-NAME')
    sn.text = pdu_name

    ipdu_refs = ET.SubElement(trig, 'I-PDU-PORT-REFS')
    ref = ET.SubElement(ipdu_refs, 'I-PDU-PORT-REF')
    ref.text = ipdu_port_ref

    return trig

def create_dummy_communication_package():
    com_pkg = ET.Element('AR-PACKAGE')
    sn = ET.SubElement(com_pkg, 'SHORT-NAME')
    sn.text = 'Communication'
    ar_pkgs = ET.SubElement(com_pkg, 'AR-PACKAGES')
    return com_pkg, ar_pkgs

# Construct dummy source and destination ARXML with minimal structure expected by function
def build_dummy_arxml(ecu_name_suffix):
    root = ET.Element('AUTOSAR')
    com_pkg, ar_pkgs = create_dummy_communication_package()
    root.append(com_pkg)
    ar_pkgs.append(ET.Element('ISignal'))  # placeholder, minimal

    physical_channel = create_dummy_physical_channel(f"EthChannel{ecu_name_suffix}")
    root.append(physical_channel)

    return DummyArxmlFile(ET.tostring(root, encoding='unicode'))

# Example Bundle data (simplified)
bundle_data = {
    'name': 'HixECUxSampleBundle',
    'routing_group': 'HixECUxRoutingGroup',
    'server_port': {
        'name': 'HixServerPort',
        'app_endpoint_name': 'HixServerAppEndpoint',
        'udp_port': '30501',
        'network_endpoint': {
            'name': 'HixServerNetEndpoint',
            'address': '10.0.0.1',
            'source': 'FIXED',
            'mask': '255.255.255.0',
        }
    },
    'client_port': {
        'name': 'ECUxClientPort',
        'app_endpoint_name': 'ECUxClientAppEndpoint',
        'udp_port': '30502',
        'network_endpoint': {
            'name': 'ECUxClientNetEndpoint',
            'address': '192.168.0.2',
            'source': 'FIXED',
            'mask': '255.255.255.0',
        }
    },
}

# Dummy frames dictionary
frames = {
    'SamplePdu': {'id': 'Frame123'}
}

# List of PDUs to match in triggers
pdus = ['SamplePdu']

# Build dummy src and dst ARXML objects
src_arxml = build_dummy_arxml('Src')
dst_arxml = build_dummy_arxml('Dst')

# For minimal testing, insert appropriate elements into dst_arxml tree if needed
# For example, add NetworkEndpoints and NetworkEndpointRefs in dst_arxml according to code expectations

# This is just an example and may need adjustment to match exactly your XML schema

create_socket_connection_bundle(bundle_data, src_arxml, dst_arxml, frames, pdus, 'EthChannelDst')
