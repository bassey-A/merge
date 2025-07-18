#!/usr/bin/python3
import logging
import sys
import os
import uuid
import copy
import xml.etree.ElementTree as ET
import re
import autosar
import factory
import mrc_abstraction as mrc
import util
import swc_patcher
from update_routing_groups import update_all_routing_refs

# This script's version
VERSION = '0.1.1'

# Add here list of root packages to copy
_ROOT_PACKAGES_ = (('Signal',      util.NAME_CLASH_IS_ERROR),
                   ('SignalGroup', util.NAME_CLASH_IS_ERROR))


# Data sync communication packages
_COMMUNICATION_PACKAGES_ = ('Frame',
                            'Pdu',
                            'ISignal',
                            'ISignalGroup',
                            'ISignalPduGroup')

_ECUSystem_TAGS_ = ('COMM-CONTROLLERS',
                    'CONNECTORS')

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
_ISIGNAL_INIT_VAL_LTLEND_ =\
 {('CAN',    'STANDARD'): (mrc.MRC_CAN_STANDARD_INIT_LE,    'isMrCommHdrPartB_Can_'),
  ('CAN',    'EXTENDED'): (mrc.MRC_CAN_EXTENDED_INIT_LE,    'isMrCommHdrPartB_Can_'),
  ('CAN-20', 'STANDARD'): (mrc.MRC_CAN_20_STANDARD_INIT_LE, 'isMrCommHdrPartB_Can_'),
  ('CAN-20', 'EXTENDED'): (mrc.MRC_CAN_20_EXTENDED_INIT_LE, 'isMrCommHdrPartB_Can_'),
  ('CAN-FD', 'STANDARD'): (mrc.MRC_CAN_FD_STANDARD_INIT_LE, 'isMrCommHdrPartB_CanFd_'),
  ('CAN-FD', 'EXTENDED'): (mrc.MRC_CAN_FD_EXTENDED_INIT_LE, 'isMrCommHdrPartB_CanFd_')}

_ISIGNAL_INIT_VAL_BIGEND =\
 {('CAN',    'STANDARD'): (mrc.MRC_CAN_STANDARD_INIT_BE,    'isMrCommHdrPartB_Can_'),
  ('CAN',    'EXTENDED'): (mrc.MRC_CAN_EXTENDED_INIT_BE,    'isMrCommHdrPartB_Can_'),
  ('CAN-20', 'STANDARD'): (mrc.MRC_CAN_20_STANDARD_INIT_BE, 'isMrCommHdrPartB_Can_'),
  ('CAN-20', 'EXTENDED'): (mrc.MRC_CAN_20_EXTENDED_INIT_BE, 'isMrCommHdrPartB_Can_'),
  ('CAN-FD', 'STANDARD'): (mrc.MRC_CAN_FD_STANDARD_INIT_BE, 'isMrCommHdrPartB_CanFd_'),
  ('CAN-FD', 'EXTENDED'): (mrc.MRC_CAN_FD_EXTENDED_INIT_BE, 'isMrCommHdrPartB_CanFd_')}

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
_REF_MAPPING_ =\
    {'ecusystem': '/ECUSystem/Hic/HICMAIN/HIC',
     'vehicletopology': '/VehicleTopology/HIAsystemVehSecCANMAIN'}

# Define disallowed PDU names that should not be copied
_DISALLOWED_PDU_NAMES_ = ('N-PDU', 'DCM-I-PDU')

def is_xml_tag_present(xml_file_path, tag_name):
    try:
        # Parse the XML file
        tree = ET.parse(xml_file_path)
        root = tree.getroot()

        # Check if the specified tag is present
        return bool(util.xml_elem_find(root,tag_name) is not None)

    except ET.ParseError as e:
        print("Error parsing XML file:", e)
        return False

def replace_prefix(old_prefix, new_prefix):
    # Split old and new prefixes into parts
    old_parts = old_prefix.strip('/').split('/')
    new_parts = new_prefix.strip('/').split('/')

    # Update only the related parts
    for i, part in enumerate(new_parts):
        old_parts[i] = part

    return f"/{'/'.join(old_parts)}"

def update_refs(elem):

    # Iterate through all elements and fetch the tag names containing '-REF'
    for elem in elem.iter():
        if "-REF" in util.xml_strip_namespace(elem):
            old_prefix = elem.text
            for key in _REF_MAPPING_:
                if key.lower() in old_prefix.lower():
                    new_prefix = _REF_MAPPING_.get(key)
                    related_parts = replace_prefix(old_prefix, new_prefix)
                    elem.text = related_parts
    for child in elem:
        update_refs(child)

def xml_get_physical_channel(arxml, ch_type, name):
    # Get PhysicalChannel of given type and name

    channels = util.xml_elem_findall(arxml.xml.getroot(), ch_type)
    for channel in channels:
        util.assert_elem_tag(channel[0], 'SHORT-NAME')
        if name == channel[0].text:
            return channel
def fetch_pdu(src_arxml):
    # Fetch Pdus from communication pkg from src arxml
    # Returns list of i-signal-i-pdus found

    # Get source packages
    src_com = util.xml_ar_package_find(src_arxml.xml.getroot(), 'Communication')
    assert src_com is not None, "Source Communication package is not found!"

    pdus = []

    # Copy only isignal related pdus
    isig_pdus = util.xml_elem_findall(src_com, '')

    # Save isignal pdus for pdu filtering
    pdus = [pdu[0].text for pdu in isig_pdus]

    return pdus

def copy_ecusystem_packages(src_arxml, dst_arxml):
    # Get source and destination ECU-INSTANCE elements
    src_ecu_instance = util.xml_elem_find(src_arxml.xml.getroot(), 'ECU-INSTANCE')
    dst_ecu_instance = util.xml_elem_find(dst_arxml.xml.getroot(), 'ECU-INSTANCE')

    for tag in _ECUSystem_TAGS_:
        src = util.xml_elem_find(src_ecu_instance, tag)
        dst = util.xml_elem_find(dst_ecu_instance, tag)

        if tag == 'COMM-CONTROLLERS':
            # Get CAN controllers from source
            comm_controllers = util.xml_elem_findall(src_ecu_instance, 'CAN-COMMUNICATION-CONTROLLER')
            for comm in comm_controllers:
                update_refs(comm)  # Update references in the source element

            # CORRECTED: Pass ARXML docs and destination parent
            util.xml_elem_extend(
                src_elems=comm_controllers,
                dst_elems=dst,  # Destination parent element (COMM-CONTROLLERS)
                src_arxml=src_arxml,
                dst_arxml=dst_arxml,
                graceful=True
            )

        elif tag == 'CONNECTORS':
            # Get CAN connectors from source
            connectors = util.xml_elem_findall(src_ecu_instance, 'CAN-COMMUNICATION-CONNECTOR')
            for conn in connectors:
                update_refs(conn)

            # CORRECTED: Pass ARXML docs and destination parent
            util.xml_elem_extend(
                src_elems=connectors,
                dst_elems=dst,  # Destination parent element (CONNECTORS)
                src_arxml=src_arxml,
                dst_arxml=dst_arxml,
                graceful=True
            )

