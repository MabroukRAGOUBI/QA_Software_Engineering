import os
import enna.core.time
import enna.core.config
import enna.core.interfaces.server
import enna.core.reporting.server_junit
import enna.core.component_system.decorators
import enna.core.interfaces.testing
import enna.core.interfaces.component

from hcp3.viwi.tests.constants import *
from hcp3.viwi.tests.subscription_race_condition.subscription_race_condition_fixture import SubscriptionRaceConditionFixture

@enna.core.component_system.decorators.RequireComponent('enna.core.reporting')
class Viwi_Ws_SubscriptionClusterRaceConditionElementIvi(SubscriptionRaceConditionFixture):
   
    viwi_element="/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609"

    first_client_switch_value = ""
    first_client_element_switch_value = ""
    second_client_switch_value = ""
    second_client_element_switch_value = ""
    update_element_switchValue= "one"
    get_resp_switchValue= "two"

    def __init__(self, reporting: enna.core.reporting.server_junit, *args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self.test_case_name = os.path.splitext(os.path.basename(__file__))[0]
        self.generate_pcap_traces = True

    def _precondition(self) -> bool:
        return self.subscription_race_condition_tc_precondition()

    def _action(self) -> bool:
        try:
            self.simulate_viwi_flask_server()
            self.first_client_ws = self.mock_ws_subscription(partition = self.ivi_partition_name,
                                                                service_name = viwi_service,
                                                                    service_port = viwi_service_port,
                                                                        service_resource = viwi_resource,
                                                                            autosubscribe = True) 
            result = self.check_action_request_on_esotrace()
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False

            self.acknowledge_received_ws_subscription() 
            
            result = self.check_mocked_client_subscription_acknowledgement(self.first_client_ws)
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False 
            
            result = self.check_action_response_on_esotrace(self.request_ids_list)
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False 
            
            result = self.acknowledge_received_ws_element_subscription() 
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False 
            
            self.second_client_ws = self.mock_ws_subscription(partition = self.ivi_partition_name,
                                                                service_name = viwi_service,
                                                                    service_port = viwi_service_port,
                                                                        service_resource = viwi_resource,
                                                                            autosubscribe = True)
            result = self.receive_client_http_request()
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False
            
            result = self.check_action_request_on_esotrace()
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False

            self.simulate_element_update_event()

            result = self.check_mocked_client_update_event_reception(self.first_client_ws, self.second_client_ws)
            
            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False

            result = self.check_action_response_on_esotrace(self.request_ids_backup_list)

            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False

            self.simulate_http_get_response()

            result = self.check_no_action_response_forwarded_to_mocked_clients()

            if not result:
                self._reporting.add_test_result_system_error(self.test_case_name, 'FAILED')
                return False

            return True
        except Exception as error:
            self._reporting.add_test_result_system_error(self.test_case_name, f'FAILED:{error}')
            return False


        