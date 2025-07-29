#!/usr/bin/python3
from optparse import OptionParser
from typing import List, Optional, Tuple, Union
from xml.dom import minidom
import logging
import os
import pprint
import sys
import uuid
import xml.etree.ElementTree as ET

# from factory import xml_ar_package_create
# from log_utils.log_wrappers import error
import autosar

pp = pprint.PrettyPrinter(indent=4)

# Utility functions
#


# Available in python 3.9...
def removesuffix(string: str, suffix: str) -> str:
    """
    Returns the specified string without the specified suffix.

    Args:
        string (str): The string to remove the suffix from.
        suffix (str): The suffix to remove.

    Returns:
        str: The string without the specified suffix.
    """
    if isinstance(string, str):
        if string.endswith(suffix):
            return string[:-len(suffix)]
        return string[:]

    raise TypeError  # string must be a str


# Available in python 3.9...
def removeprefix(string: str, prefix: str) -> str:
    """
    Returns the specified string without the specified prefix.

    Args:
        string (str): The string to remove the prefix from.
        prefix (str): The prefix to remove.

    Returns:
        str: The string without the specified prefix.
    """
    if isinstance(string, str):
        if string.startswith(prefix):
            return string[len(prefix):]
        return string[:]

    raise TypeError  # string must be a str


def xml_elem_str(elem: ET.Element, *, indent_with:str ="    ") -> str:
    """
    Returns a pretty formated string representation of the specified element.

    Args:
        elem (ET.Element): The element to stringify.
        indent_with (str, optional): Indent nested tags with this. Defaults to "    ".
    Returns:
        str: The string representation of the specified element.
    """
    if elem is None:
        return ""
    if isinstance(elem, ET.Element):
        raw_elem_str = ET.tostring(elem,
                                   encoding='utf-8',
                                   short_empty_elements=False)
        minidom_elem = minidom.parseString(raw_elem_str)
        pretty_elem_str = minidom_elem.toprettyxml(indent=indent_with)
        # Remove (potential) empty lines and the initial
        # <?xml version="1.0" ?> added by minidom
        return "\n".join([s for s in pretty_elem_str.split("\n")
                          if s.strip()][1:])

    raise TypeError


def xml_elements_equal(e1: ET.Element, e2: ET.Element) -> bool:
    """
    Returns True if the two input elements contains the same content (i.e are equal).

    Args:
        e1 (ET.Element): The first XML element.
        e2 (ET.Element): The second XML element.

    Returns:
        bool: True if the elements are considered equal, False otherwise.
    """
    if e1 is None and e2 is None:
        return True
    if isinstance(e1, ET.Element) and isinstance(e2, ET.Element):
        if e1.tag != e2.tag:
            return False
        if e1.text is not None and e2.text is not None:
            if e1.text.strip() != e2.text.strip():
                return False
        if e1.tail != e2.tail:
            return False
        if e1.attrib != e2.attrib:
            return False
        if len(e1) != len(e2):
            return False
        return all(xml_elements_equal(c1, c2) for c1, c2 in zip(e1, e2))
    return False


def xml_get_child_value_by_tag(elem: ET.Element, tag: str) -> str:
    """
    Get the value of a direct child element from its tag.

    For example, the following element AR-PACKAGE has only two direct children: SHORT-NAME and
    ELEMENTS

        <AR-PACKAGE>
          <SHORT-NAME>PortInterface</SHORT-NAME>
          <ELEMENTS>
            Element1
            Element2
            ...
          </ELEMENTS>

    Calling this function with elem being the AR-PACKAGE elem, and tag = "SHORT-NAME", would return
    "PortInterface"
    """

    for child in list(elem):
        if child.tag == autosar.base.add_schema(tag):
            value = child.text
            assert value is not None
            return value
    error(f"No child found with tag '{tag}'.") 

def xml_set_child_value_by_tag(elem: ET.Element, tag: str, value: str) -> None:
    for child in list(elem):
        if child.tag == autosar.base.add_schema(tag):
            child.text = value
            assert value is not None

