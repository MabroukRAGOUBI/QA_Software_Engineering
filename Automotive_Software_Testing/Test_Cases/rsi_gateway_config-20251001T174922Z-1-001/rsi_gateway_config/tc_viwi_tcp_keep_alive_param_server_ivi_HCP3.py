import os
import enna.core.time
import enna.core.config
import enna.core.interfaces.server
import enna.core.reporting.server_junit
import enna.core.component_system.decorators
import enna.core.interfaces.testing
import enna.core.interfaces.component
from hcp3.viwi.tests.viwi_fixture import ViwiFixture

@enna.core.component_system.decorators.RequireComponent('enna.core.reporting')
class ViwiTcpKeepAliveParamServerIvi(ViwiFixture):
    service = 'ViWiTestabilityClassTwo'
    resource = 'switchControls'
    port = 29796
    tcp_keepalive_time_server :int
    tcp_keepalive_intvl_server :int
    tcp_keepalive_probes_server:int
    
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
            self.tcp_keepalive_time_server = self.get_rsi_gateway_parameter_value(self.ivi_partition_name, section =['server_general_options'], parameter="tcp_keep_alive_time")
            self.tcp_keepalive_intvl_server = self.get_rsi_gateway_parameter_value(self.ivi_partition_name, section =['server_general_options'], parameter="tcp_keep_alive_intvl")
            self.tcp_keepalive_probes_server = self.get_rsi_gateway_parameter_value(self.ivi_partition_name, section =['server_general_options'], parameter="tcp_keep_alive_probes")

            tcp_keepAlive_capturing_time = self.tcp_keepalive_time_server + self.tcp_keepalive_intvl_server * self.tcp_keepalive_probes_server + 2 * self.tcp_keepalive_time_server
            
            result = self.send_ws_subscription_request_and_check_tcp_parameters(host = self.ivi_ip, port = self.port, service = self.service, resource = self.resource,
                                                                                    keepalive_time = self.tcp_keepalive_time_server, 
                                                                                        keepalive_intvl = self.tcp_keepalive_intvl_server, 
                                                                                            keepalive_probes = self.tcp_keepalive_probes_server, 
                                                                                                capturing_time = tcp_keepAlive_capturing_time)
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
        self.viwi_test_postcondition()
        self.resume_sending_tcp_messages()
        return True
