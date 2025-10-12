import os
import enna.core.time
import enna.core.config
import enna.core.interfaces.server
import enna.core.reporting.server_junit
import enna.core.component_system.decorators
import enna.core.interfaces.testing
import enna.core.interfaces.component
from hcp3.viwi.tests.constants import *
from hcp3.viwi.tests.connection_handling_tcp.connection_handling_tcp_fixture import ConnectionHandlingTcpFixture

@enna.core.component_system.decorators.RequireComponent('enna.core.reporting')
class ViwiTcpKeepAliveServerConnection(ConnectionHandlingTcpFixture):

    first_service_name= "ViWiTestabilityClassTwo"
    first_resource = "switchControls"
    first_service_port = 0
    first_service_tcp_keep_alive_time = 3
    first_service_tcp_keep_alive_intvl = 2
    first_service_tcp_keep_alive_probes = 3

    first_tcp_keep_alive_capturing_time = first_service_tcp_keep_alive_time + first_service_tcp_keep_alive_intvl * first_service_tcp_keep_alive_probes + 2 * first_service_tcp_keep_alive_intvl
    
    second_service_name = "PrivacySetupShapeThree"
    second_resource = "currentStatusClients"
    second_service_port = 0
    second_service_tcp_keep_alive_time = 2
    second_service_tcp_keep_alive_intvl = 3
    second_service_tcp_keep_alive_probes = 2

    second_tcp_keep_alive_capturing_time = second_service_tcp_keep_alive_time + second_service_tcp_keep_alive_intvl * second_service_tcp_keep_alive_probes + 2 * second_service_tcp_keep_alive_intvl

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
            """
                * Create IVI RSI Gateway backup 
                * Change values of "tcp_keep_alive_time" , "tcp_keep_alive_intvl" and "tcp_keep_alive_probes" within 'server_general_options' defined in IVI RSI_Gateway.json file
                * Change values of "tcp_keep_alive_time" , "tcp_keep_alive_intvl" and "tcp_keep_alive_probes" for "/PrivacySetupShapeThree" service defined in IVI RSI_Gateway.json file
                * Reboot IVI
                * Send WS Subscription on /"ViWiTestabilityClassTwo/switchControls" resource to IVI
                * Check that next TCP keep alive is sent by IVI after "tcp_keep_alive_time" then ech "tcp_keepalive_intvl" for total retries number equal to "tcp_keep_alive_probes"  as configured in step 01
                * Send WS Subscription on /"PrivacySetupShapeThree/currentStatusClients" resource to IVI
                * Check that next TCP keep alive is sent by IVI after "tcp_keep_alive_time" then ech "tcp_keepalive_intvl" for total retries number equal to "tcp_keep_alive_probes"  as configured for "/PrivacySetupShapeThree" service tcp keepAlive parameters
                * Restore initial values of tcp KeepAlive values for cleanup 
            """

            result , self.first_service_port = self.change_server_service_tcp_keepAlive_parameters(partition = self.ivi_partition_name, 
                                                                        tcp_keep_alive_time = self.first_service_tcp_keep_alive_time,
                                                                        tcp_keep_alive_intvl = self.first_service_tcp_keep_alive_intvl, 
                                                                        tcp_keep_alive_probes = self.first_service_tcp_keep_alive_probes,
                                                                        service_name = self.first_service_name)
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            result, self.second_service_port = self.change_server_service_tcp_keepAlive_parameters(partition = self.ivi_partition_name,
                                                                         tcp_keep_alive_time = self.second_service_tcp_keep_alive_time,
                                                                          tcp_keep_alive_intvl = self.second_service_tcp_keep_alive_intvl, 
                                                                          tcp_keep_alive_probes = self.second_service_tcp_keep_alive_probes, 
                                                                          service_name = self.second_service_name)
            if not result :
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            result = self.apply_config_changes(self.ivi_partition_name)
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            result = self.send_ws_subscription_request_and_check_tcp_parameters(self.ivi_ip, self.first_service_port, self.first_service_name, self.first_resource,
                                                                                 keepalive_time = self.first_service_tcp_keep_alive_time, 
                                                                                 keepalive_intvl = self.first_service_tcp_keep_alive_intvl, 
                                                                                 keepalive_probes = self.first_service_tcp_keep_alive_probes, 
                                                                                 capturing_time = self.first_tcp_keep_alive_capturing_time)
            if not result :
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False

            result = self.send_ws_subscription_request_and_check_tcp_parameters(self.ivi_ip, self.second_service_port, self.second_service_name, self.second_resource,
                                                                                 keepalive_time = self.second_service_tcp_keep_alive_intvl, 
                                                                                 keepalive_intvl = self.second_service_tcp_keep_alive_intvl, 
                                                                                 keepalive_probes = self.second_service_tcp_keep_alive_probes,
                                                                                 capturing_time = self.second_tcp_keep_alive_capturing_time)
            if not  result:
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
        return self.viwi_test_postcondition()


        


    