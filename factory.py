#!/usr/bin/python

import xml.etree.ElementTree as ET

import autosar

NAMESPACE = {'ns': 'http://autosar.org/schema/r4.0'}

def xml_get_namespace(elem: ET.Element) -> str:
    """
    Dynamically extracts the XML namespace from an element's tag.

    Args:
        elem (ET.Element): The XML element.

    Returns:
        str: The namespace URI string, or an empty string if not present.
    """        
    if '}' in elem.tag:
        return elem.tag.split('}')[0][1:]
    return ''

def xml_elem_create(string):
    """
    Creates an element from a string and applies a predefined AUTOSAR namespace.

    Args:
        string (str): The XML string to parse.

    Returns:
        ET.Element: The newly created element with namespaced tags.
    """
    # Create a "namespace-naive" element from the string
    elem = ET.fromstring(string)

    # Get the namespace URI from the global dictionary
    namespace_uri = NAMESPACE.get('ns')

    # If a namespace is defined, apply it to the root element and all its children.
    if namespace_uri:
        for e in elem.iter():
            # This check prevents adding a namespace to a tag that might already have one.
            if '}' not in e.tag:
                e.tag = f"{{{namespace_uri}}}{e.tag}"

    return elem



def xml_ar_package_create(name, uuid):
    # Returns AR-PACKAGE created where
    # SHORT-NAME is a name and UUID is uuid

    return xml_elem_create('''
    <AR-PACKAGE UUID="{}">
      <SHORT-NAME>{}</SHORT-NAME>
      <ELEMENTS/>
    </AR-PACKAGE>
    '''.format(uuid, name))


def xml_network_endpoint_ipv4_create(name, address, source, mask):
    # Returns element NETWORK-ENDPOINT (ipv4)

    return xml_elem_create('''
    <NETWORK-ENDPOINT>
      <SHORT-NAME>{}</SHORT-NAME>
      <NETWORK-ENDPOINT-ADDRESSES>
        <IPV-4-CONFIGURATION>
          <IPV-4-ADDRESS>{}</IPV-4-ADDRESS>
          <IPV-4-ADDRESS-SOURCE>{}</IPV-4-ADDRESS-SOURCE>
          <NETWORK-MASK>{}</NETWORK-MASK>
        </IPV-4-CONFIGURATION>
      </NETWORK-ENDPOINT-ADDRESSES>
    </NETWORK-ENDPOINT>
    '''.format(name, address, source, mask))


def xml_soad_routing_group_create(name):
    # Returns element SO-AD-ROUTING-GROUP

    return xml_elem_create('''
    <SO-AD-ROUTING-GROUP>
      <SHORT-NAME>{}</SHORT-NAME>
    </SO-AD-ROUTING-GROUP>
    '''.format(name))


def xml_socket_address_udp_create(name, app_endpoint_name,
                                  network_endpoint_ref, udp_port,
                                  eth_connector_ref):
    # Returns element SOCKET-ADDRESS

    return xml_elem_create('''
    <SOCKET-ADDRESS>
    <SHORT-NAME>{}</SHORT-NAME>
    <APPLICATION-ENDPOINT>
        <SHORT-NAME>{}</SHORT-NAME>
        <NETWORK-ENDPOINT-REF DEST="NETWORK-ENDPOINT">{}</NETWORK-ENDPOINT-REF>
        <TP-CONFIGURATION>
        <UDP-TP>
            <UDP-TP-PORT>
            <PORT-NUMBER>{}</PORT-NUMBER>
            </UDP-TP-PORT>
        </UDP-TP>
        </TP-CONFIGURATION>
    </APPLICATION-ENDPOINT>
    <CONNECTOR-REF DEST="ETHERNET-COMMUNICATION-CONNECTOR">{}</CONNECTOR-REF>
    </SOCKET-ADDRESS>'''.format(name, app_endpoint_name, network_endpoint_ref,
                                udp_port, eth_connector_ref))


