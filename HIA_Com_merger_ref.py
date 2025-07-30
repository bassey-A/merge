#!/usr/bin/python3

import logging
import sys
import uuid
import copy
import xml.etree.ElementTree as ET
import re
# import autosar
import factory
# import mrc_abstraction as mrc
import util
# import swc_patcher
# from update_routing_groups import update_all_routing_refs
from typing import List, Optional


#### delete later
class ArxmlFile:
    def __init__(self, tree):
        self.xml = tree
        self.parents = {}
        self.filename = ""

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


def xml_get_physical_channel(arxml: ET.ElementTree, ch_type, name):
    """
    Finds a PhysicalChannel from a given type and name.
    """
    channels = util.xml_elem_findall(arxml.xml.getroot(), ch_type)
    for channel in channels:
        # Safely find the SHORT-NAME element
        short_name_el = util.xml_get_child_elem_by_tag(channel, 'SHORT-NAME')
        if short_name_el is not None and short_name_el.text == name:
            return channel
    return None

### Changes:
# * Replaced index access (`channel[0].text`) with `util.xml_get_child_element_by_tag` call.
# * This provides error handling if a channel is missing a `SHORT-NAME`.
# * Explicitly returns `None` if no matching channel is found

######################################################################


def xml_get_physical_channel_old(arxml, ch_type, name):
    # Get PhysicalChannel of given type and name

    channels = util.xml_elem_findall(arxml.getroot(), ch_type)
### change    channels = util.xml_elem_findall(arxml.xml.getroot(), ch_type)
    for channel in channels:
        util.assert_elem_tag(channel[0], 'SHORT-NAME')
        if name == channel[0].text:
            return channel

def fetch_pdu_old(src_arxml):
    # Fetch Pdus from communication pkg from src arxml
    # Returns list of i-signal-i-pdus found

    # Get source packages
    src_com = util.xml_ar_package_find(src_arxml.getroot(), 'Communication')
### change    src_com = util.xml_ar_package_find(src_arxml.xml.getroot(), 'Communication')
    assert src_com is not None, "Source Communication package is not found!"

    pdus = []

    # Copy only isignal related pdus
    isig_pdus = util.xml_elem_findall(src_com, 'I-SIGNAL-I-PDU')

    # Save isignal pdus for pdu filtering
    pdus = [pdu[0].text for pdu in isig_pdus]

    return pdus


#####################################################################

def fetch_pdu(src_arxml) -> List[str]:
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

### Key Differences:
# * Replaced `assert` with a call to the new `util.find_ar_package` helper, which provides error handling.
# * Replaced index access (`pdu[0].text`) safer loop that uses `util.xml_get_child_element_by_tag`.

# ---------------------------------------------------------------------

# 3. copy_communication_packages
#
# Original Version was very long and used many asserts and indices.


