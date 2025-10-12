import os
import enna.core.time
import enna.core.config
import enna.core.interfaces.server
import enna.core.reporting.server_junit
import enna.core.component_system.decorators
import enna.core.interfaces.testing
import enna.core.interfaces.component
from hcp3.viwi.tests.constants import *

from hcp3.viwi.tests.subscription_timeout.subscription_timeout_fixture import SubscriptionTimeoutFixture

@enna.core.component_system.decorators.RequireComponent('enna.core.reporting')
class ViwiSubscriptionClusterTimeoutBehaviourIvi(SubscriptionTimeoutFixture):
    
    def __init__(self, reporting: enna.core.reporting.server_junit, *args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self.test_case_name = os.path.splitext(os.path.basename(__file__))[0]
        self.generate_pcap_traces = True

    def _precondition(self) -> bool:
        self._reporting.add_report_message_info(f'\n{"#" * 100}\n_precondition\n{"#" * 100}\n')
        return self.subscription_timeout_tc_precondition(partition = self.ivi_partition_name,
                                                            service_name = viwi_service)

    def _action(self) -> bool:
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\n_action\n{"#" * 100}\n')

            # fetch ws parameters from config
            self.ws_ping_pong_cycle_time_ws = int (self.get_rsi_gateway_parameter_value(partition = self.ivi_partition_name,
                                                                                            parameter = 'ws_ping_pong_cycle_time_ms',
                                                                                                section = ["client_connections", "*"]))/1000
            
            self.ws_ping_pong_max_unanswered_ping = self.get_rsi_gateway_parameter_value(partition=self.ivi_partition_name,
                                                                                            parameter = 'ws_ping_pong_max_unanswered_ping',
                                                                                                section = ["client_connections", "*"])
            self.simulate_viwi_flask_server()

            self.first_client_ws = self.mock_ws_subscription_with_tcp_message_drop(partition = self.ivi_partition_name,
                                                                                            service_name = viwi_service,
                                                                                                service_port = viwi_service_port,
                                                                                                    service_resource = viwi_resource)
            
            self.check_action_request_on_esotrace()
            
            result = self.check_ws_timings_parameters(self.ws_ping_pong_cycle_time_ws,
                                                        self.ws_ping_pong_max_unanswered_ping)
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False

            result = self.check_websocket_closure()

            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False

            result = self.check_esotrace_action_error()

            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            self._reporting.add_test_result_pass(self.test_case_name, 'SUCCESS')
            self._reporting.add_report_message_info('[PASSED] execution was successful')
            return True
            
        except Exception as error:
            self._reporting.add_test_result_system_error(self.test_case_name, f'FAILED:{error}')
            return False
    
    def _postcondition(self) -> bool:
        return self.subscription_timeout_tc_postcondition()
        
    
    