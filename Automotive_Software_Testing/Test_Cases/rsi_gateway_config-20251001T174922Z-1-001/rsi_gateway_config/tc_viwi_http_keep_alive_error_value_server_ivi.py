import os
import enna.core.time
import enna.core.config
import enna.core.interfaces.server
import enna.core.reporting.server_junit
import enna.core.component_system.decorators
import enna.core.interfaces.testing
import enna.core.interfaces.component
from hcp3.viwi.tests.rsi_gateway_config.rsi_gateway_config_fixture import RsiGatewayConfigFixture

@enna.core.component_system.decorators.RequireComponent('enna.core.reporting')
class ViwiHttpKeepAliveErrorValueServerIvi(RsiGatewayConfigFixture):
    host = 'fd53:7cb8:383:3::130'
    port = 29796
    service_name = "ViWiTestabilityClassTwo"
    http_keep_alive_timeout_ms = 10000
    tcp_user_timeout_ms = 60000

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
            Change values of 'http_keep_alive_timeout_ms' & 'tcp_user_timeout_ms' defined in IVI RSI Gateway within 'server_general_options' and check that IVI TCP connection is closed after the defined 'http_keep_alive_timeout_ms' value
                * Create IVI RSI Gateway backup 
                * Change values of 'http_keep_alive_timeout_ms' & 'tcp_user_timeout_ms' defined in IVI RSI Gateway within 'server_general_options'
                * Send root GET/ViWiTestabilityClassTwo request to HCP3
                * Check That IVI tcp connection is closed after the defined http_keep_alive_timeout_ms 
                * Restore initial values of 'http_keep_alive_timeout_ms' & 'tcp_user_timeout_ms' for cleanup 
            """

            result = self.modify_rsi_gateway_config(partition = self.ivi_partition_name,
                                                        section = ['server_general_options'],
                                                            parameter = 'http_keep_alive_timeout_ms',
                                                                value = self.http_keep_alive_timeout_ms)
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            result = self.modify_rsi_gateway_config(partition = self.ivi_partition_name,
                                            section = ['server_general_options'],
                                              parameter = 'tcp_user_timeout_ms',
                                                value = self.tcp_user_timeout_ms)
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
        
            result = self.apply_config_changes(self.ivi_partition_name)
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            result =self.send_root_get_and_check_server_tcp_timeout_connection(host = self.host,
                                                                                service = self.service_name,
                                                                                    port = self.port,
                                                                                        http_keep_alive_timeout_ms = self.http_keep_alive_timeout_ms)
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
   
            self._reporting.add_test_result_pass(self.test_case_name, 'SUCCESS')
            self._reporting.add_report_message_info('[PASSED] execution was successful')
            return True
        
        except Exception as e:
            self._reporting.add_report_message_system_error(f'[FAILED] execution threw an error - {e}')
            self._reporting.add_test_result_system_error(self.test_case_name, str(e))
            return False

    def _postcondition(self) -> bool:
        self._reporting.add_report_message_info(f'\n{"#" * 100}\n_postcondition\n{"#" * 100}\n')
        return self.viwi_test_postcondition()





        


    