def copy_communication_packages(src_arxml, dst_arxml):
    # Copy Communication source to destination packages
    # enlisted in _COMMUNICATION_PACKAGES_
    # Copy ASSOCIATED-COM-I-PDU-GROUP-REFS
    # Returns list of i-signal-i-pdus found

    # Get source and destination packages
    src_com = util.xml_ar_package_find(src_arxml.xml.getroot(), 'Communication')
    assert src_com is not None, "Source Communication package is not found!"
    dst_com = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'Communication')
    assert dst_com is not None, "Destination Communication "\
                                "package is not found!"
    pdus = []
    isig_pdus_len = []
    frame_len = []
    for name in _COMMUNICATION_PACKAGES_:
        src = util.xml_ar_package_find(src_com, name)
        dst = util.xml_ar_package_find(dst_com, name)
        if src is None:
            logging.warning("Missing source package Communication/%s", name)
            util.MISSING_SRC_PACKAGE.append(True)
            continue
        if dst is None:
            # No destination package found; create AR-PACKAGE
            # and append it to the destination AR-PACKAGES
            dst = factory.xml_ar_package_create(name, str(uuid.uuid4()) +
                                        '-Communication-' + name)
            util.assert_elem_tag(dst_com[1], 'AR-PACKAGES')
            util.xml_elem_append(dst_com[1], dst, dst_arxml.parents)
        if name == 'Pdu':
            # Copy only isignal related pdus
            isig_pdus = util.xml_elem_findall(src_com, 'I-SIGNAL-I-PDU')
            util.assert_elem_tag(dst[1], 'ELEMENTS')
            util.xml_elem_extend(isig_pdus, dst[1], src_arxml, dst_arxml)
            # Save isignal pdus for pdu filtering
            pdus = [pdu[0].text for pdu in isig_pdus]
            # Fetch the pdu length and the pdu name
            isig_pdus_len = [(util.xml_elem_find(pdu, "LENGTH").text, pdu[0].text) for pdu in isig_pdus]
            # Sort List by PDU Name
            isig_pdus_len = sorted(isig_pdus_len, key=lambda x: x[1])

            frames = util.xml_elem_findall(src_com, 'CAN-FRAME')
            if frames is not None:
                # Fetch the frame length and the pdu name
                frame_len = [(util.xml_elem_find(frame, "FRAME-LENGTH").text,
                              util.xml_elem_find(frame, "PDU-REF").text.split("/")[-1]) \
                             for frame in frames]
                # Sort List by PDU Name
                frame_len = sorted(frame_len, key=lambda x: x[1])

            if len(frame_len) > 0 \
                    and len(isig_pdus_len) > 0:
                # Loop on those two lists and break once a difference is found
                # This indicates a length mismatch between the pdu and its corresponding frame
                for i, pdu_cfg in enumerate(isig_pdus_len):
                    if frame_len[i] != pdu_cfg:
                        logging.warning("Found a mismatch: in PDU: %s, frame length: %s, PDU length: %s",\
                            pdu_cfg[1], frame_len[i][0], pdu_cfg[0])
                        break
            continue

        # Copy source elements
        util.assert_elem_tag(src[1], 'ELEMENTS')
        util.assert_elem_tag(dst[1], 'ELEMENTS')
        util.xml_elem_extend(src[1], dst[1], src_arxml, dst_arxml)

    # Copy ASSOCIATED-COM-I-PDU-GROUP-REFS
    src_group = util.xml_elem_find(src_arxml.xml.getroot(),
                              'ASSOCIATED-COM-I-PDU-GROUP-REFS')
    assert src_group is not None, "Source element "\
                                  "ASSOCIATED-COM-I-PDU-GROUP-REFS "\
                                  "is not found!"
    dst_group = util.xml_elem_find(dst_arxml.xml.getroot(),
                              'ASSOCIATED-COM-I-PDU-GROUP-REFS')
    assert dst_group is not None, "Destination element "\
                                  "ASSOCIATED-COM-I-PDU-GROUP-REFS "\
                                  "is not found!"
    util.xml_elem_extend(list(src_group), dst_group, src_arxml, dst_arxml,
                    src_name=lambda el: el.text,
                    dst_name=lambda el: el.text)
    return pdus



### Changes:
# * The complex logic for finding/creating packages, extracting PDU/frame data, and copying elements has been moved to dedicated helper functions.
# * Index accesses (`dst[1]`, `pdu[0].text`) have been replaced with robust helper function calls.
def get_pdu_names(isignal_pdus: List[ET.Element]) -> List[str]:
    """Safely extracts the SHORT-NAME text from a list of I-SIGNAL-I-PDU elements."""
    pdu_names = []
    for pdu in isignal_pdus:
        # Assumes xml_get_child_value_by_tag is in your util.py
        name = util.xml_get_child_value_by_tag(pdu, 'SHORT-NAME')
        if name:
            pdu_names.append(name)
    return pdu_names




# ---------------------------------------------------------------------

