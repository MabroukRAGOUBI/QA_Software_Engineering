import websocket
import enna.core.reporting.interface
from hcp3.viwi.tests.constants import *
from hcp3.viwi.tests.flask_server import *

from hcp3.viwi.tests.viwi_fixture import ViwiFixture

class UnsubscribeBehaviourFixture(ViwiFixture):
    def __init__(self, reporting: enna.core.reporting.interface.Interface,*args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self._reporting = reporting

    def unsubscribe_behaviour_tc_precondition(self, partition:str,service_name:str):
        try:
            self.viwi_test_precondition()
            self.disable_partition_firewall(partition)
            # Start esotrace capture
            self.start_capturing_esotrace(partition,self.esotrace_action_message_callback(service_name))  
            return True
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Failed to start subscription cluster tc precondition: {error}')
            return False
    
    def unsubscribe_subscribed_client(self,client_ws:websocket):
        unsubscription_data = {
                "type": "unsubscribe",
                "event": "/ViWiTestability/switchControls"
            }
        client_ws.send(unsubscription_data)

    def check_action_response_unsubscribed_on_esotrace(self):
            try:
                self.hold_capturing_esotrace_messages()
                first_resp_received = False
                second_resp_received = False

                while self.esotrace_actionresponse_queue.qsize != 0:
                    msg = self.esotrace_actionresponse_queue.get(timeout=1)
                    if '"requestId"' in str(msg.value["message_data"]):
                        msg_data = str(msg.value["message_data"])
                        msg_split = msg_data.split(sep=",")
                        request_id = int(next((e.split(sep=":"))[1] for e in msg_split if 'requestId' in e))
                        if request_id == self.request_ids_backup_list[0]:
                            first_resp_received= True
                        elif request_id == self.request_ids_backup_list[1]:
                            second_resp_received = True
                        
                        if first_resp_received and second_resp_received:
                            self._reporting.add_report_message_info('Failed checking actionResponse on esotrace, both clients received event update')
                            return False
            except Exception as e:
                if not first_resp_received and second_resp_received:
                    return True
                else:
                    self._reporting.add_report_message_system_error(f'Error checking actionResponse on esotrace:{e}')
                    return False     
    
    def simulate_ws_update_event(self):
        event_data_update = {
        "data":[{'id':'91c71fa6-6d18-46c9-af23-5433b7313609','name':'switchCtrlOne','uri':'/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609','restrictionReason':'one','switchValue':'one','switchValueConfiguration':['one','two','three']}],
        "type":"data",
        "event":"ViWiTestability}/#1",
        "Content-Type":"application/json; charset=utf-8"
                            }
        send_ws_server_response(self.flask_server, [event_data_update]) 
    
    def check_socket_not_closed_with_simulated_server(self):
        client_socket_data = get_next_flask_server_websocket_request()
        if client_socket_data:
            if 'unsubscribe' in client_socket_data:
                self._reporting.add_report_message_system_error(f'received unsbscription request from the Dut after unsudscribing the first mocked client:{client_socket_data}')
                return False
        else:
            self._reporting.add_report_message_info(" Dut kept the the ongoing WS connection opened - Success")
            return True
    
    def unsubscribe_behaviour_tc_postcondition(self):
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