def copy_vehicletopology_packages(src_arxml, dst_arxml):
    # Get source and destination packages
    src_vehicletopology = util.xml_ar_package_find(src_arxml.xml.getroot(), 'VehicleTopology')
    dst_vehicletopology = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'VehicleTopology')
    can_cluster_list = []
    # Fetch the can cluster from the can dp arxml
    can_clusters = util.xml_elem_findall(src_vehicletopology, 'CAN-CLUSTER')
    for can_cluster in can_clusters:
        veh_sec_can_package = util.xml_ar_package_find(dst_vehicletopology, 'HIAsystemVehSecCANMAIN')
        if veh_sec_can_package is None:
            veh_sec_can_package = factory.xml_ar_package_create('HIAsystemVehSecCANMAIN', str(uuid.uuid4()) +
                                                '-vehicletopology-' + 'HIAsystemVehSecCANMAIN')
            logging.info(" Copying CAN Cluster %s to %s",  util.xml_elem_find(can_cluster, 'SHORT-NAME').text, veh_sec_can_package[0].text)
            util.xml_elem_append(veh_sec_can_package[1], can_cluster, dst_arxml.parents)
            util.xml_elem_append(dst_vehicletopology[1], veh_sec_can_package, dst_arxml.parents)
        else:
            logging.info(" Copying CAN Cluster %s to %s",  util.xml_elem_find(can_cluster, 'SHORT-NAME').text, veh_sec_can_package[0].text)
            util.xml_elem_append(veh_sec_can_package[1], can_cluster, dst_arxml.parents)

        update_refs(veh_sec_can_package)
        # Return CAN-PHYSICAL-CHANNEL name
        can_cluster_list.append(util.xml_elem_find(can_cluster,'CAN-PHYSICAL-CHANNEL')[0].text)
    return can_cluster_list


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
            pdus_to_copy = []
            pdus_to_copy.extend(util.xml_elem_findall(src_com, 'I-SIGNAL-I-PDU'))
            pdus_to_copy.extend(util.xml_elem_findall(src_com, 'NM-PDU'))
            util.assert_elem_tag(dst[1], 'ELEMENTS')
            util.xml_elem_extend(pdus_to_copy, dst[1], src_arxml, dst_arxml, graceful=True)
            # Save isignal pdus for pdu filtering
            pdus = [pdu[0].text for pdu in pdus_to_copy]
            # Fetch the pdu length and the pdu name
            isig_pdus_len = [(util.xml_elem_find(pdu, "LENGTH").text, pdu[0].text) for pdu in pdus_to_copy]
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

def get_filtered_frames(src, disallowed_pdu_names):
    """
    Returns only the CAN-FRAME elements from 'src' that do NOT reference disallowed PDUs.
    """
    frames_to_copy = []
    for frame_elem in util.xml_elem_findall(src, 'CAN-FRAME') or []:
        pdu_ref_elem = util.xml_elem_find(frame_elem, 'PDU-REF')
        if pdu_ref_elem is not None:
            pdu_name = pdu_ref_elem.text.split('/')[-1]
            if pdu_name in disallowed_pdu_names:
                continue  # Skip disallowed PDU references
        frames_to_copy.append(frame_elem)
    return frames_to_copy