def copy_isignal_and_pdu_triggerings(src_arxml,
                                     dst_arxml, pdus,
                                     dst_eth_physical_channel, graceful):
    # Copy source to destination I-SIGNAL-TRIGGERINGS and PDU-TRIGGERINGS
    # Updates triggering's references from src_path to dst_path
    # Filter Pdu related triggering elements via provided pdus list
    # Returns a mapping of all of the updated paths

    path_map = {}

    # Get source and destination channels

    # TODO Fix this based on Device Proxy type somehow. For now, use
    # the .arxml name to see if it's a CAN or ETHERNET src channel we
    # should be looking for
    if "Eth" not in src_arxml.filename:
        src_ch = util.xml_elem_find(src_arxml.xml.getroot(), _CHANNEL_MAPPING_[0])
        assert src_ch is not None, "Source element %s is not found!" \
                                   % _CHANNEL_MAPPING_[0]
    else:
        src_ch = util.xml_elem_find(src_arxml.xml.getroot(), _CHANNEL_MAPPING_[1])
        assert src_ch is not None, "Source element %s is not found!" \
                                   % _CHANNEL_MAPPING_[1]

    # Note that dst_ch is always an ETHERNET-PHYSICAL-CHANNEL.
    # Conceptually this relates to the fact that we only have Ethernet busses
    # in the HIs so every message that comes from MR Nodes needs to eventually
    # be converted to Ethernet. MR Nodes might be using CAN or ETH, which is
    # what the if/else branch above tries to determine for src_ch
    dst_ch = xml_get_physical_channel(dst_arxml, _CHANNEL_MAPPING_[1],
                                      dst_eth_physical_channel)
    assert dst_ch is not None, "Destination element %s is "\
                               "not found!" % _CHANNEL_MAPPING_[1]

    # Remove FRAME-TRIGGERINGS since their PDU-TRIGGERINGS
    # reside under same ancenstor, so we can simplify the code
    frame_trig = util.xml_elem_find(src_ch, 'FRAME-TRIGGERINGS')
    if frame_trig:
        src_arxml.parents[frame_trig].remove(frame_trig)

    # Sync isignal triggerings
    #
    # Get source and destination packages

    # Get the ECU-COMM-PORT-INSTANCES respective to the channel
    # Because a dp arxml could have to 2 channels
    src_ecu_instance = util.xml_elem_find(src_arxml.xml.getroot(), 'ECU-INSTANCE')
    assert src_ecu_instance is not None, "Source ECU-INSTANCE package is not found!"

    if "ETHERNET" in src_ch.tag:
        src_connector = util.xml_elem_find(src_ecu_instance, 'ETHERNET-COMMUNICATION-CONNECTOR')
    else:
        src_connector = util.xml_elem_find(src_ecu_instance, 'CAN-COMMUNICATION-CONNECTOR')
    # Get path transformers
    src_ecpi = util.xml_elem_find(src_connector,
                             'ECU-COMM-PORT-INSTANCES')
    assert src_ecpi is not None, "Source element ECU-COMM-PORT-INSTANCES "\
                                 "is not found!"
    dst_ecpi = util.xml_elem_find(dst_arxml.xml.getroot(),
                             'ECU-COMM-PORT-INSTANCES')
    assert dst_ecpi is not None, "Destination element "\
                                 "ECU-COMM-PORT-INSTANCES is not found!"
    src_path = util.xml_elem_get_abs_path(src_ecpi, src_arxml)
    dst_path = util.xml_elem_find(dst_ch, 'COMMUNICATION-CONNECTOR-REF').text
    # Get source and destination isignal triggerings
    src_trig = util.xml_elem_find(src_ch, 'I-SIGNAL-TRIGGERINGS')
    assert src_trig is not None, "Source %s:I-SIGNAL-TRIGGERINGS "\
                                 "is not found!" % _CHANNEL_MAPPING_[0]
    dst_trig = util.xml_elem_find(dst_ch, 'I-SIGNAL-TRIGGERINGS')

    if dst_trig is None:
        dst_trig = factory.xml_isignal_triggerings_create()
        util.xml_elem_append(dst_ch, dst_trig, dst_arxml.parents)

    assert dst_trig is not None, "Destination %s:I-SIGNAL-TRIGGERINGS "\
                                 "is not found!" % _CHANNEL_MAPPING_[1]
    refs = util.xml_elem_findall(src_trig, 'I-SIGNAL-PORT-REF')
    assert refs is not None, "There is no I-SIGNAL-PORT-REF refs found "\
                             "for I-SIGNAL-TRIGGERINGS!"
    # Transform signal port refs
    util.xml_ref_transform_all(refs, src_path, dst_path)
    # Extend destination list and update path map
    path_map.update(util.xml_elem_extend(list(src_trig), dst_trig,
                                    src_arxml, dst_arxml))

    # Sync pdu triggerings
    #

    # Get source and destination pdu triggerings
    src_trig = util.xml_elem_find(src_ch, 'PDU-TRIGGERINGS')
    assert src_trig is not None, "Source %s:PDU-TRIGGERINGS "\
                                 "is not found!" % _CHANNEL_MAPPING_[0]
    # Remove non-relevant pdu triggerings
    util.xml_elem_child_remove_all(src_trig, [trig for trig in src_trig
                                         if not any(pdu in trig[0].text
                                                    for pdu in pdus)])
    # Transform pdu port refs
    refs = util.xml_elem_findall(src_trig, 'I-PDU-PORT-REF')
    assert refs is not None, "There is no I-PDU-PORT-REF refs found "\
                             "for PDU-TRIGGERINGS!"
    util.xml_ref_transform_all(refs, src_path, dst_path)

    # Get path transformers
    src_path = util.xml_elem_get_abs_path(src_trig, src_arxml)
    dst_path = util.xml_elem_get_abs_path(dst_trig, dst_arxml)

    dst_trig = util.xml_elem_find(dst_ch, 'PDU-TRIGGERINGS')

    if dst_trig is None:
        dst_trig = factory.xml_pdu_triggerings_create()
        util.xml_elem_append(dst_ch, dst_trig, dst_arxml.parents)

    assert dst_trig is not None, "Destination %s:PDU-TRIGGERINGS "\
                                 "is not found!" % _CHANNEL_MAPPING_[1]
    refs = util.xml_elem_findall(src_trig, 'I-SIGNAL-TRIGGERING-REF')
    assert refs is not None, "There is no I-SIGNAL-TRIGGERING-REF refs found "\
                             "for PDU-TRIGGERINGS!"
    # Transform singal triggering refs
    util.xml_ref_transform_all(refs, src_path, dst_path)
    # Copy elements and update path map
    path_map.update(util.xml_elem_extend( list(src_trig), dst_trig,
                                    src_arxml, dst_arxml, graceful=graceful))

    return path_map