def xml_socket_connection_ipdu_id_create(header_id, port_ref,
                                         pdu_triggering_ref,
                                         routing_group_ref):
    # Returns element SOCKET-CONNECTION-IPDU-IDENTIFIER

    elem = xml_elem_create('''
    <SOCKET-CONNECTION-IPDU-IDENTIFIER>
    <HEADER-ID>{}</HEADER-ID>
    <PDU-TRIGGERING-REF DEST="PDU-TRIGGERING">{}</PDU-TRIGGERING-REF>
    <ROUTING-GROUP-REFS>
        <ROUTING-GROUP-REF DEST="SO-AD-ROUTING-GROUP">{}</ROUTING-GROUP-REF>
    </ROUTING-GROUP-REFS>
    </SOCKET-CONNECTION-IPDU-IDENTIFIER>
    '''.format(header_id, pdu_triggering_ref, routing_group_ref))

    # Add PDU-COLLECTION-TRIGGER in case of Tx port
    if '_Out' in port_ref:
        elem.insert(1, xml_elem_create('''
        <PDU-COLLECTION-TRIGGER>ALWAYS</PDU-COLLECTION-TRIGGER>'''))
    return elem


def xml_socket_connection_bundle_create(name, client_port_ref,
                                        server_port_ref):
    # Returns element SOCKET-CONNECTION-BUNDLE

    return xml_elem_create('''
    <SOCKET-CONNECTION-BUNDLE>
    <SHORT-NAME>{}</SHORT-NAME>
    <BUNDLED-CONNECTIONS>
        <SOCKET-CONNECTION>
        <CLIENT-PORT-REF DEST="SOCKET-ADDRESS">{}</CLIENT-PORT-REF>
        <PDUS/>
        </SOCKET-CONNECTION>
    </BUNDLED-CONNECTIONS>
    <SERVER-PORT-REF DEST="SOCKET-ADDRESS">{}</SERVER-PORT-REF>
    </SOCKET-CONNECTION-BUNDLE>
    '''.format(name, client_port_ref,
               server_port_ref))


def xml_ecuc_textual_param_create(dest_ref, value):

    return xml_elem_create('''
    <ECUC-TEXTUAL-PARAM-VALUE>
    <DEFINITION-REF DEST="ECUC-ENUMERATION-PARAM-DEF">{}</DEFINITION-REF>
    <VALUE>{}</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
    '''.format(dest_ref, value))


def xml_ecu_reference_cont_create():
    return xml_elem_create('''
    <REFERENCE-VALUES>
    </REFERENCE-VALUES>
    ''')


def xml_ecu_reference_value_create(def_ref, value_ref):
    return xml_elem_create('''
    <ECUC-REFERENCE-VALUE>
      <DEFINITION-REF DEST="ECUC-CHOICE-REFERENCE-DEF">{}</DEFINITION-REF>
      <VALUE-REF DEST="ECUC-CONTAINER-VALUE">{}</VALUE-REF>
    </ECUC-REFERENCE-VALUE>
    '''.format(def_ref, value_ref))


def xml_ecuc_numerical_param_create(dest_ref, value):

    return xml_elem_create('''
    <ECUC-NUMERICAL-PARAM-VALUE>
    <DEFINITION-REF DEST="ECUC-BOOLEAN-PARAM-DEF">{}</DEFINITION-REF>
    <VALUE>{}</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
    '''.format(dest_ref, value))


def xml_system_signal_create(name, desc, category='VALUE', length='false'):

    return xml_elem_create('''
    <SYSTEM-SIGNAL>
    <SHORT-NAME>{}</SHORT-NAME>
      <DESC>
        <L-2 L="FOR-ALL">{}</L-2>
      </DESC>
      <CATEGORY>{}</CATEGORY>
      <DYNAMIC-LENGTH>{}</DYNAMIC-LENGTH>
    </SYSTEM-SIGNAL>
    '''.format(name, desc, category, length))