def xml_get_child_elem_by_tag(elem: ET.Element, tag: str) -> str:
    """
    Get the elem of a direct child element from its tag.

    For example, the following element AR-PACKAGE has only two direct children: PDU-TRIGGERINGS and
    I-SIGNAL-TRIGGERINGS

        <AR-PACKAGE>
          <I-SIGNAL-TRIGGERINGS>
          </I-SIGNAL-TRIGGERINGS>
          <PDU-TRIGGERINGS>
          </PDU-TRIGGERINGS>

    Calling this function with elem being the AR-PACKAGE elem, and tag = "PDU-TRIGGERINGS", would return
    PDU-TRIGGERINGS element
    """

    for child in list(elem):
        if child.tag == autosar.base.add_schema(tag):
            elem = child
            assert elem is not None
            return elem
    error(f"No child found with tag '{tag}'.")

def xml_elem_find(elem: ET.Element, tag: str) -> Optional[ET.Element]:
    return elem.find('.//' + autosar.base.add_schema(tag))


def xml_elem_find_assert_exists(elem: ET.Element, tag: str) -> ET.Element:
    return_elem = elem.find('.//' + autosar.base.add_schema(tag))
    assert return_elem is not None
    return return_elem


def xml_elem_findall(elem: ET.Element, tag: str) -> List[ET.Element]:
    return elem.findall('.//' + autosar.base.add_schema(tag))


def assert_elem_tag(elem: ET.Element, tag: Union[Tuple, str]) -> None:
    if isinstance(tag, str):
        tag = (tag, )
    assert elem.tag in (autosar.base.add_schema(t) for t in tag),\
        "Expected tags differ!"


def is_elem_tag(elem: ET.Element, tag: Union[Tuple, str]) -> bool:
    if isinstance(tag, str):
        tag = (tag, )
    return elem.tag in (autosar.base.add_schema(t) for t in tag)


def get_elem_tag_without_schema(elem: ET.Element) -> str:
    return elem.tag[elem.tag.rfind('}') + 1:]


def xml_elem_namespace(elem: ET.Element) -> str:
    """
    Returns the namespace of a specified tag.
    Args:
        elem (ET.Element): The XML element.
    Returns:
        str: The namespace of the XML element.
    """
    if isinstance(elem, ET.Element):
        try:
            if elem.tag.split("}", 1)[1]:
                return elem.tag.split("}")[0] + "}"
        except:
            return ""
    else:
        raise TypeError

    return ""

def xml_elem_namespace_new(elem: ET.Element) -> str:
    if not isinstance(elem, ET.Element):
        raise TypeError("xml_elem_namespace: elem != Et.Element")

    if '}' in elem.tag:
        return elem.tag.split('}')[0] + '}'
    return ""


def xml_strip_namespace(elem: ET.Element) -> str:
    """
    Function that returns the namespace of a specific XML element.

    Args:
        elem (ET.Element): The XML element/tag.
    Returns:
        str: The name of the tag without the namespace.
    """
    if isinstance(elem, ET.Element):
        try:
            return elem.tag.split("}", 1)[1]
        except:
            return elem.tag
    else:
        raise TypeError


def xml_elem_type_findall(elem: ET.Element, elem_type: str, name: str) -> List[ET.Element]:
    """
    Get all child elements of type 'elem_type' and name 'name'.

    First, a search is made for all elements of a certain type (or rather, with a certain tag).
    Then, all elements in that unordered list with a SHORT-NAME or DEFINITION-REF value equal
    to the input arg 'name' will be found. A list of those elements is then returned.
    """

    elems = xml_elem_findall(elem, elem_type)
    res = []
    for elem in elems:
        if list(elem):
            assert_elem_tag(elem[0], ('SHORT-NAME', 'DEFINITION-REF'))
            if elem[0].text == name:
                res.append(elem)
        elif elem.text == name:
            res.append(elem)
    return res


def xml_elem_type_find(elem: ET.Element, elem_type: str, name: str) -> Optional[ET.Element]:
    """
    Get the first child element of type 'elem_type' and name 'name'.

    First, a search is made for all elements of a certain type (or rather, with a certain tag).
    Then, the first element in that unordered list with a SHORT-NAME or DEFINITION-REF value equal
    to the input arg 'name' will be found. That element is then returned, or None if no element was
    found.
    """

    elems = xml_elem_findall(elem, elem_type)
    for e in elems:
        if list(e):  # True if list(e) returns a non-empty list
            assert_elem_tag(e[0], ('SHORT-NAME', 'DEFINITION-REF'))
            if e[0].text == name:
                return e
        elif e.text == name:
            return e
    return None


