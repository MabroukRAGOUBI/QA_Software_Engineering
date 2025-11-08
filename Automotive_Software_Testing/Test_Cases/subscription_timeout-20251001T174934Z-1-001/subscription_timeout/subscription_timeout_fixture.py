import queue
import andisdk
import enna.core.reporting.interface

from hcp3.viwi.tests.constants import *
from hcp3.viwi.tests.flask_server import *
from hcp3.viwi.tests.viwi_fixture import ViwiFixture

class SubscriptionTimeoutFixture(ViwiFixture):
    def __init__(self, reporting: enna.core.reporting.interface.Interface,*args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self._reporting = reporting
        self.tcp_connection_closed : bool = False
        self.connection_closed : bool = False
        self.actionError_received :bool = False
        self.http_msg_queue = queue.Queue()

    def subscription_timeout_tc_precondition(self, partition:str, service_name:str):
        try:
            self.viwi_test_precondition()
            self.disable_partition_firewall(partition)
            # Start esotrace capture
            self.start_capturing_esotrace(partition,self.esotrace_message_callback(service_name))  
            return True
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Failed to start subscription cluster tc precondition: {error}')
            return False   

    def esotrace_message_callback(self,service_name:str):
        def on_esotrace_message(msg: 'enna.core.interfaces.Data'):
            if not self.esotrace_queue_evt.is_set():
                if service_name in str(msg.value["message_data"]):
                    if 'actionRequest' in str(msg.value["message_data"]):
                        self._reporting.add_report_message_info(f'##### Esotrace actionRequest message captured: {msg}')
                        self.esotrace_actionrequest_queue.put(msg)
                    elif 'actionError' in str(msg.value["message_data"]) and '"statusCode":502' in str(msg.value["message_data"]):
                        self._reporting.add_report_message_info(f'##### Esotrace actionError message captured: {msg}')
                        self.actionError_received = True
        return on_esotrace_message    
  
    def mock_ws_subscription_with_tcp_message_drop(self, partition:str, service_name:str, service_port:int, service_resource:str, autosubscribe: bool = False):
        
        if partition == self.ivi_partition_name:
            host = self.ivi_ip
        else:
            host = self.sys_ip    
        if not self.service_registred:
            self.register_service(service = service_name,
                                    server_ip = tester_server_ip,
                                        server_port = tester_server_port,
                                            host = host,
                                                port = tester_debugging_port)
            self.service_registred = True

        if not self.service_logs_active:
            self.enable_service_channel_logs(service_name)
            self.service_logs_active = True

        self.start_capturing_tcp_messages(self.http_listner_callback())

        ws_uri = f'ws://[{host}]:{service_port}/{service_name}'
        client_ws = self.create_ws_connection(uri = ws_uri)
        self.client_ws_source_ports.append(client_ws.sock.getsockname()[1])
        
        self.send_ws_subscription_request(ws = client_ws,
                                            service = service_name,
                                                resource = service_resource,
                                                    autosubscribe = autosubscribe)
        
        result = self.not_answer_received_client_ws_request()
        if not result:
            return
        
        self.ws_event_listener(client_ws)
        self.wait_for(5)
        self.stop_capturing_tcp_messages()
        return client_ws
    
    def not_answer_received_client_ws_request(self):
        client_ws_request = get_next_flask_server_websocket_request(self.flask_server)
        
        if client_ws_request is None:
            self._reporting.add_report_message_info("No client request received.")
            return False

        if '"subscribe"' in client_ws_request:
            self._reporting.add_report_message_info(f'Successfully received mocked websocket subscription:{client_ws_request}')

            #Drop acknowledgments
            self.stop_sending_tcp_messages(port=tester_server_port,flags='ACK,PSH ACK,PSH',port_direction='s')
            self._reporting.add_report_message_info("\n######### Disabling WebSocket ping acknowledgment #########")
            return True

    def ws_event_listener(self, ws):
        while not self.connection_closed:
            try:
                data = self.receive_next_ws_event(ws)
                if data:
                    self._reporting.add_report_message_info(f"Received data through socket: {data}")
                    event = data.get('event')
                    code = data.get('code')
                    if event == '/ViWiTestability/switchControls/' and code == 502:
                        self.connection_closed = True
                        self._reporting.add_report_message_info("Connection closed due to event 502")
                        ws.close()
            except Exception as e:
                self._reporting.add_report_message_system_error(f"Error receiving data: {e}")
                break
    
    def http_listner_callback(self):
        def http_listner_received_callback(msg: andisdk.MessageEthernet):  
            tcp_message : andisdk.MessageTCP = msg.get_tcp_layer()
            if (tcp_message != None and tcp_message.transport_header.port_destination == tester_server_port):
                    if tcp_message.tcp_header.flags == 0x18:
                        self._reporting.add_report_message_info('PSH/ACK message to server found!')
                        self.http_msg_queue.put(tcp_message)
                    elif tcp_message.tcp_header.flags & 0x01 or tcp_message.tcp_header.flags & 0x04:
                        self._reporting.add_report_message_info(f'FIN/RST message to server received:\n{tcp_message}')
                        self.tcp_connection_closed = True  

        return http_listner_received_callback            

    def check_ws_timings_parameters(self, ws_ping_pong_cycle_time_ws:int, ws_ping_pong_max_unanswered_ping:int):
        try:            
            result = False
            #Get first packet (GET WS Upgrade)
            current_packet = self.http_msg_queue.get(timeout=1)
            #Get second packet (first segment of the WS subscribe mocking)
            current_packet = self.http_msg_queue.get(timeout=1)
            #init timestamp
            ref_timestamp = 0
            delta_time = 0
            ws_ping_probes = 0
            check_probes = True
            
            for current_packet in self.http_msg_queue.queue:
                if current_packet != None:
                    if ref_timestamp == 0:
                        ref_timestamp = current_packet.timestamp
                    else:
                        ws_ping_probes += 1
                        delta_time = current_packet.timestamp - ref_timestamp
                        ref_timestamp = current_packet.timestamp
                        # check timeout to send the next WS PING
                        if delta_time < ws_ping_pong_cycle_time_ws*0.9 or delta_time > ws_ping_pong_cycle_time_ws*1.1:
                            self._reporting.add_report_message_warning(f"Wrong ws_ping_pong_cycle_time_ws between packets: expected {ws_ping_pong_cycle_time_ws}, actual {delta_time}")
                            check_probes = False
                            break
            # Chech probes number if no timing issue previously observed
            if check_probes:
                if ws_ping_probes != ws_ping_pong_max_unanswered_ping:
                    self._reporting.add_report_message_system_error(f"Wrong ws_ping_pong_max_unanswered_ping: expected {ws_ping_pong_max_unanswered_ping}, actual {ws_ping_probes}")
                else:
                    result = True
            
            if result:
                self._reporting.add_report_message_info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully checked websocket timings\n{"*" * 100}\n')

            else:
                self._reporting.add_report_message_system_error(f'\n{"*" * 100}\nFAILURE\nError checking websocket timings\n{"*" * 100}\n')
   
            return result            
        except Exception as e:
            self._reporting.add_report_message_system_error(f"Was not able to analyze WS timeing parameters: {e}")
            return False

    def check_websocket_closure(self):
        try:
            if self.connection_closed and self.tcp_connection_closed:
                self._reporting.add_report_message_info('Successfully checked websocket closed via error message')
                return True
            else:
                self._reporting.add_report_message_info(f'Error checking websocket closed via error message: WS status={self.connection_closed}, TCP status={self.tcp_connection_closed}')
            return self.connection_closed and self.tcp_connection_closed 
        except Exception as e:
            self._reporting.add_report_message_warning(f"Exception checking connection closure: {e}")

    def check_esotrace_action_error(self):
        try:
            self._reporting.add_report_message_info('checking actionError status')
            if self.actionError_received:
                self._reporting.add_report_message_info('Successfully checked actionError message in Esotrace')

            else:
                self._reporting.add_report_message_info('Failed checking actionError message in Esotrace')

            return self.actionError_received
        except Exception as e:
            self._reporting.add_report_message_system_error(f"Was not able to check conenction status:{e}")
 
    def subscription_timeout_tc_postcondition(self):
        stop_flask_server(self.flask_server)
        self.stop_esotrace_capture()
        self.esotrace_queue_evt.clear()
        self.clear_esotrace_queue()
        self.resume_sending_tcp_messages()
        self.delete_registered_service(location=self.registered_service_location)
        return self.viwi_test_postcondition()