import socket
import threading
import time

import andisdk
import enna.core.reporting.server_junit

from hcp3.viwi.tests.viwi_fixture import ViwiFixture
from hcp3.viwi.tests.constants import*
from hcp3.viwi.tests.http_server import*

class RsiGatewayConfigFixture(ViwiFixture):
    def __init__(self, reporting: enna.core.reporting.server_junit,*args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
       
        self.consumed_services = []

    def send_root_get_and_check_server_tcp_timeout_connection(self, host:str, service:str, port:int, http_keep_alive_timeout_ms:int ):
        """Send a root GET request and check if the server TCP connection closes after the specified HTTP keep-alive timeout.

        :param str host: The host address.
        :param str service: The name of the service.
        :param int port: The port number.
        :param int http_keep_alive_timeout_ms: The timeout value for HTTP keep-alive in milliseconds.
        :return: True if the server TCP connection closes after the defined HTTP keep-alive timeout, False otherwise.
        :rtype: bool
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\n Send root GET/{service} request \n{"#" * 100}\n')
            # Create a TCP socket
            sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            sock.connect((host, port))
            request = f"GET /{service}/ HTTP/1.1\r\nHost:{host}:{port}\r\n\r\n".encode('utf-8')
            # request =  b"GET /{ViWiTestabilityClassTwo}/ HTTP/1.1\r\nHost:fd53:7cb8:383:3::130 :29796\r\n\r\n"
            sock.sendall(request)
            start_time=time.time()
            response = b""
            evt = threading.Event()
            while not evt.is_set():
                received_data = sock.recv(4096)
                if not received_data:
                    # Received FIN packet, close the connection
                    sock.close()
                    end_time=time.time()
                    evt.set()
                    break
                response += received_data

            ivi_tcp_connection_during_time = end_time - start_time
            response_status_code = int(response.decode('utf-8').split(' ')[1])
            self._reporting.add_report_message_info(response.decode('utf-8'))

            if response_status_code == 200:
                self._reporting.add_report_message_info(f'GET/{service} request is sent and properly answered with status code 200 response')
                ivi_tcp_connection_during_time_ms = ivi_tcp_connection_during_time * 1000
                if abs(ivi_tcp_connection_during_time_ms - http_keep_alive_timeout_ms) <= 0.1 * http_keep_alive_timeout_ms: # tolerance of 10% for http_keep_alive_timeout_ms value
                    self._reporting.add_report_message_pass('server TCP connection is closed after the defined http_keep_alive_timeout_ms value - Success')
                    return True
                else:
                    self._reporting.add_report_message_system_error('server TCP connection is closed after the defined http_keep_alive_timeout_ms value - Failed')
                    return False
            else:
                self._reporting.add_report_message_system_error(f'GET/{service} request received a non-200 status code: {response_status_code}')
                return False
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Error occured during sending GET/{service}: {error}')
            return False

    def check_rsi_gateway_config_conformity(self, partition:str ,vehicle_platform:str):
        """Check conformity between RSI Gateway configuration and vehicle platform configuration.

        :param str partition: The partition to be checked.
        :param str vehicle_platform: The vehicle platform name.
        :return: True if the conformity check is successful, False otherwise.
        :rtype: bool
        """

        if self.consumed_services == []:
            self.get_list_consumed_services_from_vehicle_config(partition, vehicle_platform)

        if self.consumed_services != []:
            for _con_service in self.consumed_services:
                self.check_service_parameter(partition = partition, con_service=_con_service, parameter_rsi="tcp_keep_alive_time", parameter_veh="keepalive_time")
                self.check_service_parameter(partition = partition, con_service=_con_service, parameter_rsi="tcp_keep_alive_intvl", parameter_veh="keepalive_intvl")
                self.check_service_parameter(partition = partition, con_service=_con_service, parameter_rsi="tcp_keep_alive_probes", parameter_veh="keepalive_probes")
                self.check_service_parameter(partition = partition, con_service=_con_service, parameter_rsi="tcp_user_timeout_ms", parameter_veh="tcp_user_timeout")
                self.check_service_parameter(partition = partition, con_service=_con_service, parameter_rsi="security_level", parameter_veh="security_level")
                self.check_service_parameter(partition = partition, con_service=_con_service, parameter_rsi="source_ip", parameter_veh="bind_addr")
                self.check_service_parameter(partition = partition, con_service=_con_service, parameter_rsi="pcp", parameter_veh="pcp")
            return True
        else:
            self._reporting.add_report_message_system_error('Getting consumed ViWi services from rsi gateway config - Failed')
        return False
    
    def get_list_consumed_services_from_vehicle_config(self, partition:str, vehicle_platform:str):
        """Get the list of consumed services from the vehicle configuration.

        :param str partition: The partition to be checked.
        :param str vehicle_platform: The vehicle platform name.
        """
        vehicle_platform_config = self.get_vehicle_platform_config(partition, vehicle_platform)
        # fetch the list of services
        if vehicle_platform_config["config"]["client"]:
            for service in vehicle_platform_config["config"]["client"]:
                self.consumed_services.append(service["service"])
      
    def check_service_parameter(self,partition:str, con_service:str, parameter_rsi:str, parameter_veh:str):
        """Compare parameters between RSI Gateway configuration and Vehicle Platform configuration.

        :param str partition: The partition to be checked.
        :param str con_service: The service name.
        :param str parameter_rsi: The parameter to be checked in RSI Gateway configuration.
        :param str parameter_veh: The parameter to be checked in Vehicle Platform configuration.
        """

        service_name = con_service.replace("/", "")
        self._reporting.add_report_message_info(f'\n{"#" * 100}\ncheck {parameter_rsi} in rsi gateway config on {partition} for {con_service}\n{"#" * 100}\n')
        rsi_parameter = self.get_service_parameter_rsi_gateway(partition, service_name, parameter_rsi)

        if rsi_parameter == None:
            self._reporting.add_report_message_system_error(f'was not able to get {parameter_rsi} from rsi gateway config on {partition} for {service_name}, Skipping check\n')
            return
        
        self._reporting.add_report_message_info(f'\n{"#" * 100}\n check {parameter_veh} in vehicle platform config for {partition} for {service_name}\n')
        veh_conf_parameter = self.get_service_parameter_vehicle_platform(partition, service_name, parameter_veh)

        self._reporting.add_report_message_info(f'\n{"#" * 100}\n Compare {parameter_rsi} of rsi gateway on {partition} and vehicle platform config for {service_name}\n{"#" * 100}\n')

        if rsi_parameter == veh_conf_parameter:
            self._reporting.add_report_message_info(f'Comparing {parameter_rsi} for rsi gateway config on {partition} and vehicle configuration for {service_name} - Success')

        else:
            self._reporting.add_report_message_system_error(f'Comparing {parameter_rsi} for rsi gateway config on {partition} and vehicle configuration for {service_name} - Failed')

    def get_service_parameter_rsi_gateway(self, partition:str, service:str, parameter:str):  
        """Get a parameter value for a service from the RSI Gateway configuration.

        :param str partition: The partition to be checked.
        :param str service: The service name.
        :param str parameter: The parameter to retrieve.
        :return: The value of the parameter if found, otherwise None.
        """ 
        self._reporting.add_report_message_info(f'get_rsi_gateway_ivi: {parameter} for {service}')
        param_value = None

        # Check if service specific parameter exist
        param_value = self.get_rsi_gateway_parameter_value(partition = partition , section = ["client_connections",f'{service}']  , parameter = parameter)
        if param_value is not None:
            self._reporting.add_report_message_info(f'{parameter} for {service} from rsi gateway config: {param_value}')
            return param_value
        else:
            # Check if service specific parameter exist within the client general option
            param_value = self.get_rsi_gateway_parameter_value(partition = partition , section = ["client_connections","*"] , parameter = parameter)
            if param_value is not None:
                self._reporting.add_report_message_info(f'{parameter} from rsi gateway config client general parameters: {param_value}')
                return param_value
        
        return param_value

    def get_service_parameter_vehicle_platform(self, partition:str, service:str, parameter:str):
        """Get a parameter value for a service from the vehicle configuration.

        :param str partition: The partition to be checked.
        :param str service: The service name.
        :param str parameter: The parameter to retrieve.
        :return: The value of the parameter if found, otherwise None.
        """
        self._reporting.add_report_message_info(f'get_vehicle_config: {parameter} for {service}')
        param_value = None
        bFound = False

        vehicle_config = self.get_vehicle_platform_config(partition = partition , vehicle_platform="")

        # Check if service exist
        for _service in vehicle_config["config"]["client"]:
            if _service["service"] == service:
                # Check if service specific parameter exist
                bFound = True
                if _service[parameter] != None:
                    param_value = _service[parameter]
                    self._reporting.add_report_message_info(f'{parameter} from vehicle config: {param_value}')
                else:
                    self._reporting.add_report_message_warning(f'Service {service} parameter {parameter} not defined in vehicle config')
        if not bFound:
            self._reporting.add_report_message_warning(f'Service {service} not defined in vehicle config')
        return param_value

    def check_parameter_conformity(self,partition:str, vehicle_platform:str, rsi_parameter:str, vehicle_parameter:str):
        """
        Check parameter conformance between rsi gateway and vehicle config
            * check rsi_parameter in rsi gateway config 
            * check vehicle_parameter in platform files
            * check that parameters values are equal
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\ncheck {rsi_parameter} in rsi gateway config on {partition}\n{"#" * 100}\n')
        rsi_parameter_value = self.get_rsi_gateway_parameter_value(partition, rsi_parameter)

        self._reporting.add_report_message_info(f'{rsi_parameter} from rsi gateway config is : {rsi_parameter_value}')
        
        self._reporting.add_report_message_info(f'\n{"#" * 100}\ncheck {vehicle_parameter} in vehicle platform config for {partition}\n{"#" * 100}\n')
        veh_conf = self.get_vehicle_platform_config(partition, vehicle_platform)
        vehicle_parameter_value = veh_conf[vehicle_parameter]

        self._reporting.add_report_message_info(f'{vehicle_parameter} from vehicle config is : {vehicle_parameter_value}')
        
        if rsi_parameter_value == vehicle_parameter_value:
            self._reporting.add_report_message_info(f'Comparing {rsi_parameter} for rsi gateway config on {partition} and {vehicle_parameter} from vehicle configuration - Success')
            return True
        else:
            self._reporting.add_report_message_system_error(f'Comparing {rsi_parameter} for rsi gateway config on {partition} and {vehicle_parameter} from vehicle configuration - Failed')
            return False

    def check_rsi_gateway_process_ids(self):
        """
        Check process ids for rsi gateway instances on ivi and sys
            * check process id of rsi gateway on ivi
            * check process id of rsi gateway on sys
            * check that process ids are different
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\ncheck process id of rsi gateway on ivi\n{"#" * 100}\n')
        rsi_ivi_processid = self.get_ivi_rsi_gateway_process_id()
        
        self._reporting.add_report_message_info(f'\n{"#" * 100}\ncheck process id of rsi gateway on sys\n{"#" * 100}\n')
        rsi_sys_processid = self.get_sys_rsi_gateway_process_id()

        self._reporting.add_report_message_info(f'\n{"#" * 100}\nCompare process id of rsi gateway on ivi and sys\n{"#" * 100}\n')
        
        if rsi_ivi_processid != -1 and rsi_sys_processid != -1 and rsi_ivi_processid != rsi_sys_processid:
            self._reporting.add_report_message_info('Comparing process ids for rsi gateway instances on ivi and sys - Success')
            return True
        else:
            self._reporting.add_report_message_ta_error('Comparing process ids for rsi gateway instances on ivi and sys - Failed')
        return False

    def get_ivi_rsi_gateway_process_id(self):
        """ Retrieve rsi_gateway_hcp3 process ID of IVI partition.

        :return: The Retrieved process ID, or -1 if an error occurs.
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nGet rsi_gateway_ivi_pid\n{"#" * 100}\n')
        try:
            cmd = 'adb connect 172.16.250.248:5555 && adb shell "pidof rsi_gateway_hcp3"'
            process_id_output = self.execute_command(cmd).strip().decode()
            process_id = process_id_output.split('\n')[-1]
            self._reporting.add_report_message_info(f'pid of ivi rsi_gateway: {process_id}')
            return process_id
        except Exception as e:
            self._reporting.add_report_message_system_error(f'Error getting ivi rsi_gateway_process_id: {e}')
            return -1

    def get_sys_rsi_gateway_process_id(self):
        """ Retrieve rsi_gateway_hcp3 process ID of SYS partition.

        :return: The Retrieved process ID, or -1 if an error occurs.
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nGet rsi_gateway_sys_pid\n{"#" * 100}\n')
        try:
            cmd = 'ssh -p 2222 root@172.16.250.248 "pidof rsi_gateway_hcp3"'
            process_id_output = self.execute_command(cmd).strip().decode()
            process_id = process_id_output.split('\n')[-1]
            self._reporting.add_report_message_info(f'pid of sys rsi_gateway: {process_id}')
            return process_id
        except Exception as e:
            self._reporting.add_report_message_system_error(f'Error getting sys rsi_gateway_process_id: {e}')
            return -1
    
    def check_rsi_gateway_config_files(self):
        """
        Check config files for rsi gateway instances on ivi and sys
            * check md5sum of rsi gateway config file on ivi
            * check md5sum of rsi gateway config file on sys
            * check that md5sum are different for both configs
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nCheck md5sum of rsi gateway config on ivi\n{"#" * 100}\n')
        rsi_ivi_md5sum = self.get_ivi_rsi_gateway_md5sum()
        
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nCheck md5sum of rsi gateway config on sys\n{"#" * 100}\n')
        rsi_sys_md5sum = self.get_sys_rsi_gateway_md5sum()

        self._reporting.add_report_message_info(f'\n{"#" * 100}\nComparing md5sum of rsi gateway configs on ivi and sys\n{"#" * 100}\n')
        if rsi_ivi_md5sum != -1 and rsi_sys_md5sum != -1 and rsi_ivi_md5sum != rsi_sys_md5sum:
            self._reporting.add_report_message_info('Comparing md5sums for rsi gateway instances configs on ivi and sys - Success')
            return True
        else:
            self._reporting.add_report_message_ta_error('Comparing md5sums for rsi gateway instances configs on ivi and sys - Failed')
        return False
         
    def get_ivi_rsi_gateway_md5sum(self):
        """
        Check the MD5 checksum of the IVI RSI gateway configuration file.

        :return: The MD5 checksum of the IVI RSI gateway configuration file, or -1 if an error occurs.
        :rtype: str
        """
        self._reporting.add_report_message_info('Get ivi rsi_gateway_config_md5sum')
        try:
            cmd = 'adb connect 172.16.250.248:5555 && adb shell "md5sum -b /vendor/eso/config/rsi_gateway-userdebug.json"'
            cmd_stdout = self.execute_command(cmd).strip()
            md5_checksum = cmd_stdout.split(b"\n")[-1].split(b' ')[0]
            self._reporting.add_report_message_info(f'md5sum of ivi rsi_gateway config: {md5_checksum}')
            return md5_checksum
        except Exception as e:
            self._reporting.add_report_message_system_error(f'Error getting ivi rsi_gateway_config_md5sum: {e}')
            return -1
    
    def get_sys_rsi_gateway_md5sum(self):
        """
        Check the MD5 checksum of the SYS RSI gateway configuration file.

        :return: The MD5 checksum of the SYS RSI gateway configuration file, or -1 if an error occurs.
        :rtype: str
        """
        self._reporting.add_report_message_info('Get sys rsi_gateway_config_md5sum')
        try:
            cmd = 'ssh -p 2222 root@172.16.250.248 "md5sum -b /etc/eso/rsi_gateway.json"'
            cmd_stdout = self.execute_command(cmd).strip()
            md5_checksum = cmd_stdout.split(b"\n")[-1].split(b' ')[0]
            self._reporting.add_report_message_info(f'md5sum of sys rsi_gateway config: {md5_checksum}')
            return md5_checksum
        except Exception as e:
            self._reporting.add_report_message_system_error(f'Error getting sys rsi_gateway_config_md5sum: {e}')
            return -1

    def check_client_tcp_socket_parameters(self,partition:str, service_name:str, capturing_time:int, keepalive_time:int, keepalive_intvl:int, keepalive_probes:int): 
        """ Check TCP socket parameters for DUT as client.

        :param partition: The partition name.
        :param service_name: The name of the service.
        :param capturing_time: The time for capturing TCP messages.
        :param keepalive_time: The TCP keepalive time.
        :param keepalive_intvl: The TCP keepalive interval.
        :param keepalive_probes: The TCP keepalive probes.
        :return: True if the check is successful, otherwise False.
        rtype: bool
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
            
            self.start_capturing_tcp_messages(self.tcp_keepalive_callback(tester_server_port))
            
            mocking_thread = self.mock_service(service = service_name,
                                                host = host,
                                                    port = tester_debugging_port )
            client_port, client_request = get_next_http_server_request(self.server, timeout=5)

            self._reporting.add_report_message_info(f'client HTTP request is : {client_port , client_request}')
            
            if f'GET /{service_name}' in client_request:
                self.stop_sending_tcp_messages(port = tester_server_port, flags = 'ACK,PSH ACK',port_direction='s')
           
                mocking_thread.join()
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
        """ Simulates a ViWi HTTP server for the specified service.

        :param service: The name of the service to simulate.
        :return: The created HTTP server instance or None if an error occurs.
        rtype: HttpServer | None
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

    def tcp_keepalive_callback(self, port:int):
        """ Create a callback function to handle and filter TCP keepalive messages.
        
        :param port: The TCP port to filter messages by.
        :return: A callback function that processes incoming TCP messages.
        """
        def tcp_keepalive_received_callback(msg: andisdk.MessageEthernet):
            tcp_message: andisdk.MessageTCP = msg.get_tcp_layer()

            if tcp_message and \
            (tcp_message.transport_header.port_source == port or
                    tcp_message.transport_header.port_destination == port) and \
                    tcp_message.tcp_header.flags == 0x10:
                self.tcp_messages_queue.put(tcp_message)
        return tcp_keepalive_received_callback