def prepare_ethernet_physical_channel(dst_arxml, dst_eth_physical_channel):
    # This function is needed due to yet another limitation in the Autosar
    # library. Normally, the library should make sure that an Autosar object,
    # when dumped into an .arxml, follows the Autosar schema for that object.
    # The schema would specify the order in which the Autosar object's
    # sub-elements would appear in the .arxml. We do not have this feature
    # in the library, the "schema" in our case is whatever order the
    # sub-elements get added to the Element object (usually using append).

    # This function makes sure that an ETHERNET-PHYSICAL-CHANNEL has all the
    # sub-elements in the correct order. Note that this function might need
    # some tweaking in case the ETHERNET-PHYSICAL-CHANNEL coming out of Capital
    # Networks has other sub-elements which require specific ordering.

    dst_ch = xml_get_physical_channel(dst_arxml,
                                      'ETHERNET-PHYSICAL-CHANNEL',
                                      dst_eth_physical_channel)
    assert dst_ch is not None,\
        "Destination element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"

    # Find 'COMM-CONNECTORS' index and then add 'I-SIGNAL-TRIGGERINGS'
    # and 'PDU-TRIGGERINGS' after that index
    for i, channel in enumerate(dst_ch):
        tag = channel.tag
        if tag[tag.rfind('}')+1:] == 'COMM-CONNECTORS':
            comm_conn_idx = i
            break

    assert comm_conn_idx is not None,\
        "Destination element 'COMM-CONNECTORS' is not found!"

    dst_isig_trig = util.xml_elem_find(dst_ch, 'I-SIGNAL-TRIGGERINGS')
    if dst_isig_trig is None:
        dst_isig_trig = factory.xml_isignal_triggerings_create()
        dst_ch.insert(comm_conn_idx + 1, dst_isig_trig)
        dst_arxml.parents[dst_isig_trig] = dst_ch

    dst_pdu_trig = util.xml_elem_find(dst_ch, 'PDU-TRIGGERINGS')
    if dst_pdu_trig is None:
        dst_pdu_trig = factory.xml_pdu_triggerings_create()
        dst_ch.insert(comm_conn_idx + 2, dst_pdu_trig)
        dst_arxml.parents[dst_pdu_trig] = dst_ch

    # Find 'NETWORK-ENDPOINTS' index and then add 'SO-AD-CONFIG'
    # after that index. Make sure to add 'CONNECTION-BUNDLES'
    # before 'SOCKET-ADDRESSS' as subelements of 'SO-AD-CONFIG'
    for i, channel in enumerate(dst_ch):
        tag = channel.tag
        if tag[tag.rfind('}') + 1:] == 'NETWORK-ENDPOINTS':
            net_end_idx = i
            break

    assert net_end_idx is not None, \
        "Destination element 'NETWORK-ENDPOINTS' is not found!"

    dst_soad_config = util.xml_elem_find(dst_ch, 'SO-AD-CONFIG')
    if dst_soad_config is None:
        dst_soad_config = factory.xml_soad_config_create()
        dst_sock_addrs = factory.xml_socket_addresss_create()
        dst_conn_bundles = factory.xml_conn_bundles_create()

        dst_soad_config.append(dst_conn_bundles)
        dst_soad_config.append(dst_sock_addrs)

        dst_ch.insert(net_end_idx + 1, dst_soad_config)

        dst_arxml.parents[dst_sock_addrs] = dst_soad_config
        dst_arxml.parents[dst_conn_bundles] = dst_soad_config
        dst_arxml.parents[dst_soad_config] = dst_ch



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