def xml_ar_package_find(elem: ET.Element, name: str) -> Optional[ET.Element]:
    # Returns AR-PACKAGE found in elem where
    # SHORT-NAME matches given name

    return xml_elem_type_find(elem, 'AR-PACKAGE', name)


def xml_ar_package_validate(elem: ET.Element) -> bool:
    # Validate structure of a elem
    # Returns True if 'AR-PACKAGES' is present
    # or False if it isn't
    assert_elem_tag(elem, 'AR-PACKAGE')
    assert_elem_tag(elem[0], 'SHORT-NAME')
    assert_elem_tag(elem[1], 'ELEMENTS')

    elems = len(elem)
    if elems > 2:
        assert elems == 3, "Unhandled AR-PACKAGE "\
                           "detected (children > 3)!"
        assert_elem_tag(elem[2], 'AR-PACKAGES')
        return True
    return False


def xml_ref_transform_all(refs: List[ET.Element], src_path, dst_path) -> None:
    # Transform source to destination refs paths

    for ref in refs:
        assert ref.text is not None
        assert src_path in ref.text, "The path %s does not contains "\
                                     "subpath %s" % (ref.text, src_path)
        if ref.text:
            ref.text = ref.text.replace(src_path, dst_path)


def xml_elem_child_remove_all(elem, children):
    # Remove elem elements

    for child in children:
        elem.remove(child)


def xml_elem_get_abs_path(elem, arxml):
    # Get elem path by traversing it's
    # parents until root node is reached

    def traverse_parents(elem, arxml, path):
        child = list(elem)
        if child and is_elem_tag(child[0], 'SHORT-NAME'):
            path.insert(0, child[0].text)
        parent = arxml.parents.get(elem, None)
        if parent:
            traverse_parents(parent, arxml, path)

    path = []
    traverse_parents(elem, arxml, path)
    assert path is not None, "The absolute path of %s can't "\
                             "be found in %s" % (elem, arxml)
    return '/' + '/'.join(path)


def xml_elem_append(elem, child, parents):
    # Append child to elem (child can be a list)
    # Updates parent list (needed for path retrieval)

    if isinstance(child, list) \
      or is_elem_tag(child, "ELEMENTS")\
      or is_elem_tag(child, "SOCKET-ADDRESSS") \
      or is_elem_tag(child, "DATA-TRANSFORMATIONS") \
      or is_elem_tag(child, "TRANSFORMATION-TECHNOLOGYS") \
      or is_elem_tag(child, "CONNECTION-BUNDLES"):
        for el in child:
            elem.append(el)
            parents[el] = elem
    else:
        elem.append(child)
        parents[child] = elem

def xml_elem_append_at_index(elem, child, index, parents):
    # Insert child to elem at index (child can be a list)
    # Updates parent list (needed for path retrieval)
    # Raises TypeError if child is a list
    # If needed for child to be a list, improvements are needed in the code

    if isinstance(child, list) \
      or is_elem_tag(child, "ELEMENTS")\
      or is_elem_tag(child, "SOCKET-ADDRESSS") \
      or is_elem_tag(child, "DATA-TRANSFORMATIONS") \
      or is_elem_tag(child, "TRANSFORMATION-TECHNOLOGYS") \
      or is_elem_tag(child, "CONNECTION-BUNDLES"):
        raise TypeError("child cannot be a list")

    elem.insert(index, child)
    parents[child] = elem


def xml_elem_add_ar_packages(elem, parents):
    # Appends 'AR-PACKAGES' to the elem

    child = autosar.base.create_element('AR-PACKAGES')
    elem.append(child.xmlref)
    parents[child] = elem


def xml_ecu_sys_name_get(arxml):
    # Returns an ECU System name from the arxml

    ecu_sys = xml_ar_package_find(arxml.xml.getroot(), 'ECUSystem')
    assert ecu_sys is not None, "The ECUSystem "\
                                "package is not found in %s!" % arxml
    assert_elem_tag(ecu_sys[1], 'AR-PACKAGES')
    assert_elem_tag(ecu_sys[1][0], 'AR-PACKAGE')
    assert_elem_tag(ecu_sys[1][0][0], 'SHORT-NAME')
    return ecu_sys[1][0][0].text


