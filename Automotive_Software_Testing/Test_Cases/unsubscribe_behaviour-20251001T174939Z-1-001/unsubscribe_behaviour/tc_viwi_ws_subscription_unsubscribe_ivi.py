import os
import enna.core.time
import enna.core.config
import enna.core.interfaces.server
import enna.core.reporting.server_junit
import enna.core.component_system.decorators
import enna.core.interfaces.testing
import enna.core.interfaces.component

from hcp3.viwi.tests.constants import *
from hcp3.viwi.tests.unsubscribe_behaviour.unsubscribe_behaviour_fixture import UnsubscribeBehaviourFixture

@enna.core.component_system.decorators.RequireComponent('enna.core.reporting')
class ViwiWsSubscriptionUnsubscribeIvi(UnsubscribeBehaviourFixture):

    def __init__(self, reporting: enna.core.reporting.server_junit, *args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self.test_case_name = os.path.splitext(os.path.basename(__file__))[0]
        self.generate_pcap_traces = True

    def _precondition(self) -> bool:
        self._reporting.add_report_message_info(f'\n{"#" * 100}\n_precondition\n{"#" * 100}\n')
        return self.unsubscribe_behaviour_tc_precondition(partition = self.ivi_partition_name,
                                                            service_name = viwi_service)

    def _action(self) -> bool:
        self._reporting.add_report_message_info(f'\n{"#" * 100}\n_action\n{"#" * 100}\n')
        try:
            self.simulate_viwi_flask_server()

            self.first_client_ws = self.mock_ws_subscription(partition = self.ivi_partition_name,
                                                                service_name = viwi_service,
                                                                    service_port = viwi_service_port,
                                                                        service_resource = viwi_resource)

            result = self.check_action_request_on_esotrace()

            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False

            self.second_client_ws = self.mock_ws_subscription(partition = self.ivi_partition_name,
                                                                service_name = viwi_service,
                                                                    service_port = viwi_service_port,
                                                                        service_resource = viwi_resource) 

            result = self.check_action_request_on_esotrace()

            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False

            self.acknowledge_received_ws_subscription()

            result = self.check_mocked_client_subscription_acknowledgement(self.first_client_ws, self.second_client_ws)
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            result = self.check_action_response_on_esotrace(self.request_ids_list)
       
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            self.unsubscribe_subscribed_client(self.first_client_ws)

            result = self.check_socket_not_closed_with_simulated_server()
                        
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False

            self.simulate_ws_update_event()
            
            result = self.check_action_response_unsubscribed_on_esotrace()

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
        return self.unsubscribe_behaviour_tc_postcondition()
    


    