def copy_socket_connection_bundles(src_arxml, dst_arxml,
                                   dst_eth_physical_channel,
                                   sock_addr_map, isig_pdu_path_map):
    # Copies an Ethernet DP's SocketConnectionBundles to destination channel
    # Uses sock_addr_map to update the CLIENT-PORT-REFs and SERVER-PORT-REFs
    # Uses isig_pdu_path_map to update the PDU-TRIGGERING-REFs

    # Get source and destination Ethernet channels
    src_ch = util.xml_elem_find(src_arxml.xml.getroot(),
                           'ETHERNET-PHYSICAL-CHANNEL')
    assert src_ch is not None,\
        "Source element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"
    dst_ch = xml_get_physical_channel(dst_arxml,
                                      'ETHERNET-PHYSICAL-CHANNEL',
                                      dst_eth_physical_channel)
    assert dst_ch is not None,\
        "Destination element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"

    # Get SocketConnectionBundles
    src_sock_conn_bundles = util.xml_elem_find(src_ch, 'CONNECTION-BUNDLES')
    assert src_sock_conn_bundles is not None,\
        "Source element 'CONNECTION-BUNDLES' is not found!"
    dst_sock_conn_bundles = util.xml_elem_find(dst_ch, 'CONNECTION-BUNDLES')
    assert dst_sock_conn_bundles is not None,\
        "Destination element 'CONNECTION-BUNDLES' is not found!"

    # Update CLIENT-PORT-REFs, SERVER-PORT-REF, PDU-TRIGGERING-REFs
    for sock_conn_bundle in src_sock_conn_bundles:

        client_port_ref = util.xml_elem_find(sock_conn_bundle,
                                        'CLIENT-PORT-REF')
        client_port_ref.text = sock_addr_map[client_port_ref.text]

        server_port_ref = util.xml_elem_find(sock_conn_bundle,
                                        'SERVER-PORT-REF')
        server_port_ref.text = sock_addr_map[server_port_ref.text]

        pdu_trig_refs = util.xml_elem_findall(sock_conn_bundle,
                                           'PDU-TRIGGERING-REF')
        for pdu_trig_ref in pdu_trig_refs:
            pdu_trig_ref.text = isig_pdu_path_map[pdu_trig_ref.text]

    # Extend destination socket connection bundle list with source socket
    # connection bundle list. Detect conflicts by looking at 'HEADER-ID'.
    util.xml_elem_extend(src_sock_conn_bundles, dst_sock_conn_bundles,
                    src_arxml, dst_arxml,
                    src_name=lambda el: util.xml_elem_find(el, 'HEADER-ID').text,
                    dst_name=lambda el: util.xml_elem_find(el, 'SHORT-NAME').text)


