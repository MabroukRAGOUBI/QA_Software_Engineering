import socket
import enna.core.reporting.interface

from hcp3.viwi.tests.constants import *
from hcp3.viwi.tests.flask_server import *
from hcp3.viwi.tests.websocket_server import *
from hcp3.viwi.tests.viwi_fixture import ViwiFixture

class SubscriptionRaceConditionFixture(ViwiFixture):
    def __init__(self, reporting: enna.core.reporting.interface.Interface,*args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self._reporting = reporting

    def subscription_race_condition_tc_precondition(self, partition:str, service_name:str):
        try:
            self.viwi_test_precondition()
            self.disable_partition_firewall(partition)
            # Start esotrace capture
            self.start_capturing_esotrace(partition,self.esotrace_action_message_callback(service_name))  
            return True
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Failed to start subscription race condition tc precondition: {error}')
            return False      
        
    def simulate_source_update_event(self):
        self._reporting.add_report_message_info(f'\n{"*" * 10}Simulating update event for source{"*" * 10}\n')
        update_event_data_one = {
        "data":[{'id':'91c71fa6-6d18-46c9-af23-5433b7313609','name':'switchCtrlOne','uri':'/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609','restrictionReason':'one','switchValue':'one','switchValueConfiguration':['one','two','three']}],
        "type":"data",
        "event":"/ViWiTestability/switchControls/#1",
        "Content-Type":"application/json; charset=utf-8"
        }
        send_ws_server_response(self.flask_server,[update_event_data_one])
        self._reporting.add_report_message_info('Successfully simulated update event')

    def check_mocked_client_update_event_reception(self, *client_ws_list):
        try:
            # Set timeout for all clients
            for client_ws in client_ws_list:
                client_ws.settimeout(10)
                self.client_ws_list.append(client_ws)
            
            for index, client_ws in enumerate(client_ws_list, start=1):
                # Receive ws subscription ack for each client
                update_event_data = client_ws.recv()


                if update_event_data:
                    self._reporting.add_report_message_info(f'ws update event is received for mocked client {index}: {update_event_data}')
                else:
                    self._reporting.add_report_message_system_error(f'No ws update event is received for mocked client {index}.')
                    return False

            return True
        except socket.timeout:
            self._reporting.add_report_message_system_error('Timeout occurred while waiting for data from the clients.')
            return False
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Failed to receive initial event for clients: {error}')
            return False  

    def check_no_action_response_forwarded_to_mocked_clients(self):
        self._reporting.add_report_message_info('check no actionResponse on esotrace')
        result = self.check_action_response_on_esotrace()
        if not result :
            self._reporting.add_report_message_info('Successfully check no actionResponse on esotrace')
            return True
        else:
            self._reporting.add_report_message_system_error('Failed to check no actionResponse on esotrace')
            return False

    def simulate_element_update_event(self):
        self._reporting.add_report_message_info(f'\n{"*" * 10}Simulating update event for element{"*" * 10}\n')
        update_event_data_one = {
        "data":[{'id':'91c71fa6-6d18-46c9-af23-5433b7313609','name':'switchCtrlOne','uri':'/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609','restrictionReason':'one','switchValue':"one",'switchValueConfiguration':['one','two','three']}],
        "type":"data",
        "status": "ok",
        "event":"/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609#1"
        }
        send_ws_server_response(self.flask_server,[update_event_data_one])
        self._reporting.add_report_message_info('Successfully simulated update event')

    def acknowledge_received_ws_element_subscription(self):
        client_ws_request = get_next_flask_server_websocket_request(self.flask_server)
        if client_ws_request is not None:
            if "subscribe" in client_ws_request:
                sub_event = client_ws_request.get('event')
                uuid = sub_event.split("#")[1]
                if "/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609" in sub_event:
                    self._reporting.add_report_message_info("######## Autosubscribe to element ack ##########")
                    subscription_ack_element_data = {
                        "type": "subscribe",
                        "event": f"/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609/#{uuid}",
                        "status": "ok"
                    }

                    initial_event_element_data = {
                        "data":[{'id':'91c71fa6-6d18-46c9-af23-5433b7313609','name':'switchCtrlOne','uri':'/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609','restrictionReason':'one','switchValue':'two','switchValueConfiguration':['one','two','three']}],
                        "type":"data",
                        "status": "ok",
                        "event":f"/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609#{uuid}"
                        }
                    send_ws_server_response(self.flask_server,[subscription_ack_element_data,initial_event_element_data])
                    return True
        else:
            return False 
                         
    def subscription_race_condition_tc_postcondition(self):
        try:
            self.close_client_websocket()
            if hasattr(self, 'flask_server') and self.flask_server:
                stop_flask_server(self.flask_server)
        except Exception as e:
            self._reporting.add_report_message_system_error(f"Error stopping viwi server: {e}")

        self.stop_esotrace_capture()
        self.esotrace_queue_evt.clear()
        self.clear_esotrace_queue()
        self.delete_registered_service(location=self.registered_service_location)
        return self.viwi_test_postcondition()  