def copy_fibex_elements(src_arxml, dst_arxml, pdus):
    # Copy source to destination Communication related Fibex elements
    # found in _COMMUNICATION_PACKAGES_
    # Filter Pdu related Fibex elements via provided pdus list

    # Get source and destination packages
    src_vp = util.xml_ar_package_find(src_arxml.xml.getroot(), 'VehicleProject')
    assert src_vp is not None, "Source VehicleProject package is not found!"
    dst_vp = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'VehicleProject')
    assert dst_vp is not None, "Destination VehicleProject "\
                               "package is not found!"
    src_fibex = util.xml_elem_find(src_vp, 'FIBEX-ELEMENTS')
    assert src_fibex is not None, "Source VehicleProject:FIBEX-ELEMENTS "\
                                  "is not found!"
    dst_fibex = util.xml_elem_find(dst_vp, 'FIBEX-ELEMENTS')
    assert dst_fibex is not None, "Destination VehicleProject:FIBEX-ELEMENTS "\
                                  "is not found!"
    # Create filter list as a combination of subpaths of a non-Pdu
    # Communication packages and given pdus
    fib_paths = ['/Communication/' + name for name in
                 _COMMUNICATION_PACKAGES_ if name != 'Pdu'] + pdus
    logging.debug("Fibex filter paths: %s", fib_paths)
    # Handling nested FIBEX-ELEMENT-REF
    fibex_refs = src_fibex.findall('.// '+ autosar.base.add_schema('FIBEX-ELEMENT-REF'))
    fibex_conditional_refs = src_fibex.findall(".//" + autosar.base.add_schema('FIBEX-ELEMENT-REF-CONDITIONAL'))
    logging.info("Found  %d FIBEX-ELEMENT-REF-CONDITIONALs", len(fibex_conditional_refs))
    # Get filtered Fibex elements list
    elems = [fibex for fibex in fibex_refs
             if any(path in fibex[0].text for path in fib_paths)]
    cond_elems = [fibex for fibex in fibex_conditional_refs
             if any(path in util.xml_elem_find(fibex, 'FIBEX-ELEMENT-REF').text for path in fib_paths)]
    # Copy source elements
    util.xml_elem_extend(list(elems), dst_fibex, src_arxml, dst_arxml)
    util.xml_elem_extend(list(cond_elems), dst_fibex, src_arxml, dst_arxml)


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
    # Get source and destination isignal triggerings which exists only for CAN-COMMUNICATION-CONNECTOR
    if "ETHERNET" not in src_ch.tag:
        src_trig = util.xml_elem_find(src_ch, 'I-SIGNAL-TRIGGERINGS')
        assert src_trig is not None, "Source %s:I-SIGNAL-TRIGGERINGS "\
                                 "is not found!" % _CHANNEL_MAPPING_[1]
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
    # Get source and destination pdu triggerings
    src_trig = util.xml_elem_find(src_ch, 'PDU-TRIGGERINGS')
    assert src_trig is not None, "Source %s:PDU-TRIGGERINGS "\
                                 "is not found!" % _CHANNEL_MAPPING_[0]
    dst_trig = util.xml_elem_find(dst_ch, 'I-SIGNAL-TRIGGERINGS')
    # Remove non-relevant pdu triggerings
    util.xml_elem_child_remove_all(
        src_trig,
        [trig for trig in src_trig
         if util.xml_elem_find(trig, 'I-PDU-REF') is not None
         and util.xml_elem_find(trig, 'I-PDU-REF').text is not None
         and util.xml_elem_find(trig, 'I-PDU-REF').text.split('/')[-1] in _DISALLOWED_PDU_NAMES_])
    # Remove non-relevant PDU triggerings (those not in the allowed pdus list)
    util.xml_elem_child_remove_all(
        src_trig,
        [trig for trig in src_trig if not any(pdu in trig[0].text for pdu in pdus)])
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
    path_map.update(util.xml_elem_extend(list(src_trig), dst_trig,
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
    # Copies an Ethernet DP's NetworkEndpoint to given destination channel
    # Note that this function makes the following assumptions:
    # - src_arxml contains only two NetworkEndpoints (its own and HIx's)
    # - dst_arxml always has at least one NetworkEndpoint (HIx's)
    # - each NetworkEndpoint only contains one IPV4Configuration
    # Get source and destination Ethernet channels
    src_ch = util.xml_elem_find(src_arxml.xml.getroot(),
                           'ETHERNET-PHYSICAL-CHANNEL')
    assert src_ch is not None,\
        "Source element 'ETHERNET-PHYSICAL-CHANNEL' is not found!"
    dst_ch = xml_get_physical_channel(dst_arxml,
                                      'ETHERNET-PHYSICAL-CHANNEL',
                                      dst_eth_physical_channel)
    assert dst_ch is not None,\
        "Destination element 'ETHERNET-PHYSICAL-CHANNEL' is  not found!"
    # Get network endpoints
    src_net_ends = util.xml_elem_find(src_ch, 'NETWORK-ENDPOINTS')
    assert src_net_ends is not None,\
        "Source element 'NETWORK-ENDPOINTS' is not found!"
    dst_net_ends = util.xml_elem_find(dst_ch, 'NETWORK-ENDPOINTS')
    assert dst_net_ends is not None,\
        "Destination element 'NETWORK-ENDPOINTS' is not found!"

    # Function to check if an element is a nested NETWORK-ENDPOINTS
    def is_nested_network_endpoints(element):
        return element.tag == '{http://autosar.org/schema/r4.0}NETWORK-ENDPOINTS'

    # Filter out nested NETWORK-ENDPOINTS elements from src_net_ends
    filtered_src_net_ends = [elem for elem in src_net_ends if not is_nested_network_endpoints(elem)]
    # Extend destination network endpoints list with source network
    # endpoints list. Detect conflicts by looking at 'IPV-4-ADDRESS'.
    path_map = util.xml_elem_extend(
        filtered_src_net_ends, dst_net_ends,
        src_arxml, dst_arxml,
        src_name=lambda el: util.xml_elem_find(el, 'IPV-4-ADDRESS').text,
        dst_name=lambda el: util.xml_elem_find(el, 'IPV-4-ADDRESS').text,
        graceful=True)
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
        # Ensure client_port_ref.text is in sock_addr_map before assignment
        if client_port_ref and client_port_ref.text in sock_addr_map:
            client_port_ref.text = sock_addr_map[client_port_ref.text]
        else:
            logging.warning("CLIENT-PORT-REF '%s' not found in sock_addr_map "
                            "for bundle '%s'. Original reference retained.",
                            client_port_ref.text, util.xml_elem_find(sock_conn_bundle, 'SHORT-NAME').text)


        server_port_ref = util.xml_elem_find(sock_conn_bundle,
                                             'SERVER-PORT-REF')
        # Ensure server_port_ref.text is in sock_addr_map before assignment
        if server_port_ref and server_port_ref.text in sock_addr_map:
            server_port_ref.text = sock_addr_map[server_port_ref.text]
        else:
            logging.warning("SERVER-PORT-REF '%s' not found in sock_addr_map "
                            "for bundle '%s'. Original reference retained.",
                            server_port_ref.text, util.xml_elem_find(sock_conn_bundle, 'SHORT-NAME').text)

        pdu_trig_refs = util.xml_elem_findall(sock_conn_bundle,
                                               'PDU-TRIGGERING-REF')
        for pdu_trig_ref in pdu_trig_refs:
            # THIS IS THE KEY CHANGE FOR OPTION 3:
            # Check if the reference exists in the map before attempting to use it.
            if pdu_trig_ref.text in isig_pdu_path_map:
                pdu_trig_ref.text = isig_pdu_path_map[pdu_trig_ref.text]
            else:
                logging.warning("PDU-TRIGGERING-REF '%s' not found in isig_pdu_path_map. "
                                "For bundle '%s'. Original reference retained (this may cause issues downstream).",
                                pdu_trig_ref.text, util.xml_elem_find(sock_conn_bundle, 'SHORT-NAME').text)

    #util.xml_elem_child_remove_all(dst_sock_conn_bundles, [socket for socket in dst_sock_conn_bundles
    #                              if util.xml_elem_find(socket, 'HEADER-ID') is None])
    # Extend destination socket connection bundle list with source socket
    # connection bundle list. Detect conflicts by looking at 'HEADER-ID'.
    util.xml_elem_extend(src_sock_conn_bundles, dst_sock_conn_bundles,
                         src_arxml, dst_arxml,
                         src_name=lambda el: util.xml_elem_find(el, 'HEADER-ID').text,
                         dst_name=lambda el: util.xml_elem_find(el, 'SHORT-NAME').text, graceful=True)


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
    # Get network endpoint path
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


def fetch_can_frame_triggering_info(src_arxml, is_mrcom_arxml):
    # Iterate through CAN-FRAME-TRIGGERINGs and fetch
    # information about the frame's name, behaviour and
    # identifier
    # Returns dictionary with the frames information
    can_frames = {}
    frames = util.xml_elem_findall(src_arxml.xml.getroot(), 'CAN-FRAME-TRIGGERING')
    for frame in frames:
        # Integrity check
        util.assert_elem_tag(frame[0], 'SHORT-NAME')
        util.assert_elem_tag(frame[2], 'FRAME-REF')
        util.assert_elem_tag(frame[4], 'CAN-ADDRESSING-MODE')
        util.assert_elem_tag(frame[5], ('CAN-FRAME-RX-BEHAVIOR',
                                   'CAN-FRAME-TX-BEHAVIOR'))
        util.assert_elem_tag(frame[6], 'IDENTIFIER')
        # Let's figure out which pdu is referenced by this frame
        # triggering so we can save packing order and pdu reference
        # Get frame name from the ref
        name = frame[2].text[frame[2].text.rfind('/') + 1:]
        # Get can frame
        src_frame = util.xml_elem_type_find(src_arxml.xml.getroot(),
                                       'CAN-FRAME', name)
        assert src_frame is not None, "Source CAN-FRAME:%s is not found!"\
                                      % name
        src_map = util.xml_elem_find(src_frame, 'PDU-TO-FRAME-MAPPINGS')
        assert src_map is not None, "Source CAN-FRAME:PDU-TO-FRAME-MAPPINGS "\
                                    "is not found!"
        assert len(src_map) == 1, "Invalid number of PDU-TO-FRAME-MAPPINGs "\
                                  "in the CAN-FRAME:%s!" % name
        # Get first and only child
        src_map = src_map[0]
        # Integrity check
        util.assert_elem_tag(src_map[2], 'PDU-REF')
        # Finally, add entry
        pdu = src_map[2].text[src_map[2].text.rfind('/') + 1:]
        assert can_frames.get(pdu, None) is None, "The entry already "\
                                                  "exist with name %s!" % pdu
        if is_mrcom_arxml:
            packing = ''
            ipdu = util.xml_elem_type_find(src_arxml.xml.getroot(),
                                    'I-SIGNAL-I-PDU', pdu)
            if ipdu is not None:
                imap = util.xml_elem_find(ipdu, 'I-SIGNAL-TO-I-PDU-MAPPING')
                assert imap is not None, "Source I-SIGNAL-I-PDU:"\
                                        "I-SIGNAL-TO-I-PDU-MAPPING is not found!"
                util.assert_elem_tag(imap[2], 'PACKING-BYTE-ORDER')
                packing = imap[2].text
            # Order items by pdu (reference)
            can_frames[pdu] = {'name': frame[0].text,
                            'mode': frame[4].text,
                            'type': frame[5].text,
                            'tx': util.is_elem_tag(frame[5],
                                                'CAN-FRAME-TX-BEHAVIOR'),
                            'id': frame[6].text,
                            'packing': packing}
    return can_frames


def add_mr_com_flavour(dst_arxml, can_frames, can_pdus,
                       dst_eth_physical_channel):
    # Add MR COM protocol support by enriching dst_arxml with
    # relevant data
    dst_sig = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'Signal')
    assert dst_sig is not None, "Destination Signal package is not found!"
    # Add Signal
    desc = "Contains packet type and control flag for MR Comm protocol"
    sig = factory.xml_system_signal_create('MrCommHdrPartB', desc)
    util.assert_elem_tag(dst_sig[1], 'ELEMENTS')
    util.xml_elem_extend(sig, dst_sig[1], dst_arxml, dst_arxml,
                    src_name=lambda el: el.text,
                    dst_name=lambda el: el.text)
    dst_isig = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'ISignal')
    assert dst_isig is not None, "Destination ISignal package is not found!"
    dst_pdu = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'Pdu')
    assert dst_pdu is not None, "Destination Pdu package is not found!"
    dst_ch = xml_get_physical_channel(dst_arxml, _CHANNEL_MAPPING_[1],
                                      dst_eth_physical_channel)
    assert dst_ch is not None, "Destination element %s is "\
                               "not found!" % _CHANNEL_MAPPING_[1]
    dst_trigs = util.xml_elem_find(dst_ch, 'I-SIGNAL-TRIGGERINGS')
    assert dst_trigs is not None, "Destination %s:I-SIGNAL-TRIGGERINGS "\
                                  "is not found!" % _CHANNEL_MAPPING_[0]
    dst_vp = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'VehicleProject')
    assert dst_vp is not None, "Destination VehicleProject "\
                               "package is not found!"
    dst_fibex = util.xml_elem_find(dst_vp, 'FIBEX-ELEMENTS')
    assert dst_fibex is not None, "Destination VehicleProject:FIBEX-ELEMENTS "\
                                  "is not found!"
    # Find CommunicationConnector associated with Channel
    connector_ref = util.xml_elem_find(dst_ch, 'COMMUNICATION-CONNECTOR-REF')
    assert connector_ref is not None,\
        "Could not find 'COMMUNICATION-CONNECTOR-REF' in %s channel"\
        % dst_eth_physical_channel
    connector_name = connector_ref.text[connector_ref.text.rfind('/')+1:]
    for connector in util.xml_elem_findall(dst_arxml.xml.getroot(),
                                      'ETHERNET-COMMUNICATION-CONNECTOR'):
        if connector[0].text == connector_name:
            dst_path = connector
            break
    assert dst_path is not None, \
        "Could not find 'ETHERNET-COMMUNICATION-CONNECTOR' %s referenced by"\
        " %s channel" % (connector_name, dst_eth_physical_channel)
    dst_ports = util.xml_elem_findall(dst_path, 'I-SIGNAL-PORT')
    assert dst_ports is not None, "Destination I-SIGNAL-PORT "\
                                  "is not found!"
    pdu_trigs = util.xml_elem_find(dst_ch, 'PDU-TRIGGERINGS')
    assert pdu_trigs is not None, "Destination %s:PDU-TRIGGERINGS "\
                                  "is not found!" % _CHANNEL_MAPPING_[1]
    for index, pdu in enumerate(can_pdus):
        # Add iSignal
        _args = ['32',
                 '/DataType/DataTypeSemantics/SwBaseTypes/SIGMrCommHdrPartB',
                 '/DataType/DataTypeSemantics/uint32',
                 util.xml_elem_get_abs_path(sig, dst_arxml)]
        key = can_frames[pdu]['type'], can_frames[pdu]['mode']
        if can_frames[pdu]['packing'] == 'MOST-SIGNIFICANT-BYTE-FIRST':
            isig = factory.xml_isignal_create(_ISIGNAL_INIT_VAL_BIGEND[key][1] + str(index),
                                      _ISIGNAL_INIT_VAL_BIGEND[key][0], *_args)
        else:
            isig = factory.xml_isignal_create(_ISIGNAL_INIT_VAL_LTLEND_[key][1] + str(index),
                                      _ISIGNAL_INIT_VAL_LTLEND_[key][0], *_args)
        util.xml_elem_extend(isig, dst_isig[1], dst_arxml, dst_arxml,
                        src_name=lambda el: el.text,
                        dst_name=lambda el: el.text, graceful=True)
        # Add I-SIGNAL-TO-PDU-MAPPING to each Pdu
        ipdu = util.xml_elem_type_find(dst_pdu, 'I-SIGNAL-I-PDU', pdu)
        assert ipdu is not None, "Destination I-SIGNAL-I-PDU:%s is not found!"\
                                 % pdu
        pdu_maps = util.xml_elem_find(ipdu, 'I-SIGNAL-TO-PDU-MAPPINGS')
        assert pdu_maps is not None, "Destination %s:I-SIGNAL-TO-PDU-MAPPINGS"\
                                     " is not found!" % pdu_maps
        # Offset start position by 32
        for pdu_map in pdu_maps:
            util.assert_elem_tag(pdu_map[3], 'START-POSITION')
            pdu_map[3].text = str(int(pdu_map[3].text) + 32)
            # check for UPDATE-INDICATION-BIT-POSITION
            upd_bit = util.xml_elem_find(pdu_map, 'UPDATE-INDICATION-BIT-POSITION')
            if upd_bit is not None:
                upd_bit.text = str(int(upd_bit.text) + 32)
        # Update IPDU length
        length = util.xml_elem_find(ipdu, 'LENGTH')
        assert length is not None, "Destination I-SIGNAL-I-PDU:LENGTH "\
                                   "is not found!"
        length.text = str(int(length.text) + 4)
        # Add new entry
        _args = [isig[0].text + ('_mtx' if can_frames[pdu]['tx'] else '_mrx'),
                 util.xml_elem_get_abs_path(isig, dst_arxml),
                 can_frames[pdu]['packing'],
                 '7' if can_frames[pdu]['packing'] ==
                 'MOST-SIGNIFICANT-BYTE-FIRST' else 0,
                 'PENDING']
        isig_map = factory.xml_isignal_to_ipdu_mapping_create(*_args)
        util.xml_elem_extend(isig_map, pdu_maps, dst_arxml, dst_arxml,
                        src_name=lambda el: el.text,
                        dst_name=lambda el: el.text,graceful=True)
        # Add I-SIGNAL-TRIGGERINGs for each ISignal
        isig_trigs = {}
        for index, port in enumerate(dst_ports):
            _args = [isig[0].text + '_' + str(index),
                     util.xml_elem_get_abs_path(port, dst_arxml),
                     util.xml_elem_get_abs_path(isig, dst_arxml)]
            direction = port[0].text[port[0].text.rfind('_') + 1:]
            isig_trigs[direction] = factory.xml_isignal_triggering_create(*_args)
            util.xml_elem_extend(isig_trigs[direction], dst_trigs, dst_arxml,
                            dst_arxml, src_name=lambda el: el.text,
                            dst_name=lambda el: el.text)
        # Add FIBEX-ELEMENT-REF-CONDITIONAL referencing new ISignals
        signal_ref = util.xml_elem_get_abs_path(isig, dst_arxml)
        fibex = factory.xml_fibex_elem_ref_conditional_create(signal_ref)
        util.xml_elem_extend(fibex, dst_fibex, dst_arxml, dst_arxml,
                        src_name=lambda el: el.text,
                        dst_name=lambda el: el.text)
        # Add I-SIGNAL-TRIGGERING-REF to PDU-TRIGGERING:I-SIGNAL-TRIGGERINGS
        dst_trig = [trig for trig in pdu_trigs if pdu == trig[0].text.replace('PduTr', '')]
        assert len(dst_trig) == 1, "The %s can't be matched in destination "\
                                   "%s:PDU-TRIGGERINGS "\
                                   % (pdu, _CHANNEL_MAPPING_[1])
        trig = dst_trig[0]
        util.assert_elem_tag(trig[1], 'I-PDU-PORT-REFS')
        assert len(trig[1]) == 1, "Invalid number of I-PDU-PORT-REFs "\
                                  "in the PDU-TRIGGERING:%s!" % trig[0].text
        util.assert_elem_tag(trig[3], 'I-SIGNAL-TRIGGERINGS')
        direction = trig[1][0].text[trig[1][0].text.rfind('_') + 1:]
        signal_ref = util.xml_elem_get_abs_path(isig_trigs[direction], dst_arxml)
        ref = factory.xml_isignal_triggering_ref_conditional_create(signal_ref)
        util.xml_elem_extend(ref, trig[3], dst_arxml, dst_arxml,
                        src_name=lambda el: el.text,
                        dst_name=lambda el: el.text)


