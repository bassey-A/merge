# Com-Merger

- [x] util.py: replace deprecated libraries with std lib modules
- [ ] util.py: prefer using xml_elem_namespace_new over xml_elem_namespace
- [x] util.py: def xml_ecu_sys_name_get(arxml) needs to be fixed
- [x] going thru documentation of the othdeprecated libraries what functionality reimplemented the std lib


### To do



### Can move
- xml_get_physial_channel (uses only native python modules and fxns from util)
- fetch_pdus (uses only native python modules and fxns from util)
- copy_communication_packages (maybe - uses uuid but that is also imported in util.py, fills the error handling arrays in util.py)



### Diffs (Use function overloading???)
- eg HIA & HIB: def create_socket_connection_bundle(bundle, src_arxml, dst_arxml,
                                    frames, pdus, dst_eth_physical_channel):

- def fix_ihfa_ihra_naming(src_arxml):
- def copy_ecpi_to_ethernet_connectors(dst_arxml):
- def update_reference(ref):


## FLOW
- copy_socket_connection_bundles
- copy_socket_addresses
- create_socket_connection_bundle


## OBSERVATIONS
  The old implementation solved a really complex task excellently but can be improved in a few ways:
  - The use of indexing (eg pdu[0]) should be replaced with search for specific elements (eg using util.xml_elem_find(elem)). This way, the script will successfully run even with input files that have slight changes in the index position of elements.
  - Some of the third party python modules / libraries used are now deprecated. Adding new features that will likely depend on modern features / libraries may lead to dependency conflicts. It may be more beneficial to replace deprecated libraries before adding new features.
  - 
## Common Functions
  - xml_get_physical_channel
  - fetch_pdu
  - def copy_communication_packages
  - copy_fibex_elements
  - copy_isignal_and_pdu_triggerings
  - prepare_ethernet_physical_channel
  - copy_network_endpoint
  - copy_socket_connection_bundles
  - copy_socket_addresses
  - create_socket_connection_bundle
  - add_mr_com_flavour
  - fix_ihfa_ihra_naming
  - add_swbasetype_arpackage
  - copy_ecpi_to_ethernet_connectors
  - add_transfer_property_to_signals
  - update_reference
  - copy_and_append_data_mappings
