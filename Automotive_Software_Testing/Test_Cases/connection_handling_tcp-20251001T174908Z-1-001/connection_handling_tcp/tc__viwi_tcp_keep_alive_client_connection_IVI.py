import os
import enna.core.time
import enna.core.config
import enna.core.interfaces.server
import enna.core.reporting.server_junit
import enna.core.component_system.decorators
import enna.core.interfaces.testing
import enna.core.interfaces.component
from hcp3.viwi.tests.constants import*
from hcp3.viwi.tests.http_server import*
from hcp3.viwi.tests.connection_handling_tcp.connection_handling_tcp_fixture import ConnectionHandlingTcpFixture

@enna.core.component_system.decorators.RequireComponent('enna.core.reporting')
class ViwiTcpKeepAliveClientConnectionIvi(ConnectionHandlingTcpFixture):

    first_service_name = "CallServices"
    first_service_keepalive_time = 3
    first_service_keepalive_intvl = 2
    first_service_keepalive_probes = 3
    first_tcp_keep_alive_capturing_time = first_service_keepalive_time + first_service_keepalive_intvl * first_service_keepalive_probes + 2 * first_service_keepalive_time

    second_service_name = "DisasterWarnings"
    second_service_keepalive_time = 2
    second_service_keepalive_intvl = 3
    second_service_keepalive_probes = 2
    second_tcp_keep_alive_capturing_time = second_service_keepalive_time + second_service_keepalive_intvl * second_service_keepalive_probes + 2 * second_service_keepalive_time


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

            result = self.change_client_service_tcp_keepAlive_parameters(partition = self.ivi_partition_name,
                                                                service = self.first_service_name,
                                                                    keepalive_time = self.first_service_keepalive_time,
                                                                        keepalive_intvl = self.first_service_keepalive_intvl,
                                                                            keepalive_probes = self.first_service_keepalive_probes)
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            result = self.change_client_service_tcp_keepAlive_parameters(partition = self.ivi_partition_name,
                                                                service = self.second_service_name,
                                                                    keepalive_time = self.second_service_keepalive_time,
                                                                        keepalive_intvl = self.second_service_keepalive_intvl,
                                                                            keepalive_probes = self.second_service_keepalive_probes)
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
        
            result = self.apply_config_changes(self.ivi_partition_name)

            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            
            result = self.check_client_tcp_socket_parameters(partition = self.ivi_partition_name,
                                                     service_name = self.first_service_name,
                                                            capturing_time = self.first_tcp_keep_alive_capturing_time,
                                                                keepalive_time = self.first_service_keepalive_time,
                                                                    keepalive_intvl = self.first_service_keepalive_intvl,
                                                                        keepalive_probes = self.first_service_keepalive_probes)
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            result = self.check_client_tcp_socket_parameters(partition = self.ivi_partition_name,
                                                     service_name = self.second_service_name,
                                                            capturing_time = self.second_tcp_keep_alive_capturing_time,
                                                                keepalive_time = self.second_service_keepalive_time,
                                                                    keepalive_intvl = self.second_service_keepalive_intvl,
                                                                        keepalive_probes = self.second_service_keepalive_probes)
            
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
        self.restore_initial_rsi_config(self.ivi_partition_name)
        self.resume_sending_tcp_messages()
        return self.viwi_test_postcondition()