def fix_ihfa_ihra_naming(src_arxml):
    prefix_map = {
        "IHFA": "IHFA",
        "IHRA": "IHRA",
        "TVRR": "TVRR",
        "TVRL": "TVRL",
    # prefix every relevant element in these .arxmls with the name of the node.
    # This function goes through various Autosar elements and adds this prefix.
        "PSCM": "PSCM",
		"RBCM": "RBCM",
        "SRSR": "SRSR",
		"TSTA": "TSTA",
		"TSTC": "TSTC",
		"TSTE": "TSTE",
		"TSTG": "TSTG",
		"TSTI": "TSTI",
		"TSTK": "TSTK",
        "TSYNC_HPA": "TSYNCHPA",
        "TSYNC_HPB": "TSYNCHPB",
		    }
    prefix = None
    for key, val in prefix_map.items():
        if key in src_arxml.filename:
            prefix = val
            break
    if not prefix:
        return
    # We want to do the renaming in the entire .arxml so we start from the root
    parent_elem = src_arxml.xml.getroot()

    # Globally apply prefix to elements and their corresponding references.
    for elem_type in ['I-SIGNAL', 'I-SIGNAL-GROUP', 'I-SIGNAL-TRIGGERING']:
        util.add_prefix_to_elements_of_type(parent_elem, prefix, elem_type)
    for ref_type in ['I-SIGNAL-REF', 'I-SIGNAL-GROUP-REF', 'I-SIGNAL-TRIGGERING-REF']:
        util.add_prefix_to_refs_of_type(parent_elem, prefix, ref_type)

    # Update only the FIBEX-ELEMENT-REFs which point to I-SIGNALs
    util.add_prefix_to_refs_of_type(
        parent_elem,
        prefix,
        'FIBEX-ELEMENT-REF',
        has_property=lambda ref: ref.text.startswith("/Communication/ISignal/") or
                                 ref.text.startswith("/Communication/ISignalGroup/")
    )


