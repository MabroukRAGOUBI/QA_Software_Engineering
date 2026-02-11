import os
import enna.core.time
import enna.core.config
import enna.core.interfaces.server
import enna.core.reporting.server_junit
import enna.core.component_system.decorators
import enna.core.interfaces.testing
import enna.core.interfaces.component
from hcp3.viwi.tests.connection_handling_tcp.connection_handling_tcp_fixture import ConnectionHandlingTcpFixture

@enna.core.component_system.decorators.RequireComponent('enna.core.reporting')
class ViwiHttpKeepAliveHeaderClientIvi(ConnectionHandlingTcpFixture):
    service_name = "WiperUI"

    def __init__(self, reporting: enna.core.reporting.server_junit, *args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self.test_case_name = os.path.splitext(os.path.basename(__file__))[0]
        self.generate_pcap_traces = True


    def _precondition(self) -> bool:
        self._reporting.add_report_message_info(f'\n{"#" * 100}\n_precondition\n{"#" * 100}\n')
        return self.viwi_test_precondition()
    
    def _action(self) -> bool:
        self._reporting.add_report_message_info(f'\n{"#" * 100}\n_action\n{"#" * 100}\n') 
        
        try:
            result = self.client_http_request_contain_keepalive_header(partition = self.ivi_partition_name,
                                                                service_name = self.service_name)
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            self._reporting.add_test_result_pass(self.test_case_name, 'SUCCESS')
            self._reporting.add_report_message_info('[PASSED] execution was successful')
            return True
        
        except Exception as e:
            self._reporting.add_test_result_system_error(self.test_case_name, str(e))
            return False
        
    def _postcondition(self) -> bool:   
        self._reporting.add_report_message_info(f'\n{"#" * 100}\n_postcondition\n{"#" * 100}\n')     
        return self.viwi_test_postcondition()
    