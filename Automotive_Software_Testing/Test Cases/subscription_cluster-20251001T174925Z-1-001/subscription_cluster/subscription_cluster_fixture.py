import json

import enna.core.reporting.interface

from hcp3.viwi.tests.constants import *
from hcp3.viwi.tests.flask_server import *
from hcp3.viwi.tests.websocket_server import *
from hcp3.viwi.tests.viwi_fixture import ViwiFixture

class SubscriptionClusterFixture(ViwiFixture):
    def __init__(self, reporting: enna.core.reporting.interface.Interface,*args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self._reporting = reporting

    def subscription_cluster_tc_precondition(self, partition:str,service_name:str):
        """ Prepare the preconditions for the subscription cluster test case execution.

        :param partition: Partition name
        :param service_name: Service name
        :return: True if preconditions are successfully set, False otherwise
        :rtype: bool
        """
        try:
            self.viwi_test_precondition()
            self.disable_partition_firewall(partition)
            # Start esotrace capture
            self.start_capturing_esotrace(partition,self.esotrace_action_message_callback(service_name))  
            return True
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Failed to start subscription cluster tc precondition: {error}')
            return False

    def receive_client_ws_subscription_request(self):
        """ Receive and process the DUT as client WebSocket subscription request.
        """
        client_subscription_request = get_next_websocket_server_request(self.viwi_ws_server)

        if client_subscription_request is not None:
            if "subscribe" in client_subscription_request and "/ViWiTestability/switchControls" in client_subscription_request:
                self._reporting.add_report_message_info("ViWiTestabilityClassTwo/switchControls resource is properly mocked to the simulated server")
            else:
                self._reporting.add_report_message_info(f"Unexpected subscription request received:{client_subscription_request}")
        else:
            self._reporting.add_report_message_info('Second Subscription is not sent by DUT, subscription is clustered')
    
    def acknowledge_received_ws_subscription_request(self):
        """ Acknowledge the received WebSocket subscription request.
        """
        subscription_ack_response = {
        "type": "subscribe",
        "status": "ok",
        "event": "/ViWiTestability/switchControls/#1"
                                    }
        send_websocket_server_response(self.viwi_ws_server, response=json.dumps(subscription_ack_response)) 
        initial_event_message = {
                        "type": "data",
                        "status":"ok",
                        "event": "/ViWiTestability/switchControls/#1",
                        "data":[{"id":"91c71fa6-6d18-46c9-af23-5433b7313609","name":"switchCtrlOne","uri":"/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609","restrictionReason":"one","switchValue":"two","switchValueConfiguration":["one","two","three"]}]
                                }
                    
        send_websocket_server_response(self.viwi_ws_server, response=json.dumps(initial_event_message))
    
    def check_time_difference_between_first_action_request_and_dut_ws_request(self):
        """ Check the time difference between the first esotrace action request and the DUT WebSocket subscription request.

        :return: False (to be performed manually)
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nStep: Check the time difference between esotrace first "actionrequest" and ws subscription request mocked by HCP3 will be performed manually\n{"#" * 100}\n')             
        return False

    def subscription_cluster_tc_postcondition(self):
        """ Cleanup actions and reset the system to its postconditions after the subscription cluster test case.
        
        :return: True if preconditions are successfully set, False otherwise
        :rtype: bool
        """
        try:
            self.close_client_websocket()
            if hasattr(self, 'viwi_ws_server') and self.viwi_ws_server:
                stop_websocket_server(self.viwi_ws_server)
            if hasattr(self, 'flask_server') and self.flask_server:
                stop_flask_server(self.flask_server)
        except Exception as e:
            self._reporting.add_report_message_system_error(f"Error stopping viwi server: {e}")

        self.stop_esotrace_capture()
        self.esotrace_queue_evt.clear()
        self.clear_esotrace_queue()
        self.delete_registered_service(location=self.registered_service_location)
        return self.viwi_test_postcondition()