def update_isignal_and_pdu_triggerings(src_arxml,
                                     dst_arxml,
                                     dst_physical_channel):
    # Copy source to destination I-SIGNAL-TRIGGERINGS and PDU-TRIGGERINGS
    # Updates triggering's references from src_path to dst_path
    # Filter Pdu related triggering elements via provided pdus list
    # Get source and destination channels
    if "SRSR" in src_arxml.filename:
        src_channels = util.xml_elem_findall(src_arxml.xml.getroot(), _CHANNEL_MAPPING_[0])
    else:
        src_ch = util.xml_elem_find(src_arxml.xml.getroot(), _CHANNEL_MAPPING_[0])
        assert src_ch is not None, "Source element %s is not found!" \
                                    % _CHANNEL_MAPPING_[0]
    dst_ch = xml_get_physical_channel(dst_arxml, _CHANNEL_MAPPING_[0],
                                      dst_physical_channel)
    assert dst_ch is not None, "Destination element %s is "\
                               "not found!" % _CHANNEL_MAPPING_[0]
    # Sync isignal triggerings
    #
    for src_ch in src_channels if "SRSR" in src_arxml.filename else [src_ch]:
        if "AD75E191479D3ED93701AD79EC7F37E8" == src_ch[0].text:
            pass
        else:
            logging.info("Syncing I-SIGNAL-TRIGGERINGS and PDU-TRIGGERINGS for %s" , src_ch[0].text)
            # Get source and destination isignal triggerings
            src_trig = util.xml_get_child_elem_by_tag(src_ch, 'I-SIGNAL-TRIGGERINGS')
            assert src_trig is not None, "Source %s:I-SIGNAL-TRIGGERINGS "\
                                        "is not found!" % _CHANNEL_MAPPING_[0]
            dst_trig = util.xml_elem_find(dst_ch, 'I-SIGNAL-TRIGGERINGS')
            if dst_trig is None:
                dst_trig = factory.xml_isignal_triggerings_create()
                util.xml_elem_append(dst_ch, dst_trig, dst_arxml.parents)
            refs = util.xml_elem_findall(src_trig, 'I-SIGNAL-PORT-REF')
            assert refs is not None, "There is no I-SIGNAL-PORT-REF refs found "\
                                    "for I-SIGNAL-TRIGGERINGS!"
        # Get path transformers
        src_ecpi = util.xml_elem_find(src_arxml.xml.getroot(),
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
        if "AD75E191479D3ED93701AD79EC7F37E8" == src_ch[0].text:
            pass
        else:
            src_trig = util.xml_elem_find(src_ch, 'I-SIGNAL-TRIGGERINGS')
            assert src_trig is not None, "Source %s:I-SIGNAL-TRIGGERINGS "\
                                        "is not found!" % _CHANNEL_MAPPING_[0]
            dst_trig = util.xml_elem_find(dst_ch, 'I-SIGNAL-TRIGGERINGS')
            assert dst_trig is not None, "Destination %s:I-SIGNAL-TRIGGERINGS "\
                                        "is not found!" % _CHANNEL_MAPPING_[0]
            refs = util.xml_elem_findall(src_trig, 'I-SIGNAL-PORT-REF')
            assert refs is not None, "There is no I-SIGNAL-PORT-REF refs found "\
                                    "for I-SIGNAL-TRIGGERINGS!"
        # Transform signal port refs
        #util.xml_ref_transform_all(refs, src_path, dst_path)
        # Sync pdu triggerings
        #
        # Get source and destination pdu triggerings
        src_trig = util.xml_get_child_elem_by_tag(src_ch, 'PDU-TRIGGERINGS')
        assert src_trig is not None, "Source %s:PDU-TRIGGERINGS "\
                                    "is not found!" % _CHANNEL_MAPPING_[0]
        dst_trig = util.xml_elem_find(dst_ch, 'PDU-TRIGGERINGS')
        assert dst_trig is not None, "Destination %s:PDU-TRIGGERINGS "\
                                    "is not found!" % _CHANNEL_MAPPING_[0]
        # Remove non-relevant pdu triggerings
        util.xml_elem_child_remove_all(src_trig, [trig for trig in src_trig
                                             if not any(pdu in trig[0].text
                                                      for pdu in fetch_pdu(src_arxml))])
        # Transform pdu port refs
        refs = util.xml_elem_findall(src_trig, 'I-PDU-PORT-REF')
        assert refs is not None, "There is no I-PDU-PORT-REF refs found "\
                                "for PDU-TRIGGERINGS!"
        #util.xml_ref_transform_all(refs, src_path, dst_path)
        # Sync frame triggerings
        #
        # Get source and destination frame triggerings
        src_trig = util.xml_get_child_elem_by_tag(src_ch, 'FRAME-TRIGGERINGS')
        assert src_trig is not None, "Source %s:FRAME-TRIGGERINGS " \
                                    "is not found!" % _CHANNEL_MAPPING_[0]
        dst_trig = util.xml_elem_find(dst_ch, 'FRAME-TRIGGERINGS')
        assert dst_trig is not None, "Destination %s:FRAME-TRIGGERINGS " \
                                    "is not found!" % _CHANNEL_MAPPING_[0]
        # Remove non-relevant frame triggerings
        util.xml_elem_child_remove_all(src_trig, [trig for trig in src_trig
                                             if not any(frame in trig[0].text
                                                      for frame in fetch_can_frame(src_arxml ))])


def fetch_can_frame(src_arxml):
    # Fetch CAN frames carrying I-SIGNAL PDUs from the Communication package in src_arxml
    # Returns list of CAN-FRAME names with I-SIGNAL-I-PDU references

    # Locate the Communication package in the source ARXML
    src_com = util.xml_ar_package_find(src_arxml.xml.getroot(), 'Communication')
    assert src_com is not None, "Source Communication package is not found!"

    frames = []
    # Find all CAN-FRAME elements under the Communication package
    can_frames = util.xml_elem_findall(src_com, 'CAN-FRAME')
    for frame in can_frames:
        # Find the PDU reference inside the CAN-FRAME
        pdu_ref_elem = util.xml_elem_find(frame, 'PDU-REF')
        if pdu_ref_elem is not None:
            # Check if this PDU-REF points to an I-SIGNAL-I-PDU
            if pdu_ref_elem.attrib.get('DEST') in ['I-SIGNAL-I-PDU', 'NM-PDU']:
                # Append the CAN-FRAME's name (SHORT-NAME text) to the result list
                frames.append(frame[0].text)
    return frames

def add_swbasetype_arpackage(swc_dp_arxmls,dst_arxml):
    # Create a new AR package - DataType in com_merged arxml
    dst_datatype = factory.xml_ar_package_create('DataType', str(uuid.uuid4()) +
                                        '-DataType')
    util.xml_elem_add_ar_packages(dst_datatype, dst_arxml.parents)
    util.xml_elem_append(dst_arxml.xml.getroot()[0], dst_datatype, dst_arxml.parents)
    # Get destination Datatype package
    dst_datatype_package = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'DataType')
    # Create and add a new AR package - DataTypeSemantics as a child in Datatype package
    dst = factory.xml_ar_package_create('DataTypeSemantics', str(uuid.uuid4()) +
                                        '-DataType-DataTypeSemantics')
    util.xml_elem_add_ar_packages(dst, dst_arxml.parents)
    util.xml_elem_append(dst_datatype_package[2], dst, dst_arxml.parents)
    for arxml in swc_dp_arxmls:
        src_arxml = autosar.arxml.load(arxml)
        # Get source package
        src_swbasetype = util.xml_ar_package_find(src_arxml.xml.getroot(), 'SwBaseTypes')
        assert src_swbasetype is not None, "Source SwBaseTypes package is not found!"
        if arxml == swc_dp_arxmls[0]:
            swc_patcher.add_native_declaration_to_base_types(src_arxml)
        # Copy SwBaseTypes in destination arxml
        util.xml_ar_package_copy(src_swbasetype, dst[2], src_arxml, dst_arxml)