# Error handling
ELEMENTS_NAME_CLASH: List[bool] = []
MISSING_SRC_PACKAGE: List[bool] = []
NAME_CLASH_IS_ERROR = ()
NAME_CLASH_IS_ALLOWED = None


def xml_elem_extend_name_clashed():
    if any(ELEMENTS_NAME_CLASH):
        logging.warning("Elements Clashed: %s",ELEMENTS_NAME_CLASH)
    return any(ELEMENTS_NAME_CLASH)


def xml_ar_packages_missing():
    return any(MISSING_SRC_PACKAGE)

def xml_elem_extend_clashed_ports(el, prefixed_el, dst_arxml):
    """
    #handle the copying of clashed port names (i.e. already existing ports in the dst_arxml)
    #1: delete the original port in dst arxml.
    #2: copy the prefixed port from src arxml.
    #3: update the delegation_port_connecter in dst_arxml to reference the new prefixed outter port.
    """
    logging.info('Copying clashed port: %s', el[0].text)
    #Deleting the original port in dst_arxml:
    dst_sw_comp_type = xml_elem_find(dst_arxml.xml.getroot(), 'COMPOSITION-SW-COMPONENT-TYPE')
    dst_el = xml_elem_type_find(dst_sw_comp_type, get_elem_tag_without_schema(el), el[0].text)
    #saving dst_el path before removing it:
    dst_el_path = xml_elem_get_abs_path(dst_el, dst_arxml)
    xml_elem_find(dst_sw_comp_type, 'PORTS').remove(dst_el)

    #keeping the old unprefixed port interface reference (we will use the none prefixed prot interfaces)
    xml_set_child_value_by_tag(prefixed_el, 'PROVIDED-INTERFACE-TREF', xml_get_child_value_by_tag(el, 'PROVIDED-INTERFACE-TREF'))
    #Appending prefixed src_port to dst_arxml
    xml_elem_append(xml_elem_find(dst_sw_comp_type, 'PORTS'), prefixed_el, dst_arxml.parents)
    #updating the delegation port connector:
    dst_delegation_connectors = xml_elem_findall(dst_sw_comp_type, 'DELEGATION-SW-CONNECTOR')
    prefixed_el_dst_path = xml_elem_get_abs_path(prefixed_el, dst_arxml)
    for connector in dst_delegation_connectors:
        if dst_el_path == xml_get_child_value_by_tag(connector, 'OUTER-PORT-REF'):
            xml_set_child_value_by_tag(connector, 'OUTER-PORT-REF', prefixed_el_dst_path)
def get_element_index(parent, tag):
    #gets the index of the child element tag with respect to its parent.
    #if there is no child element with the tag, it returns -1 (useful to be used in conditions)
    element = xml_elem_find(parent, tag)
    for i, child in enumerate(parent):
        if child is element:
            return i
    return -1

