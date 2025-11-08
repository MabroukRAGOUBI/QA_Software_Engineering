import andisdk
import enna.core.reporting.server_junit
import enna.core.reporting.interface
from hcp3.viwi.tests.viwi_fixture import ViwiFixture
from hcp3.viwi.tests.constants import*
from hcp3.viwi.tests.http_server import*


class ConnectionHandlingTcpFixture(ViwiFixture):
    def __init__(self, reporting: enna.core.reporting.interface.Interface,*args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self._reporting = reporting
        self.server : HttpServer
    
    def check_client_tcp_socket_parameters(self,partition:str, service_name:str, capturing_time:int, keepalive_time:int, keepalive_intvl:int, keepalive_probes:int):    
        """Check client TCP socket parameters by capturing and analyzing TCP keepAlive messages.

        :param str partition: The partition to be used.
        :param str service_name: The name of the service.
        :param int capturing_time: The time, in seconds, to capture TCP messages.
        :param int keepalive_time: The expected time, in seconds, between the last TCP packet and the first TCP keepAlive packet.
        :param int keepalive_intvl: The expected time, in seconds, between two successive TCP keepAlive packets.
        :param int keepalive_probes: The expected maximum number of TCP keepAlive packets that should be sent before closing the client socket connection.
        :return: True if the parameters are successfully checked, False otherwise.
        :rtype: bool
        """
        try:
            self.server = self.simulate_viwi_http_server(service_name)
            self.disable_partition_firewall(partition)
            
            if partition == self.ivi_partition_name:
                host = self.ivi_ip
            else:
                host = self.sys_ip
            result  = self.register_service(service = service_name,
                                                server_ip = tester_server_ip,
                                                    server_port = tester_server_port,
                                                        host = host,
                                                            port = tester_debugging_port)
            if not result:
                self._reporting.add_report_message_system_error(f'Failed to register and mock the service: {service_name}')
                return False
            
            self.start_capturing_tcp_messages(self.tcp_keepalive_message_callback(tester_server_port))
            
            mocking_thread = self.mock_service(service = service_name,
                                                host = host,
                                                    port = tester_debugging_port)
            client_port, client_request = get_next_http_server_request(self.server, timeout=5)

            self._reporting.add_report_message_info(f'client HTTP request is : {client_port , client_request}')
            
            if f'GET /{service_name}' in client_request:
                self.stop_sending_tcp_messages(port = tester_server_port, flags = 'ACK,PSH ACK',port_direction='s')
           
                mocking_thread.join(timeout=5)
                self.wait_for(capturing_time)

                self.stop_capturing_tcp_messages()
                self.resume_sending_tcp_messages()
                
                result = self.check_tcp_keep_alive_parameters(keepalive_time = keepalive_time,
                                                                keepalive_intvl = keepalive_intvl,
                                                                    keepalive_probes = keepalive_probes,
                                                                        port = client_port)
                stop_http_server(self.server)
                self.delete_registered_service(self.registered_service_location)
                return result
            else:
                return False
        except Exception as error:
            self._reporting.add_report_message_ta_error(f"error has occured: {error}")

    def simulate_viwi_http_server(self, service: str):
        """Simulate a VIWI HTTP server.

        :param str service: The name of the service.
        :return: The created HTTP server object.
        :rtype: HTTPServer
        """
        try:
            http_server = create_http_server(server_ip=tester_server_ip,
                                                server_port=tester_server_port,
                                                    service=service,
                                                        handler=HttpServerHDLR,
                                                            reporting=self._reporting)
            start_http_server(http_server)
            return http_server
        except Exception as error:
            self._reporting.add_report_message_ta_error(f'Failed to simulate http server: {error}') 
            return None

    def tcp_keepalive_message_callback(self, port:int):
        def tcp_keepalive_received_callback(msg: andisdk.MessageEthernet):
            tcp_message: andisdk.MessageTCP = msg.get_tcp_layer()

            if tcp_message and \
            (tcp_message.transport_header.port_source == port or
             tcp_message.transport_header.port_destination == port ) and \
                    tcp_message.tcp_header.flags == 0x10:
                self.tcp_messages_queue.put(tcp_message)
        return tcp_keepalive_received_callback

    def client_http_request_contain_keepalive_header(self, partition:str,service_name:str):
        """Check if the client HTTP request contains the 'Connection: keep-alive' header.

        :param str partition: The partition to be used.
        :param str service_name: The name of the service.
        :return: True if the client HTTP request contains the 'Connection: keep-alive' header, False otherwise.
        :rtype: bool
        """
        
        self.server = self.simulate_viwi_http_server(service_name)
        self.disable_partition_firewall(partition)
        
        if partition == self.ivi_partition_name:
            host = self.ivi_ip
        else:
            host = self.sys_ip
        
        result  = self.register_service(service = service_name,
                                                    server_ip = tester_server_ip,
                                                        server_port = tester_server_port,
                                                            host = host,
                                                                port = tester_debugging_port)
        mocking_thread = self.mock_service(service = service_name,
                                                host = host,
                                                    port = tester_debugging_port)
        mocking_thread.join()
        
        if not result:
            self._reporting.add_report_message_system_error(f'Failed to register and mock the service: {service_name}')
            return False
        
        client_request = get_next_http_server_request(self.server , timeout=5)[1]
        self._reporting.add_report_message_info(f'client request is : {client_request}')
        
        stop_http_server(self.server)
        
        return "Connection: keep-alive" in client_request