def copy_ecpi_to_ethernet_connectors(dst_arxml):
    # Find all Ethernet-communication-connector elements
    ethernet_connectors = util.xml_elem_findall(dst_arxml.xml.getroot(), 'ETHERNET-COMMUNICATION-CONNECTOR')
    # Find the ECU-COMM-PORT-INSTANCES element
    dst_ecpi = util.xml_elem_find(dst_arxml.xml.getroot(), 'ECU-COMM-PORT-INSTANCES')
    assert dst_ecpi is not None, "Source element ECU-COMM-PORT-INSTANCES is not found!"
    # Loop through each Ethernet-communication-connector
    for connector in ethernet_connectors:
        # Check if the connector already has an ECU-COMM-PORT-INSTANCES element
        existing_ecpi = util.xml_elem_find(connector, 'ECU-COMM-PORT-INSTANCES')
        if existing_ecpi is None:
            # Create a deep copy of the original tag
            copied_ecpi = copy.deepcopy(dst_ecpi)
            # Insert the ECU-COMM-PORT-INSTANCES element to the Ethernet-communication-connector at third index
            util.xml_elem_append_at_index(connector, copied_ecpi, 3, dst_arxml.parents)


def add_transfer_property_to_signals(dst_arxml):
    # Iterate over all I-SIGNAL-TO-I-PDU-MAPPING elements in the source tree
    for mapping in util.xml_elem_findall(dst_arxml.xml.getroot(), 'I-SIGNAL-TO-I-PDU-MAPPING'):
        # Check if it's an individual signal (i.e., not a signal group)
        is_signal_group = util.xml_elem_find(mapping, 'I-SIGNAL-GROUP-REF') is not None
        if not is_signal_group:
            # Check the SHORT-NAME to see if it's an RX signal
            short_name = util.xml_elem_find(mapping, 'SHORT-NAME').text
            if not short_name.endswith('_mrx'):
            # Check if TRANSFER-PROPERTY exists
                transfer_property = util.xml_elem_find(mapping, 'TRANSFER-PROPERTY')
                if transfer_property is None:
                    # Add TRANSFER-PROPERTY with value PENDING
                    transfer_property = ET.Element('TRANSFER-PROPERTY')
                    transfer_property.text = 'PENDING'
                    mapping.append(transfer_property)
    # Save the updated destination tree back to the file
    dst_arxml.save(dst_arxml.filename)

def process_gateway_and_remove_signals(src_arxml, dst_arxml):
    gateway_package = util.xml_ar_package_find(src_arxml.xml.getroot(), 'Gateway')
    if not gateway_package:
        logging.info("No Gateway AR-PACKAGE found.")
        return
    # Dictionary to store source to target PDU mappings
    pdu_mappings = {}
    # Extracting all mappings from the Gateway package
    gateways = util.xml_elem_findall(gateway_package, 'GATEWAY')
    for gateway in gateways:
        mappings = util.xml_elem_findall(gateway, 'I-PDU-MAPPING')
        for mapping in mappings:
            source_pdu_ref = util.xml_elem_find(mapping, 'SOURCE-I-PDU-REF').text
            target_pdu_ref = util.xml_elem_find(mapping, 'TARGET-I-PDU').find('TARGET-I-PDU-REF').text
            pdu_mappings[source_pdu_ref] = target_pdu_ref
    # Now process each PDU-TRIGGERING in the destination ARXML
    pdu_triggerings = util.xml_elem_findall(dst_arxml.xml.getroot(), 'PDU-TRIGGERING')
    for pdu_trig in pdu_triggerings:
        # Check if this PDU-TRIGGERING is a target in any of the mappings
        pdu_ref = util.xml_elem_find(pdu_trig, 'I-PDU-REF').text
        if pdu_ref in pdu_mappings.values():
            # This is a target PDU, process its I-SIGNAL-TRIGGERINGS
            i_signal_triggerings = util.xml_elem_find(pdu_trig, 'I-SIGNAL-TRIGGERINGS')
            if i_signal_triggerings:
                for i_signal_trig in list(i_signal_triggerings):
                    ref = util.xml_elem_find(i_signal_trig, 'I-SIGNAL-TRIGGERING-REF')
                    if ref and ref.text in pdu_mappings:  # Check if this I-SIGNAL should be removed
                        i_signal_triggerings.remove(i_signal_trig)
                        logging.info("Removed I-SIGNAL-TRIGGERING {ref.text} as it is linked to a mapped PDU")


def update_reference(ref):
    # Define patterns and replacements
    patterns = [
        (r'/ECUExtract\w+/VehicleProject/\w+/\w+[sS]warch', '/ECUExtractHIC/VehicleProject/HIASystem/HIAswarch'),
        (r'/ECUExtract\w+/ComponentType/\w+[sS]warch/\w+MAIN', '/ECUExtractHIC/ComponentType/HIAswarch/HICMAIN'),
        (r'/ComponentType/\w+/\w+MAIN/\w+', '/ComponentType/HIC/HICMAIN/HIC'),
        # Add more patterns and replacements as needed
    ]
    for pattern, replacement in patterns:
        if re.match(pattern, ref, flags=re.IGNORECASE):
            ref = re.sub(pattern, replacement, ref)
    return ref