def xml_elem_extend(
    src_elems,
    dst_elems,
    src_arxml,
    dst_arxml,
    src_name=lambda el: el[0].text,
    dst_name=lambda el: el[0].text,
    graceful=False
):
    """
    Extends dst_elems with src_elems list while checking for name clashes.
    Returns a dictionary mapping old paths to new paths.

    Parameters:
    - src_elems: List of XML elements to be added.
    - dst_elems: List of existing XML elements where new elements will be added.
    - src_arxml: Source XML document.
    - dst_arxml: Destination XML document.
    - src_name: Function to extract the name of a source element.
    - dst_name: Function to extract the name of a destination element.
    - graceful: If True, handles name clashes by keeping unique elements; otherwise, logs an error.

    Example:
    >>> src_elems = [<Element 'A'>, <Element 'B'>]
    >>> dst_elems = [<Element 'B'>, <Element 'C'>]
    >>> xml_elem_extend(src_elems, dst_elems, src_arxml, dst_arxml)
    """
    path_map = {}

    for elem in src_elems:
        name = src_name(elem)
        src_path = xml_elem_get_abs_path(elem, src_arxml)
        duplicate = next((x for x in dst_elems if name == dst_name(x)), None)

        # Determine the new path for the element in the destination XML
        dst_path = (
            xml_elem_get_abs_path(duplicate, dst_arxml)
            if duplicate else
            f"{xml_elem_get_abs_path(dst_elems, dst_arxml)}{src_path[src_path.rfind('/'):]}")

        path_map[src_path] = dst_path

    # Identify name clashes
    src_names = {src_name(el) for el in src_elems}
    dst_names = {dst_name(el) for el in dst_elems}
    intersection = sorted(src_names & dst_names)

    if intersection:
        src_path = xml_elem_get_abs_path(src_elems[0], src_arxml).rsplit('/', 1)[0]
        dst_path = xml_elem_get_abs_path(dst_elems, dst_arxml)

        logging.warning("%d name clashes found in %s and %s", len(intersection), src_path, dst_path)
        logging.warning("Conflicting elements: %s", intersection)

        if graceful:
            # Copy only elements without clashes
            diff_elems = [el for el in src_elems if src_name(el) not in intersection]
            xml_elem_append(dst_elems, diff_elems, dst_arxml.parents)
        else:
            # Log the clash error
            ELEMENTS_NAME_CLASH.append(True)
    else:
        # No clashes, append all elements
        xml_elem_append(dst_elems, src_elems, dst_arxml.parents)

    return path_map


def xml_ar_package_copy(src, dst_parent, src_arxml, dst_arxml, grace_list=()):
    # Copy element tree of a src to a dst_parent
    # Validates the structure of a 'AR-PACKAGE'
    # Recreates missing destination packages

    src_have_pkgs = xml_ar_package_validate(src)

    # Find destination package
    name = src[0].text
    dst = xml_ar_package_find(dst_parent, name)
    if dst is None:
        # No destination package found; create AR-PACKAGE
        # and append it to the destination AR-PACKAGES
        path = xml_elem_get_abs_path(src, src_arxml)
        dst = xml_ar_package_create(name,
                                    str(uuid.uuid4()) + path.replace('/', '-'))
        # Add 'AR-PACKAGES'
        if src_have_pkgs:
            xml_elem_add_ar_packages(dst, dst_arxml.parents)
        xml_elem_append(dst_parent, dst, dst_arxml.parents)
    else:
        # Check for presence of a destination 'AR-PACKAGES'
        dst_have_pkgs = xml_ar_package_validate(dst)
        if src_have_pkgs and not dst_have_pkgs:
            xml_elem_add_ar_packages(dst, dst_arxml.parents)

    # Copy source elements
    xml_elem_extend(src[1],
                    dst[1],
                    src_arxml,
                    dst_arxml,
                    graceful=name in grace_list if grace_list else True)

    # Copy 'AR-PACKAGES' elems
    if src_have_pkgs:
        for pkg in src[2]:
            xml_ar_package_copy(pkg, dst[2], src_arxml, dst_arxml, grace_list)


def xml_ar_package_root_copy(src_arxml,
                             dst_arxml,
                             root_pkgs,
                             tolerate_missing=()):
    # Copy root_pkgs from src_arxml to dst_arxml
    # Treat as no error if src package is missing but found
    # in tolerate_missing

    # Copy root packages
    for name, grace_list in root_pkgs:
        logging.info("Copying package %s", name)
        src = xml_ar_package_find(src_arxml.xml.getroot(), name)
        if src is None:
            if name not in tolerate_missing:
                logging.warning("Package %s is missing in source .arxml", name)
                MISSING_SRC_PACKAGE.append(True)
            continue
        xml_ar_package_copy(src,
                            dst_arxml.xml.getroot()[0], src_arxml, dst_arxml,
                            grace_list)


def replace_uuid(elem):
    """
        Given an Autosar element, replace its UUID with a newly generated one.
        Used to avoid duplicate UUIDs in .arxmls since DaVinci tools complain
        about this problem. Instead of completely removing UUIDs we should
        replace them and keep track of the replacement in order to have Autosar
        element tracebility back to the tools that produced them initially.
    """

    elem_uuid = elem.attrib['UUID']
    if elem_uuid:
        new_uuid = str(uuid.uuid4())
        logging.debug("Replacing UUID of element %s with new UUID %s",
            xml_elem_str(elem).split('\n', 2)[0:2],
            new_uuid
        )
        elem.attrib.pop("UUID", None)
        elem.set("UUID", new_uuid)
    else:
        logging.warning("Trying to replace UUID of element %s with no UUID",
            xml_elem_str(elem).split('\n', 2)[0:2]
        )
    return new_uuid

