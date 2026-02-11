import queue
import andisdk
import enna.core.reporting.interface

from hcp3.viwi.tests.constants import *
from hcp3.viwi.tests.flask_server import *
from hcp3.viwi.tests.websocket_server import *
from hcp3.viwi.tests.viwi_fixture import ViwiFixture

class SubscriptionHandlingFixture(ViwiFixture):
    def __init__(self, reporting: enna.core.reporting.interface.Interface,*args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self._reporting = reporting
        self.tcp_messages_queue_first_websocket = queue.Queue()
        self.tcp_messages_queue_second_websocket = queue.Queue()
        self.tcp_messages_queue_websocket_sim = queue.Queue()
        self.burst_client1_ws_events_timestamps = []
        self.burst_client2_ws_events_timestamps = []
        self.burst_sim_events_timestamps = []

    def subscription_handling_tc_precondition(self, partition:str,service_name:str):
        """ Prepare the preconditions for the subscription handling test case execution.

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

    def Trigger_events_update_burst(self):

        self.start_capturing_tcp_messages(self.burst_tcp_callback(self.client_ws_source_ports))

        self._reporting.add_report_message_info("Busrt sending started")
        
        burst_event_data_one = {
        "data":[{'id':'91c71fa6-6d18-46c9-af23-5433b7313609','name':'switchCtrlOne','uri':'/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609','restrictionReason':'one','switchValue':'one','switchValueConfiguration':['one','two','three']}],
        "type":"data",
        "event":f"/ViWiTestability/switchControls/#1",
        "Content-Type":"application/json; charset=utf-8"
        }
        burst_event_data_two = {
        "data":[{'id':'91c71fa6-6d18-46c9-af23-5433b7313609','name':'switchCtrlOne','uri':'/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609','restrictionReason':'one','switchValue':'two','switchValueConfiguration':['one','two','three']}],
        "type":"data",
        "event":f"/ViWiTestability/switchControls/#1",
        "Content-Type":"application/json; charset=utf-8"
        }
        burst_event_data = []
        for i in range(busrt_length):
        # Send the initial event to the client
            if i % 2 == 0:
                burst_event_data.append(burst_event_data_one)

            else:
                burst_event_data.append(burst_event_data_two)
                
        send_ws_server_response(self.flask_server, burst_event_data, inter_frames_time=0.1)
        self._reporting.add_report_message_info(f'Successfully simulated events burst')

        self.wait_for(1 + busrt_length * 0.2)
        self.stop_capturing_tcp_messages()

    def burst_tcp_callback(self,source_ports:list):
        def burst_received_callback(msg: andisdk.MessageEthernet):
            tcp_message: andisdk.MessageTCP = msg.get_tcp_layer()

            if tcp_message and tcp_message.tcp_header.flags == 0x18 and len(tcp_message.get_hex_bytes()) > ws_ping_payload_len:
                if tcp_message.transport_header.port_source == tester_debugging_port:
                    if tcp_message.transport_header.port_destination == source_ports[0]:
                        self.tcp_messages_queue_first_websocket.put(tcp_message)
                    elif tcp_message.transport_header.port_destination == source_ports[1]:
                        self.tcp_messages_queue_second_websocket.put(tcp_message)
                elif tcp_message.transport_header.port_source == tester_server_port:
                    self.tcp_messages_queue_websocket_sim.put(tcp_message)
                    return
        return burst_received_callback         

    def check_action_response_burst_on_esotrace(self, request_ids_list:list):
        try:
            self.hold_capturing_esotrace_messages()
            request1_events_count = 0
            request2_events_count = 0
            for msg in self.esotrace_actionresponse_queue.queue:
                if '"requestId"' in str(msg.value["message_data"]):
                    msg_data = str(msg.value["message_data"])
                    msg_split = msg_data.split(sep=",")
                    request_id = int(next((e.split(sep=":"))[1] for e in msg_split if 'requestId' in e))
                    if request_id == request_ids_list[0]:
                        request1_events_count += 1
                    elif request_id == request_ids_list[1]:
                        request2_events_count += 1
            if request1_events_count >= busrt_length and request2_events_count >= busrt_length:
                self._reporting.add_report_message_info(f'Successfully check burst events actionResponse on esotrace for RequestIds {request_ids_list[0]} and {request_ids_list[1]}\n{"*" * 100}\n')
                return True
            else:
                self._reporting.add_report_message_system_error(f"Received events for ReqId {request_ids_list[0]}: {request1_events_count} !!!" )
                self._reporting.add_report_message_system_error(f"Received events for ReqId {request_ids_list[1]}: {request2_events_count} !!!" )
                return False
            
        except Exception as e:
            self._reporting.add_report_message_system_error(f'Error checking actionResponse burst events in esotraces:{e}')
            return False
            
    def check_ws_events_timestamps(self):

        try:
            self._reporting.add_report_message_info(f"######## Burst events received, checking all events received and timestamps")
            result = False
            for current_packet in self.tcp_messages_queue_first_websocket.queue:
                if current_packet != None:
                    self.burst_client1_ws_events_timestamps.append(current_packet.timestamp)

            for current_packet in self.tcp_messages_queue_second_websocket.queue:
                if current_packet != None:
                    self.burst_client2_ws_events_timestamps.append(current_packet.timestamp)

            for current_packet in self.tcp_messages_queue_websocket_sim.queue:
                if current_packet != None:
                    self.burst_sim_events_timestamps.append(current_packet.timestamp)

            if len(self.burst_client1_ws_events_timestamps) >= busrt_length and \
                len(self.burst_client2_ws_events_timestamps) >= busrt_length and \
                len(self.burst_sim_events_timestamps) >= busrt_length:
                result = True

            return result           
        except Exception as e:
            self._reporting.add_report_message_system_error(f"Exception while getting events timestamps: {e}")
            return False
    
    def check_timestamps_difference(self):
        try:
            result = True
            for i in range(len(self.burst_sim_events_timestamps)):
                ws_timestamp = self.burst_client1_ws_events_timestamps[i]
                sim_timestamp = self.burst_sim_events_timestamps[i]
                diff_timestamp = ws_timestamp - sim_timestamp
                if diff_timestamp > 0.1:
                    result = False
                self._reporting.add_report_message_info(f"\nEvent Timestamps for subscribed client 1:\nforwarded timestamp:{ws_timestamp}\nsimulated timestamp:{sim_timestamp}\ndiff:{diff_timestamp}\n")
            
            for i in range(len(self.burst_sim_events_timestamps)):
                ws_timestamp = self.burst_client2_ws_events_timestamps[i]
                sim_timestamp = self.burst_sim_events_timestamps[i]
                diff_timestamp = ws_timestamp - sim_timestamp
                if diff_timestamp > 0.1:
                    result = False
                self._reporting.add_report_message_info(f"\nEvent Timestamps for subscribed client 2:\nforwarded timestamp:{ws_timestamp}\nsimulated timestamp:{sim_timestamp}\ndiff:{diff_timestamp}\n")

            if result:
                self._reporting.add_report_message_info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully checked timestamps tolerance for events burst\n{"*" * 100}\n')
            else:
                self._reporting.add_report_message_info(f'\n{"*" * 100}\nFAILURE\nError checking timestamps tolerance for events burst\n{"*" * 100}\n')
            
            return result
        except Exception as e:
            self._reporting.add_report_message_system_error(f"Was not able to check timestamps tolerance: {e}")

    def subscription_handling_tc_postcondition(self):
        """ Cleanup actions and reset the system to its postconditions after the subscription handling test case.
        
        :return: True if preconditions are successfully set, False otherwise
        :rtype: bool
        """
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