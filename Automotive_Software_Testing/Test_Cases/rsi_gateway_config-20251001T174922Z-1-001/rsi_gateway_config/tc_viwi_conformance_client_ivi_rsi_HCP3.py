import os
import enna.core.time
import enna.core.config
import enna.core.interfaces.server
import enna.core.reporting.server_junit
import enna.core.component_system.decorators
import enna.core.interfaces.testing
import enna.core.interfaces.component
from hcp3.viwi.tests.rsi_gateway_config.rsi_gateway_config_fixture import RsiGatewayConfigFixture
from hcp3.viwi.tests.constants import*

@enna.core.component_system.decorators.RequireComponent('enna.core.reporting')
class ViwiConformanceClientIvi(RsiGatewayConfigFixture):

    def __init__(self, reporting: enna.core.reporting.server_junit, *args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self.test_case_name = os.path.splitext(os.path.basename(__file__))[0]

    def _precondition(self) -> bool:
        self._reporting.add_report_message_info(f'\n{"#" * 100}\n_precondition\n{"#" * 100}\n')
        return self.viwi_test_precondition()

    def _action(self) -> bool:
        self._reporting.add_report_message_info(f'\n{"#" * 100}\n_action\n{"#" * 100}\n')
        
        try:
            result = self.check_rsi_gateway_config_conformity(partition = self.ivi_partition_name,
                                                               vehicle_platform = hcp3_vehicle_platform)
           
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

 