def ensure_unique_uuids(arxml):
    """
    Ensures every XML element with a UUID attribute has a unique UUID.
    Updates duplicate UUIDs and writes changes back to the ARXML file.
    """
    root = arxml.xml.getroot()
    seen = {}
    for elem in root.findall('.//*[@UUID]'):
        current_uuid = elem.attrib['UUID']
        logging.debug("Checking UUID %s", current_uuid)
        if current_uuid in seen:
            new_uuid = replace_uuid(elem)
            seen[new_uuid] = elem
        else:
            seen[current_uuid] = elem

def add_prefix_to_elements_of_type(parent_elem, prefix, elem_type):
    """
        Adds a prefix to the SHORT-NAME of all elements which have parent_elem
        as parent and which have the given type. The elements' UUID is replaced
        with a new one.

        Example: add_prefix_to_elements_of_type('ABC', 'SYSTEM-SIGNAL')

        <SYSTEM-SIGNAL UUID=abc:123>
            <SHORT-NAME> X </SHORT-NAME>
        <SYSTEM-SIGNAL UUID=def:456>
            <SHORT-NAME> Y </SHORT-NAME>
                        |
                        v
        <SYSTEM-SIGNAL UUID=abc:111>
            <SHORT-NAME> ABCX </SHORT-NAME>
        <SYSTEM-SIGNAL UUID=def:222>
            <SHORT-NAME> ABCY </SHORT-NAME>
    """

    elements = xml_elem_findall(parent_elem, elem_type)
    for elem in elements:
        replace_uuid(elem)
        elem_name = xml_elem_find(elem, 'SHORT-NAME')
        elem_name.text = prefix + elem_name.text


def add_prefix_to_refs_of_type(parent_elem,
                               prefix,
                               type_ref,
                               has_property=lambda x: True):
    """
        Updates all REFs which have parent_elem as parent and are of the given
        type, to refer to a prefixed name.

        Usually used in conjunction with the add_prefix_to_elements_of_type in
        order to update the references to the new name. Optionally update only
        those REFs which have a specific property.

        Example: add_prefix_to_elements_of_type('ABC', 'SYSTEM-SIGNAL-REF')

        <SYSTEM-SIGNAL-REF> /pkg1/pkg2/X </SYSTEM-SIGNAL-REF>
        <SYSTEM-SIGNAL-REF> /pkg1/pkg3/Y </SYSTEM-SIGNAL-REF>
                             |
                             v
        <SYSTEM-SIGNAL-REF> /pkg1/pkg2/ABCX </SYSTEM-SIGNAL-REF>
        <SYSTEM-SIGNAL-REF> /pkg1/pkg3/ABCY </SYSTEM-SIGNAL-REF>
    """

    assert any(string in type_ref for string in ['-REF', '-TREF']), \
        "add_prefix_to_refs_of_type should only be used with references"
    refs = xml_elem_findall(parent_elem, type_ref)
    for ref in refs:
        if has_property(ref):
            if type_ref in ['ROOT-DATA-PROTOTYPE-REF', 'DATA-ELEMENT-REF']:
                # type_ref is ROOT-DATA-PROTOTYPE-REF or DATA-ELEMENT-REF.
                # add the prefix to port-interface and data element
                # in <port>/<portinterface>/<data element>
                ref_s = ref.text[1:].split('/')
                ref.text = f"/{ref_s[0]}/{ref_s[1]}/{prefix}{ref_s[2]}"
            elif type_ref in ['REQUIRED-INTERFACE-TREF','PROVIDED-INTERFACE-TREF']:
                # type_ref is REQUIRED-INTERFACE-TREF or PROVIDED-INTERFACE-TREF.
                # add the prefix to portinterface in <port>/<portinterface>
                ref_s = ref.text[1:].split('/')
                ref.text = f"/{ref_s[0]}/{prefix}{ref_s[1]}"
            else:
                # type_ref is SYSTEM-SIGNAL-REF, I-SIGNAL-REF,
                # I-SIGNAL-GROUP-REF, SYSTEM-SIGNAL-GROUP-REF,
                # I-SIGNAL-TRIGGERING-REF, FIBEX-ELEMENT-REF
                # add the prefix to signal or group signal
                ref.text = ref.text[:ref.text.rfind('/') + 1] +\
                       prefix +\
                       ref.text[ref.text.rfind('/') + 1:]