def copy_and_append_data_mappings(src_arxml, dest_arxml):

    # Get the root elements
    src_root = src_arxml.xml.getroot()
    dest_root = dest_arxml.xml.getroot()

    # Find the DATA-MAPPINGS element in the source ARXML
    src_mappings = src_root.find('.//ns:DATA-MAPPINGS', NAMESPACE)
    if src_mappings is None:
        logging.warning("No DATA-MAPPINGS found in source ARXML")
        return

    # Find or create the DATA-MAPPINGS element in the destination ARXML
    dest_mappings = dest_root.find('.//ns:DATA-MAPPINGS', NAMESPACE)
    if dest_mappings is None:
        system_mapping = dest_root.find('.//ns:SYSTEM-MAPPING', NAMESPACE)
        if system_mapping is None:
            logging.warning("No SYSTEM-MAPPING found in destination ARXML")
            return
        dest_mappings = ET.SubElement(system_mapping, '{http://autosar.org/schema/r4.0}DATA-MAPPINGS')

    # Append each child of the source DATA-MAPPINGS to the destination DATA-MAPPINGS
    for mapping in src_mappings:
        # Update references in the mapping
        for elem in mapping.iter():
            if elem.text:
                elem.text = update_reference(elem.text)
        dest_mappings.append(mapping)


def check_defaulted_ports(dst_arxml):
    socket_addresses = util.xml_elem_findall(dst_arxml.xml.getroot(), 'SOCKET-ADDRESS')
    defaulted_addresses = set()
    for socket_address in socket_addresses:
        port_number = util.xml_elem_find(socket_address, 'PORT-NUMBER')
        if port_number is not None and port_number.text == '1001':
            defaulted_addresses.add(socket_address[0].text)
    if defaulted_addresses:
        logging.warning("%d socket addresses defaulted to 1001 [%s]",
                        len(defaulted_addresses), ', '.join(defaulted_addresses))

def remove_unwanted_can_frames(dst_arxml):
    """
    Removes any CAN-FRAME inside the Frame AR-PACKAGE if it contains a PDU-REF
    pointing to an unwanted PDU type ('N-PDU', 'NM-PDU', 'DCM-I-PDU').

    If the Frame package becomes empty after deleting , it is also removed.
    """
    # Locate the Communication package
    dst_com = util.xml_ar_package_find(dst_arxml.xml.getroot(), 'Communication')
    assert dst_com is not None, "Destination Communication package is not found!"

    # Locate the Frame package inside Communication
    dst_frame_pkg = util.xml_ar_package_find(dst_com, 'Frame')
    if dst_frame_pkg is None:
        logging.warning("Frame AR-PACKAGE not found. Skipping CAN-FRAME removal.")
        return  # If no frames exist, nothing to process

    # Find all CAN-FRAME elements
    for can_frame in list(util.xml_elem_findall(dst_frame_pkg, 'CAN-FRAME')):
        frame_name_elem = util.xml_elem_find(can_frame, 'SHORT-NAME')
        if frame_name_elem is None:
            continue

        pdu_mappings_elem = util.xml_elem_find(can_frame, 'PDU-TO-FRAME-MAPPINGS')
        if pdu_mappings_elem is None:
            continue

        if should_remove_can_frame(frame_name_elem, can_frame, pdu_mappings_elem, _DISALLOWED_PDU_NAMES_, dst_frame_pkg):
            continue  # Frame was removed, skip to next


        pdu_mappings = util.xml_elem_findall(pdu_mappings_elem, 'PDU-TO-FRAME-MAPPING')
        for mapping in pdu_mappings:
            pdu_ref_elem = util.xml_elem_find(mapping, 'PDU-REF')
            if pdu_ref_elem is None or pdu_ref_elem.get('DEST') not in _DISALLOWED_PDU_NAMES_:
                continue

            logging.info("Removing CAN-FRAME: %s because it references %s", frame_name_elem.text, pdu_ref_elem.text)
            try:
                dst_frame_pkg[1].remove(can_frame)
                logging.info("Successfully removed %s", frame_name_elem.text)
            except ValueError:
                logging.warning("Failed to remove %s, element not in list", frame_name_elem.text)
            break  # Stop checking once we find an invalid reference


    # If the Frame package is now empty, remove it
    if not util.xml_elem_findall(dst_frame_pkg, 'CAN-FRAME'):
        logging.info("Removing empty Frame AR-PACKAGE from Communication.")
        dst_com[1].remove(dst_frame_pkg)  # Explicitly remove the Frame AR-PACKAGE


def should_remove_can_frame(frame_name_elem, can_frame, pdu_mappings_elem, _DISALLOWED_PDU_NAMES_, dst_frame_pkg):
    pdu_mappings = util.xml_elem_findall(pdu_mappings_elem, 'PDU-TO-FRAME-MAPPING')
    for mapping in pdu_mappings:
        pdu_ref_elem = util.xml_elem_find(mapping, 'PDU-REF')
        if pdu_ref_elem is not None and pdu_ref_elem.get('DEST') in _DISALLOWED_PDU_NAMES_:
            logging.info("Removing CAN-FRAME: %s because it references %s", frame_name_elem.text, pdu_ref_elem.text)
            try:
                dst_frame_pkg[1].remove(can_frame)
                logging.info("Successfully removed %s", frame_name_elem.text)
            except ValueError:
                logging.warning("Failed to remove %s, element not in list", frame_name_elem.text)
            return True  # Frame removed
    return False

def remove_empty_triggerings(root):
    ns = {'ns': 'http://autosar.org/schema/r4.0'}  # Match your ARXML namespace
    # Iterate through all potential parent elements
    for parent in root.findall(".//*"):
        # Find direct children that are empty I-SIGNAL-TRIGGERINGS
        empty_triggerings = [
            child for child in parent
            if child.tag == f'{{{ns["ns"]}}}I-SIGNAL-TRIGGERINGS' and len(child) == 0
        ]
        # Remove found elements
        for triggering in empty_triggerings:
            parent.remove(triggering)

