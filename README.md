# Com-Merger

- [x] util.py: replace deprecated libraries with std lib modules
- [ ] util.py: prefer using xml_elem_namespace_new over xml_elem_namespace
- [ ] util.py: def xml_ecu_sys_name_get(arxml) needs to be fixed
- [x] going thru documentation of the other libraries to see if i can reimplement the functions using only the std lib, should complete util.py this weekend


### To do
- look at xml_ecu_sys_name_get
- xml_elem_extend_name_clashed && xml_ar_packages_missing depend on xml_ecu_sys_name_get. check that they still work if xml_ecu_sys_name_get was touched.
- PyAUTOSAR 3.9.1+


### Can move
- xml_get_physial_channel (uses only native python modules and fxns from util)
- fetch_pdus (uses only native python modules and fxns from util)
- copy_communication_packages (maybe - uses uuid but that is also imported in util.py, fills the error handling arrays in util.py)



### Diffs (Use function overloading???)
- HIA & HIB: def create_socket_connection_bundle(bundle, src_arxml, dst_arxml,
                                    frames, pdus, dst_eth_physical_channel):

- def fix_ihfa_ihra_naming(src_arxml):
- def copy_ecpi_to_ethernet_connectors(dst_arxml):
- def update_reference(ref):