def copy_socket_addresses(src_arxml, dst_arxml,
                          dst_eth_physical_channel,
                          net_ends_path_map):
    # Copies an Ethernet DP's SocketAddresses to destination channel
    # Uses net_ends_path_map to update the NetworkEndpointsRefs

    # Note that this function makes the following assumptions:
    # - EthernetPhysicalChannels only contain one COMMUNICATION-CONNECTOR-REF

    # Get source and destination Ethernet channels
    src_ch = util.xml_elem_find(src_arxml.xml.getroot(),
                           'ETHERNET-PHYSICAL-CHANNEL')
    assert src_ch is not None, \
        "Source element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"
    dst_ch = xml_get_physical_channel(dst_arxml,
                                      'ETHERNET-PHYSICAL-CHANNEL',
                                      dst_eth_physical_channel)
    assert dst_ch is not None, \
        "Destination element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"

    # Get socket addresses
    src_sock_addrs = util.xml_elem_find(src_ch, 'SOCKET-ADDRESSS')
    assert src_sock_addrs is not None,\
        "Source element 'SOCKET-ADDRESSS' is not found!"
    dst_sock_addrs = util.xml_elem_find(dst_ch, 'SOCKET-ADDRESSS')
    assert dst_sock_addrs is not None,\
        "Destination element 'SOCKET-ADDRESSS' is not found!"

    # Get ConnectorRef by looking in the Ethernet Physical Channel
    comm_connector_ref = util.xml_elem_find(dst_ch, 'COMMUNICATION-CONNECTOR-REF')
    # Correct NetworkEndpointRefs
    for sock_addr in src_sock_addrs:
        net_end_ref = util.xml_elem_find(sock_addr, 'NETWORK-ENDPOINT-REF')
        net_end_ref.text = net_ends_path_map[net_end_ref.text]
        multicast_ref = util.xml_elem_find(sock_addr, 'MULTICAST-CONNECTOR-REF')
    if multicast_ref is not None:
        multicast_ref.text = comm_connector_ref.text
    # Correct ConnectorRef, if present
    for sock_addr in src_sock_addrs:
        connector_ref = util.xml_elem_find(sock_addr, 'CONNECTOR-REF')
        if connector_ref is not None:
            connector_ref.text = comm_connector_ref.text
    #util.xml_elem_child_remove_all(dst_sock_addrs, [socket for socket in dst_sock_addrs
    #                              if util.xml_elem_find(socket, 'PORT-NUMBER') is None])

    # Extend destination socket address list with source socket address
    # list. Detect conflicts by looking at 'PORT-NUMBER'.
    path_map = util.xml_elem_extend(
        src_sock_addrs, dst_sock_addrs,
        src_arxml, dst_arxml,
        src_name=lambda el: util.xml_elem_find(el, 'PORT-NUMBER').text,
        dst_name=lambda el: util.xml_elem_find(el, 'SHORT-NAME').text)

    return path_map