def main(args):
    # Prepare the script options and load the files
    help_desc = {'i': ('input_arxml', "A comma separated list of input files: "
                                      " file1, file2, file3 etc. where file1 "
                                      "is the HI ECU COM arxml and rest are "
                                      "the MR ECU COM arxmls."),
                 'o': ('output_arxml', "A path to the output HI ECU COM "
                                       "arxml file.")}
    options = util.ScriptOptions.get(args, description="Script to merge "
                                "COM extracts.", version=VERSION,
                                help_desc=help_desc)
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    # Get list of input files
    arxmls = options.input_arxml.split(',')
    stakeholder_directory = 'out/products/hic/deps/stakeholder/components/input/MR_DP/HIC/'
    # The ECUsystem naming is inconsistent, for HIA it is named as HIASPA2 , in HIB it is named as HIB only.
    # and Elektra has a problem that when changing the visible name, the actual name that appears in the arxml does not change
    # Thus we need to make this dirty hack
    new_base_arxml = ''
    with open(arxmls[0], mode = 'r', encoding ='UTF-8') as f:
        for line in f:
            if 'HICSPA2' in line:
                new_base_arxml += line.replace("HICSPA2", "Hic").replace("Â¿", "")
            else:
                new_base_arxml += line.replace("Â¿", "")
    # Pre-process input ARXML file to remove invalid characters
    #input_file_path = options.input_arxml.split(',')[0]
    tmp_base_arxml = 'out/products/hic/test_com_merger/temp_com_arxml.arxml'
    with open(tmp_base_arxml, 'w', encoding='utf-8') as file:
        file.write(new_base_arxml)
    # The first .arxml in the list should be the .arxml coming out
    # from Capital Networks for our HI COM-SYSTEM. We consider this
    # to be the "base" or "destination" .arxml and everything else
    # gets added on top of it.
    dst_arxml = autosar.arxml.load(tmp_base_arxml)
    logging.info('Using %s as base .arxml', arxmls[0])
    # TODO: Maintain a separate file where the Device Proxy type is
    # given since we can't rely on any naming convention. For now,
    # detect which is which by using the .arxml filenames. We are lucky
    # that HIPOC ETH and LPC Device Proxy .arxmls have "Eth" in their names.
    can_dp_arxmls = []
    eth_dp_arxmls = []
    swc_dp_arxmls = arxmls[1:]
    graceful = False
    for arxml_name in arxmls[2:]:
        if is_xml_tag_present(arxml_name,"ETHERNET-CLUSTER"):
            eth_dp_arxmls.append(arxml_name)
        if is_xml_tag_present(arxml_name,"CAN-CLUSTER"):
            can_dp_arxmls.append(arxml_name)
    for arxml in eth_dp_arxmls:
        # Load Ethernet DP .arxml
        src_arxml = autosar.arxml.load(arxml)
        logging.info('Processing %s', arxml)
        if "SRSR" in src_arxml.filename:
            vlan = _VLAN_[1]
            graceful = True
        else:
            vlan = _VLAN_[0]
            graceful = False
        src_arxml.filename = src_arxml.filename.replace('system', 'Ethsystem')
        # Copy Signal and SignalGroups packages as is
        util.xml_ar_package_root_copy(src_arxml, dst_arxml, _ROOT_PACKAGES_)
        # Copy Communication packages (ISignal, ISignalPduGroup, Pdu)
        pdus = copy_communication_packages(src_arxml, dst_arxml)
        # Copy Fibex information
        copy_fibex_elements(src_arxml, dst_arxml, pdus)
        copy_and_append_data_mappings(src_arxml, dst_arxml)
        prepare_ethernet_physical_channel(dst_arxml, vlan)
        # Copy triggerings to Ethernet MR Vlan
        isig_pdu_path_map = copy_isignal_and_pdu_triggerings(
            src_arxml, dst_arxml,
            pdus,
            vlan,
            graceful)
        # Copy Ethernet DP's NetworkEndpoint
        net_ends_path_map = copy_network_endpoint(
            src_arxml, dst_arxml,
            vlan)
        # Copy Ethernet DP's SocketAddress(es)
        sock_addr_map = copy_socket_addresses(
            src_arxml, dst_arxml,
            vlan,
            net_ends_path_map)
        # Copy Ethernet DP's SocketBundles
        copy_socket_connection_bundles(
            src_arxml, dst_arxml,
            vlan,
            sock_addr_map, isig_pdu_path_map)
    # Merge MR COM extracts into HI COM extract
    can_frames, can_pdus = {}, []
    vlan = _VLAN_[1]
    special_handling_dp_arxmls = ['TSYNC', 'TSTA', 'TSTC', 'TSTE', 'TSTG', 'TSTI', 'TSTK']
    for arxml in can_dp_arxmls:
        if any(node_name in arxml for node_name in special_handling_dp_arxmls):
            continue
        # Processing MR Node DP with pure CAN communication with HIC
        src_arxml = autosar.arxml.load(arxml)
        logging.info('Processing %s for Pure CAN Communication with HIC', arxml)
        fix_ihfa_ihra_naming(src_arxml)
        # This is to copy connectors and comm-controller from can dp arxmls as they don't exist in the com arxml
        copy_ecusystem_packages(src_arxml, dst_arxml)
        graceful = bool("SRSR" in src_arxml.filename)
        src_arxml.filename = src_arxml.filename.replace('Ethsystem', 'system')
        # This function is to add the can cluster from each can dp arxml as com arxml doesn't have this info
        # Each can cluster can have only one can physical channel
        dst_physical_channels = copy_vehicletopology_packages(src_arxml, dst_arxml)
        # Sync data from src_arxml to dst_arxml
        if "SRSR" not in src_arxml.filename\
                and "RBCM" not in src_arxml.filename:
            util.xml_ar_package_root_copy(src_arxml, dst_arxml, _ROOT_PACKAGES_)
            pdus = copy_communication_packages(src_arxml, dst_arxml)
            copy_fibex_elements(src_arxml, dst_arxml, pdus)
        else:
            pdus = fetch_pdu(src_arxml)
        for dst_physical_channel in dst_physical_channels:
            update_isignal_and_pdu_triggerings(src_arxml, dst_arxml,
                                            dst_physical_channel)
    for arxml in can_dp_arxmls:
        if not any(node_name in arxml for node_name in special_handling_dp_arxmls):
            continue
        vlan = _VLAN_[1]
        # Load MR COM extract
        src_arxml = autosar.arxml.load(arxml)
        logging.info('Processing %s for MRCOM Communication with HIC', arxml)
        fix_ihfa_ihra_naming(src_arxml)
        # Get frames info
        frames = fetch_can_frame_triggering_info(src_arxml, True)
        # Map ports to signals
        copy_and_append_data_mappings(src_arxml, dst_arxml)
        util.xml_ar_package_root_copy(src_arxml, dst_arxml, _ROOT_PACKAGES_)
        pdus = copy_communication_packages(src_arxml, dst_arxml)
        copy_fibex_elements(src_arxml, dst_arxml, pdus)
        # Copy triggerings
        copy_isignal_and_pdu_triggerings(
            src_arxml, dst_arxml,
            pdus,
            vlan,
            graceful)
        # Create socket connection bundle to dst_arxml
        create_socket_connection_bundle(_SOCKET_CONNECTION_BUNDLE_,
                                        src_arxml, dst_arxml,
                                        frames, pdus, vlan)
        can_pdus += pdus
        # Todo: check for keys collision
        can_frames.update(frames)
    add_mr_com_flavour(dst_arxml, can_frames, can_pdus, vlan)
    # Add SWBaseType AR Package in com_merged arxml from swc_merged arxml
    #add_swbasetype_arpackage(swc_dp_arxmls, dst_arxml)
    # TODO: It seems like not all Device Proxy .arxmls have the same
    # Communication packages. For example, HIPocDpHibEthMAIN2 does
    # not contain ISignalGroup (since there are no Signal Groups defined)
    # Should we remove the missing packages check?
    # Check for anomalies
    if util.xml_ar_packages_missing():
        assert 0, "Missing source packages detected...aborting!"
    if util.xml_elem_extend_name_clashed():
        logging.warning("Name clashes were detected and skipped due to graceful mode.")
    copy_ecpi_to_ethernet_connectors(dst_arxml)
    # Add transfer property to signals
    add_transfer_property_to_signals(dst_arxml)
    # Check for defaulted ports with 1001
    check_defaulted_ports(dst_arxml)
    # Process only files within the stakeholder directory
    file_names = os.listdir(stakeholder_directory)
    for file_name in file_names:
        if file_name.endswith('.arxml'):
            arxml_path = os.path.join(stakeholder_directory, file_name)
            try:
                src_arxml = autosar.arxml.load(arxml_path)
                logging.info('Processing {file_name}: ')
                # function to process gateway AR.package and remove i-signals PDUs in each Stackholder ARXML file
                process_gateway_and_remove_signals(src_arxml, dst_arxml )
            except (IOError, ValueError) as e:
                logging.error('Failed to process {file_name}: {str(e)}')
    # Removes any CAN frame with IPU refs to N-PDU' NM-PDU or DCM-I-PDU dest arxml
    remove_unwanted_can_frames(dst_arxml)
    update_all_routing_refs(dst_arxml)
    # Remove empty element - I-SIGNAL-TRIGGERINGS
    remove_empty_triggerings(dst_arxml.xml.getroot())
    util.ensure_unique_uuids(dst_arxml)
    # Save merged COM extract arxml
    dst_arxml.save(options.output_arxml)
# Run COM merger
if __name__ == "__main__":
    SystemExit(main(sys.argv[1:]))