def xml_get_elem_from_path(src_arxml, path):
    """
        Returns the Element given by path

        For example, if path is /ECUExtractIHRAdpHIB/ComponentType/IHRAswarch
        then this function will return the IHRAswarch element by traversing
        the Element tree (ECUExtractIHRAdpHIB and ComponentType).

        Many REFs in .arxml files are paths such as this one, this function is
        useful in getting the Elements pointed to by those REFs.
    """

    path_elem_names = path.strip('/').split('/')

    elem = src_arxml.xml.getroot()
    for name in path_elem_names:
        elem = elem.find(".//*[" + autosar.base.add_schema('SHORT-NAME') +
                         "='" + name + "']")
        assert elem is not None,\
            "Could not traverse path %s, %s element not found" % (path, name)

    return elem


def get_root_sw_composition_type(arxml):
    """
        Find the COMPOSITION-SW-COMPONENT-TYPE which is associated with the
        root software composition. Given an arxml, start from its root and
        traverse the path required to obtain the Element corresponding
        to the type of the root software composition. We are looking for
        the type of the root software composition since it is the type that
        contains the ports (not the root software composition prototype).

        It is assumed that there is only one ROOT-SW-COMPOSITION-PROTOTYPE.

        ROOT-SW-COMPOSITION-PROTOTYPE ->
        SOFTWARE-COMPOSITION-TREF -> SOFTWARE-COMPOSITION ->
        TYPE-TREF -> ((COMPOSITION-SW-COMPONENT-TYPE))
    """

    try:
        root_sw_comp = xml_elem_find(arxml.xml.getroot(),
                                     'ROOT-SW-COMPOSITION-PROTOTYPE')
        sw_comp_tref = xml_elem_find(root_sw_comp,
                                     'SOFTWARE-COMPOSITION-TREF')
        sw_comp = xml_get_elem_from_path(arxml,
                                         sw_comp_tref.text)
        type_tref = xml_elem_find(sw_comp,
                                  'TYPE-TREF')
        src_sw_comp_type = xml_get_elem_from_path(arxml,
                                                  type_tref.text)

        return src_sw_comp_type
    except AttributeError:
        logging.error(
            "COMPOSITION-SW-COMPONENT-TYPE corresponding to the root software"
            "composition in %s cannot be found!", arxml.filename
        )
        return None


class ScriptOptions:
    @classmethod
    def test_file(cls, file):
        assert hasattr(cls, 'parser'), "The ScriptOptions.get must be called "\
                                       "first to initialize the parser!"
        # Print error if the file doesn't exist
        if not os.path.isfile(file):
            cls.parser.error("The file doesn't exist: %s" % file)

    @classmethod
    def get(cls, args, description, version, help_desc=None):

        if help_desc is None:
            help_desc = {
                'i': ('input_arxml', 'Input file to read.'),
                'o': ('output_arxml', 'Output file to write.')
            }

        usage = "Usage: %prog [options]"
        cls.parser = OptionParser(usage=usage,
                                  description=description,
                                  version="%%prog %s (%s)" %
                                  (version, autosar.VERSION))

        # Add parser options
        for opt, t in help_desc.items():
            dest, desc = t
            cls.parser.add_option('-' + opt, '--' + dest, dest=dest, help=desc)

        # Read the script's arguments
        (options, args) = cls.parser.parse_args(args)

        # Print help if input files are not specified
        dest, _ = help_desc['i']
        input_arxml = getattr(options, dest, None)
        if input_arxml is None:
            cls.parser.print_help(None)
            sys.exit(0)

        # Test if input files exists
        for arxml in input_arxml.split(','):
            cls.test_file(arxml)

        return options