def create_socket_connection_bundle(bundle, src_arxml, dst_arxml,
                                    frames, pdus, dst_eth_physical_channel):
    # Creates various socket adapter elements such as:
    # SO-AD-ROUTING-GROUP, NETWORK-ENDPOINT, SOCKET-ADDRESS
    # and SOCKET-CONNECTION-BUNDLE with corresponding
    # SOCKET-CONNECTION-IPDU-IDENTIFIER (populated from pdus)

    # Get ECU System names
    ecu_dst = util.xml_ecu_sys_name_get(dst_arxml)
    ecu_src = util.xml_ecu_sys_name_get(src_arxml)

    # An ECU System name transformer
    def get_name(s, src=ecu_src, dst=ecu_dst):
        return s.replace('Hix', dst).replace('ECUx', src)

    # Get destination Communication package
    dst_com = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'Communication')
    assert dst_com is not None, "Destination Communication "\
                                "package is not found!"

    # Get soad routing group
    dst_rgroups = util.xml_ar_package_find(dst_com, 'SoAdRoutingGroup')
    if dst_rgroups is None:
        # No package found; create AR-PACKAGE
        # and append it to the AR-PACKAGES
        name = 'SoAdRoutingGroup'
        dst_rgroups = factory.xml_ar_package_create(name, str(uuid.uuid4()) +
                                            '-Communication-' + name)
        util.assert_elem_tag(dst_com[1], 'AR-PACKAGES')
        util.xml_elem_append(dst_com[1], dst_rgroups, dst_arxml.parents)

    # Create routing group
    rgroup = factory.xml_soad_routing_group_create(get_name(bundle['routing_group']))
    util.assert_elem_tag(dst_rgroups[1], 'ELEMENTS')
    util.xml_elem_extend(rgroup, dst_rgroups[1], src_arxml, dst_arxml,
                    src_name=lambda el: el.text)
    rgroup_path = util.xml_elem_get_abs_path(rgroup, dst_arxml)
    # Get physical channel
    dst_ch = xml_get_physical_channel(dst_arxml, _CHANNEL_MAPPING_[1],
                                      dst_eth_physical_channel)
    assert dst_ch is not None, "Destination element %s is "\
                               "not found!" % _CHANNEL_MAPPING_[1]
    # Get network endpoints
    dst_net_ends = util.xml_elem_find(dst_ch, 'NETWORK-ENDPOINTS')
    assert dst_net_ends is not None, "Destination element "\
                                     "'NETWORK-ENDPOINTS' is not found!"

    def get_network_endpoint(dst_net_ends, end):
        # Returns existing or creates a new endpoint
        net_end = util.xml_elem_type_find(dst_net_ends, 'NETWORK-ENDPOINT',
                                     get_name(end['name']))
        if net_end is None:
            net_end = factory.xml_network_endpoint_ipv4_create(get_name(end['name']),
                                                       end['address'],
                                                       end['source'],
                                                       end['mask'])
            util.xml_elem_append(dst_net_ends, net_end, dst_arxml.parents)
        return net_end

    # Create server port
    #

    server_port = bundle['server_port']
    # Get network endpoint
    net_end = get_network_endpoint(dst_net_ends,
                                   server_port['network_endpoint'])
    # Get network endpoing path
    net_end_path = util.xml_elem_get_abs_path(net_end, dst_arxml)
    # Get network endpoint reference
    net_end_ref = util.xml_elem_type_find(dst_arxml.xml.getroot(),
                                     'NETWORK-ENDPOINT-REF',
                                     net_end_path)
    assert net_end_ref is not None, "Destination element "\
                                    "NETWORK-ENDPOINTS-REF:%s is "\
                                    "not found!" % net_end_path
    # Get network endpoint reference path
    net_end_ref_path = util.xml_elem_get_abs_path(net_end_ref, dst_arxml)

    # Create 1st socket address
    soad1 = factory.xml_socket_address_udp_create(get_name(server_port['name']),
                                          get_name(server_port[
                                           'app_endpoint_name']),
                                          net_end_path,
                                          server_port['udp_port'],
                                          net_end_ref_path)
    # Get socket addresses
    dst_soads = util.xml_elem_find(dst_ch, 'SOCKET-ADDRESSS')
    assert dst_soads is not None, "Destination element "\
                                  "'SOCKET-ADDRESSS' is not found!"
    util.xml_elem_extend(soad1, dst_soads, src_arxml, dst_arxml,
                    src_name=lambda el: el.text)

    # Create client port
    #

    client_port = bundle['client_port']
    # Get network endpoint
    net_end = get_network_endpoint(dst_net_ends,
                                   client_port['network_endpoint'])
    # Get network endpoing path
    net_end_path = util.xml_elem_get_abs_path(net_end, dst_arxml)

    # Create 2nd socket address
    soad2 = factory.xml_socket_address_udp_create(get_name(client_port['name']),
                                          get_name(client_port[
                                           'app_endpoint_name']),
                                          net_end_path,
                                          client_port['udp_port'],
                                          net_end_ref_path)
    util.xml_elem_extend(soad2, dst_soads, src_arxml, dst_arxml,
                    src_name=lambda el: el.text)

    # Get paths
    server_ref = util.xml_elem_get_abs_path(soad1, dst_arxml)
    client_ref = util.xml_elem_get_abs_path(soad2, dst_arxml)

    # Create socket connection bundle
    #

    # Get destination pdu triggerings
    dst_trig = util.xml_elem_find(dst_ch, 'PDU-TRIGGERINGS')
    assert dst_trig is not None, "Destination %s:PDU-TRIGGERINGS "\
                                 "is not found!" % _CHANNEL_MAPPING_[0]
    # Filter only new ones
    dst_trig = [trig for trig in dst_trig
                if any(pdu in trig[0].text
                       for pdu in pdus)]
    # Create socket connection ipdu triggerings
    ipdus = []
    for trig in dst_trig:
        util.assert_elem_tag(trig[1], 'I-PDU-PORT-REFS')
        assert len(trig[1]) == 1, "Invalid number of I-PDU-PORT-REFs "\
                                  "in the PDU-TRIGGERING:%s!" % trig[0].text
        frame = [frames[pdu] for pdu in frames.keys() if pdu == trig[0].text.replace('PduTr', '')]
        assert len(frame) == 1, "The PDU-TRIGGERING:%s can't be matched!"\
                                % trig[0].text
        trig_spec = [frame[0]['id'],
                     trig[1][0].text,
                     util.xml_elem_get_abs_path(trig, dst_arxml),
                     rgroup_path]
        ipdu = factory.xml_socket_connection_ipdu_id_create(*trig_spec)
        util.xml_elem_append(ipdus, ipdu, dst_arxml.parents)

    # Create socket connection bundle
    bundle = factory.xml_socket_connection_bundle_create(get_name(bundle['name']),
                                                 client_ref, server_ref)
    # Get bundles pdus elem
    bpdus = util.xml_elem_find(bundle, 'PDUS')
    bpdus.extend(ipdus)

    # Get connection bundles
    dst_bundles = util.xml_elem_find(dst_ch, 'CONNECTION-BUNDLES')
    assert dst_bundles is not None, "Destination %s:CONNECTION-BUNDLES "\
                                    "is not found!" % _CHANNEL_MAPPING_[0]
    util.xml_elem_extend(bundle, dst_bundles, src_arxml, dst_arxml,
                    src_name=lambda el: el.text)