def xml_isignal_create(name, value, length,
                       sw_base_type, compu_method, sig_ref,
                       data_policy='NETWORK-REPRESENTATION-FROM-COM-SPEC'):

    return xml_elem_create('''
    <I-SIGNAL>
      <SHORT-NAME>{}</SHORT-NAME>
      <DATA-TYPE-POLICY>{}</DATA-TYPE-POLICY>
      <INIT-VALUE>
        <NUMERICAL-VALUE-SPECIFICATION>
          <VALUE>{}</VALUE>
        </NUMERICAL-VALUE-SPECIFICATION>
      </INIT-VALUE>
      <LENGTH>{}</LENGTH>
      <NETWORK-REPRESENTATION-PROPS>
        <SW-DATA-DEF-PROPS-VARIANTS>
          <SW-DATA-DEF-PROPS-CONDITIONAL>
            <BASE-TYPE-REF DEST="SW-BASE-TYPE">{}</BASE-TYPE-REF>
            <COMPU-METHOD-REF DEST="COMPU-METHOD">{}</COMPU-METHOD-REF>
          </SW-DATA-DEF-PROPS-CONDITIONAL>
        </SW-DATA-DEF-PROPS-VARIANTS>
      </NETWORK-REPRESENTATION-PROPS>
      <SYSTEM-SIGNAL-REF DEST="SYSTEM-SIGNAL">{}</SYSTEM-SIGNAL-REF>
    </I-SIGNAL>
    '''.format(name, data_policy, value, length,
               sw_base_type, compu_method, sig_ref))


def xml_isignal_to_ipdu_mapping_create(name, isig_ref, packing,
                                       position, transfer):

    return xml_elem_create('''
    <I-SIGNAL-TO-I-PDU-MAPPING>
      <SHORT-NAME>{}</SHORT-NAME>
      <I-SIGNAL-REF DEST="I-SIGNAL">{}</I-SIGNAL-REF>
      <PACKING-BYTE-ORDER>{}</PACKING-BYTE-ORDER>
      <START-POSITION>{}</START-POSITION>
      <TRANSFER-PROPERTY>{}</TRANSFER-PROPERTY>
    </I-SIGNAL-TO-I-PDU-MAPPING>
    '''.format(name, isig_ref, packing, position, transfer))


def xml_isignal_triggerings_create():
    return xml_elem_create('''
    <I-SIGNAL-TRIGGERINGS>
    </I-SIGNAL-TRIGGERINGS>
    ''')


def xml_isignal_triggering_create(name, port_ref, signal_ref):

    return xml_elem_create('''
    <I-SIGNAL-TRIGGERING>
      <SHORT-NAME>{}</SHORT-NAME>
      <I-SIGNAL-PORT-REFS>
        <I-SIGNAL-PORT-REF DEST="I-SIGNAL-PORT">{}</I-SIGNAL-PORT-REF>
      </I-SIGNAL-PORT-REFS>
      <I-SIGNAL-REF DEST="I-SIGNAL">{}</I-SIGNAL-REF>
    </I-SIGNAL-TRIGGERING>
    '''.format(name, port_ref, signal_ref))


def xml_fibex_elem_ref_conditional_create(signal_ref):

    return xml_elem_create('''
    <FIBEX-ELEMENT-REF-CONDITIONAL>
      <FIBEX-ELEMENT-REF DEST="I-SIGNAL">{}</FIBEX-ELEMENT-REF>
    </FIBEX-ELEMENT-REF-CONDITIONAL>
    '''.format(signal_ref))


def xml_isignal_triggering_ref_conditional_create(signal_ref):

    return xml_elem_create('''
    <I-SIGNAL-TRIGGERING-REF-CONDITIONAL>
      <I-SIGNAL-TRIGGERING-REF DEST="{}">{}</I-SIGNAL-TRIGGERING-REF>
    </I-SIGNAL-TRIGGERING-REF-CONDITIONAL>
    '''.format('I-SIGNAL-TRIGGERING', signal_ref))


def xml_pdu_triggerings_create():
    return xml_elem_create('''
    <PDU-TRIGGERINGS>
    </PDU-TRIGGERINGS>
    ''')


def xml_soad_config_create():
    return xml_elem_create('''
    <SO-AD-CONFIG>
    </SO-AD-CONFIG>
    ''')


def xml_conn_bundles_create():
    return xml_elem_create('''
    <CONNECTION-BUNDLES>
    </CONNECTION-BUNDLES>
    ''')


# Yes, they really misspelled addresses as addresss in Autosar
def xml_socket_addresss_create():
    return xml_elem_create('''
    <SOCKET-ADDRESSS>
    </SOCKET-ADDRESSS>
    ''')
