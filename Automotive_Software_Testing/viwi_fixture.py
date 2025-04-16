
import datetime
import inspect
import json
import os
import queue
import re
import socket
import threading
import requests
from websocket import create_connection
import subprocess
import time
from urllib.parse import urlparse
import websocket
from andisdk import message_builder, andi
import andisdk
from hcp3.simulations.main import Simulation
from hcp3.viwi.tests.flask_server import *

from hcp3.viwi.tests.constants import *
from hcp3.viwi.tests.websocket_server import *

import enna
import enna.core.config
import enna.core.reporting.interface
import enna.core.interfaces.testing
import enna.core.time
import enna.core.deployment.debug
import enna.data_interfaces.serial.interface
from enna.data_interfaces.esotrace.server_socket import Server
from technica_powersupply.driver import driver_dict, manson
from typing import Callable

# from flask_server import FlaskServer
from hcp3.viwi.fixtures import ivi_rsi_gw_configs, sys_rsi_gw_configs

# from http_server import HttpServer
# from websocket_server import WebsocketServer


class ViwiFixture(enna.core.interfaces.testing.Stimulation):
    def __init__(
                self,reporting: enna.core.reporting.interface.Interface,

    ):
        """Initialize the test.

        :param str adapter: the adapter used to send and receive ethernet packets from the ECU
        :param str partition: ECU partition
        """
    
        enna.core.interfaces.testing.Stimulation.__init__(self, reporting)
        self._reporting = reporting
        self.ivi_rsi_gw_path= '/vendor/eso/config/rsi_gateway-userdebug.json'
        self.sys_rsi_gw_path = '/etc/eso/rsi_gateway.json'
        self.flask_server : FlaskServer
        self.viwi_ws_server : WebsocketServer
        self.can_messages_queue = queue.Queue()
        self.ivi_sd_offers_queue = queue.Queue()
        self.sys_sd_offers_queue = queue.Queue()
        self.ivi_sd_offer_list = []
        self.sys_sd_offer_list = []
        self.ivi_ip: str='fd53:7cb8:383:3::130'
        self.sys_ip: str='fd53:7cb8:383:e::108'
        self.ivi_partition_name:str = "ivi"
        self.sys_partition_name:str = "sys"
        self.rsi_gateway_config:str = ""
        self.modified_rsi_gateway_config:str = ""
        self.backup_rsi_gateway_config_file:str = ""
        self.vehicle_config:str = ""
        self.tcp_messages_queue = queue.Queue()
        self.esotrace_queue = queue.Queue()
        self.esotrace_queue_evt = threading.Event()
        self.registered_service_location : str
        self.generate_pcap_traces = False
        self.activate_simulation = False
        self.esotrace_actionresponse_queue = queue.Queue()
        self.esotrace_actionrequest_queue = queue.Queue()
        self.esotrace_actionerror_queue = queue.Queue()
        self.client_ws_source_ports  = []
        self.client_ws_list  = []
        self.request_ids_list = []
        self.request_ids_backup_list = []
        self.service_registred : bool = False
        self.service_logs_active : bool = False
        # Auto Detect hardware adapters
        andi.detect_hardware()
        self.init_powersupply()
    
    def init_powersupply(self):

        # if not self.power_supply:
        self.power_supply: manson.HCS = driver_dict['MANSON_HCS']()

        self.power_supply.init(os.environ.get('POWERSUPPLY_COM_PORT', '/dev/ttyUSB0'), (9600,))
    
    def viwi_test_precondition(self):
        """ Set up all preconditions needed before starting the testcases execution.

        :return: result of precondition
        :rtype: bool
        """
        try:
            report_base_path =  os.path.dirname(self._reporting.report_path.value)
            report_path = os.path.join(report_base_path, os.path.basename(inspect.getfile(self.__class__))[:-3])
            os.makedirs(report_path, exist_ok=True)
            test_case_name = os.path.splitext(os.path.basename(inspect.getfile(self.__class__)))[0]
            if self.generate_pcap_traces :
                pcap_file = os.path.join(report_path, f'{test_case_name}.pcapng')
                self._reporting.add_report_message_info(f'recording to {pcap_file}')
                debug_channel = andisdk.andi.create_channel(os.environ.get('stimulation_adapter', 'enp12s0'))
                self.debug_channel = andisdk.ChannelEthernet(debug_channel)
                self.debug_channel.start_record(pcap_file)
            if self.activate_simulation:
                try:
                    self.keepalive_sim= Simulation()
                    self.keepalive_sim.start()  
                    self.wait_for(5)
                except Exception as e:
                    self._reporting.add_report_message_ta_error(f'Precondition finished - Failed: {error}')
                    return False

            self._reporting.add_report_message_info("Precondition finished - Successful ")    
            return True
        except Exception as error:
            self._reporting.add_report_message_ta_error(f'Precondition finished - Failed: {error}')
            return False

        finally:
            self._reporting.start_testcase(test_case_name)
    
    def viwi_test_postcondition(self):
        try:
                if self.generate_pcap_traces:
                    self.debug_channel.stop_record()
                if self.activate_simulation:
                    self.keepalive_sim.stop()   
                return True
        except Exception as e:
            self._reporting.add_test_result_ta_error(f'was not able to teardown:{e}')
            return False
        finally:
            self._reporting.end_testcase()
 
    def execute_command(self, command: str, cwd=None):
        """ Execute a given SSH command.

        :param str command: The command to execute.
        :param str cwd: The directory from which the command should be executed.
        :return: The output of the command.
        :rtype: bytes or None
        """
        try:
            self._reporting.add_report_message_info(f'Start executing command: {command}')
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
            out, err = process.communicate()
            if err:
                raise Exception(err.decode())
            self._reporting.add_report_message_info(f'Command execution Result: {out}')
            return out
        except Exception as e:
            self._reporting.add_report_message_system_error(f'Error executing command: {e}')
            return None
        finally:
            # Terminate the subprocess
            if 'process' in locals():
                process.terminate()
          
    def power_off_dut(self):
        """ Power off the Device Under Test (DUT).

        :return: True if the DUT was successfully powered off, False otherwise.
        :rtype: bool
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nPower off DUT\n{"#" * 100}\n')
        res = self.power_supply.output_on()
        if res.strip() == "OK":
            self._reporting.add_report_message_info(f'Power off DUT - Successful')
            return True
        else: 
            self._reporting.add_report_message_ta_error(f'Power off DUT - Error')
            return False

    def power_on_dut(self):
        """ Power on the Device Under Test (DUT).
        This function turns on the power supply to the DUT and waits for a specified duration before reporting the success of the operation.
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nPower on DUT\n{"#" * 100}\n')
        self.power_supply.output_off()
        self._reporting.add_report_message_info(f'Power off DUT - Successful')

    def backup_ivi_rsi_gateway_config(self):
        """Backup the IVI RSI gateway configuration file.

        This method backs up the IVI RSI gateway configuration file, copies the file to the execution report,
        and logs the success or failure of the operation.

        :return: True if the backup was successful, False otherwise.
        :rtype: bool
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nBackup ivi_rsi_gateway_config file\n{"#" * 100}\n')
            self.backup_rsi_gateway_config_file = self.download_ivi_rsi_gateway_config()
            self.copy_file_to_execution_report(self.backup_rsi_gateway_config_file,'rsi_gateway-userdebug.json')
            self._reporting.add_report_message_info(f'Backup ivi_rsi_gateway_config File - Success')
            return True
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Backup ivi_rsi_gateway_config File - Failed: {error}')
            return False
    
    def backup_sys_rsi_gateway_config(self):
        """Backup the SYS RSI gateway configuration file.

        This method backs up the IVI RSI gateway configuration file, copies the file to the execution report,
        and logs the success or failure of the operation.

        :return: True if the backup was successful, False otherwise.
        :rtype: bool
        """
        try:    
            self.backup_rsi_gateway_config_file = self.download_sys_rsi_gateway_config()
            # Copy file to report path
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nCopy Backup sys_rsi_gateway_config File to report path\n{"#" * 100}\n')
            self.copy_file_to_execution_report(self.backup_rsi_gateway_config_file,'rsi_gateway.json')
            self._reporting.add_report_message_info('Backup sys_rsi_gateway_config File - Successful')
            return True
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Backup sys_rsi_gateway_config File - Failed: {error}')
            return False   

    def backup_rsi_gateway_config(self, partition:str):
        """ Create a backup file for RSI Gatway.json configuration from the specified partition of the DUT.

        :param str partition: The partition from which the backup should be created.
        :return: True if the RSI Gatway.json configuration backedup successfully, False otherwise.
        :rtype: bool
        """
        try:
            if partition == self.ivi_partition_name:
                return self.backup_ivi_rsi_gateway_config()

            if partition == self.sys_partition_name:
                return self.backup_sys_rsi_gateway_config()
            else:
                self._reporting.add_report_message_ta_error(f'Backup rsi_gateway_config File - Failed: {partition}')

        except Exception as error:
            self._reporting.add_report_message_ta_error(f'Backup rsi_gateway_config File - Failed: {error}')
            return False
    
    def download_ivi_rsi_gateway_config(self):
        """Download the IVI RSI gateway configuration file.

        :return: The file path of the downloaded IVI RSI gateway configuration file.
        :rtype: str
        """
        file_path = os.path.join(os.path.abspath(os.path.dirname(ivi_rsi_gw_configs.__file__)), f'rsi_gw_config_IVI_'+ datetime.datetime.now().strftime('%m_%d_%Y_%H_%M_%S') + '.json')   
        adb_command = f"adb connect 172.16.250.248:5555 && adb root && adb pull {self.ivi_rsi_gw_path} {file_path}"
        self.execute_command(adb_command)
        self._reporting.add_report_message_info("Download IVI RSI Gateway Config - Success")
        return file_path
    
    def download_sys_rsi_gateway_config(self):
        """Download the SYS RSI gateway configuration file.
        
        :return: The file path of the downloaded SYS RSI gateway configuration file.
        :rtype: str
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nDownload sys_rsi_gateway_config file\n{"#" * 100}\n')
        file_path = os.path.join(os.path.abspath(os.path.dirname(sys_rsi_gw_configs.__file__)), f'rsi_gw_config_SYS_'+ datetime.datetime.now().strftime('%m_%d_%Y_%H_%M_%S') + '.json')   
        ssh_command = f"scp -P 2222 root@172.16.250.248:{self.sys_rsi_gw_path} {file_path}"
        self.execute_command(ssh_command)
        return file_path
                
    def remove_comments_from_json_file(self ,file_path:str):
        """Remove comments from a JSON file.

        :param str file_path: The path to the JSON file.
        :return: The JSON data with comments removed.
        :rtype: dict
        """
        with open(file_path) as jsonfile:
            #Remove comments lines as they are not supported by JSON
            json_data = ''.join(line for line in jsonfile if not '#' in line)
            return json.loads(json_data)

    def copy_file_to_execution_report(self, file_path , file_name:str):
        """Copy a file to the execution report directory.

        :param str file_path: The path of the file to be copied.
        :param str file_name: The name of the file to be copied.
        :return: None
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nCopy file {file_name} to execution report\n{"#" * 100}\n')
            # copy rsi config to report path
            report_base_path =  os.path.dirname(self._reporting.report_path.value)
            report_path = os.path.join(report_base_path, os.path.basename(inspect.getfile(self.__class__))[:-3])
            destination_path = os.path.join(report_path, os.path.basename(file_name))
            self.adb_command = f"cp -f {file_path} {destination_path}"
            self.execute_command(self.adb_command)
            self._reporting.add_report_message_pass(f"Copy file to execution report - Success")
        
        except Exception as error:
            self._reporting.add_report_message_system_error(f"Copy file to execution report - Failed: {error}")
    
    def get_ivi_rsi_gateway_parameter_value(self, section: list, parameter: str):
        """Retrieve the value of a specific parameter from the IVI RSI gateway configuration.

        :param list section: The section of the configuration to search in, represented as a list of keys.
        :param str parameter: The name of the parameter whose value is to be retrieved.
        :return: The value of the specified parameter, or None if the parameter is not found.
        :rtype: any or None
        """
        if self.rsi_gateway_config == "":
            self.rsi_gateway_config = self.download_ivi_rsi_gateway_config()
            self.copy_file_to_execution_report(self.rsi_gateway_config, 'rsi_gateway-userdebug.json')
        
        rsi_gateway_config = self.remove_comments_from_json_file(self.rsi_gateway_config)

        if section:
            current_section = rsi_gateway_config
            try:
                for key in section:
                    current_section = current_section[key]
            except (KeyError, TypeError):
                return None

            if parameter in current_section:
                return current_section[parameter]
        else:
            if parameter in rsi_gateway_config:
                return rsi_gateway_config[parameter]
        return None
     
    def get_sys_rsi_gateway_parameter_value(self, section:list , parameter:str):
        """Retrieve the value of a specific parameter from the SYS RSI gateway configuration.

        :param list section: The section of the configuration to search in, represented as a list of keys.
        :param str parameter: The name of the parameter whose value is to be retrieved.
        :return: The value of the specified parameter, or None if the parameter is not found.
        :rtype: any or None
        """
        if self.rsi_gateway_config == "":
            self.rsi_gateway_config = self.download_sys_rsi_gateway_config()
            self.copy_file_to_execution_report(self.rsi_gateway_config, 'rsi_gateway.json')
            
        rsi_gateway_config = self.remove_comments_from_json_file(self.rsi_gateway_config)

        if section:
            current_section = rsi_gateway_config
            try:
                for key in section:
                    current_section = current_section[key]
            except (KeyError, TypeError):
                return None

            if parameter in current_section:
                return current_section[parameter]
        else:
            if parameter in rsi_gateway_config:
                return rsi_gateway_config[parameter]
        return None
    
    def get_rsi_gateway_parameter_value(self, partition:str, parameter, section=[]):
        """Retrieve the value of a specific parameter from the RSI gateway configuration based on the partition.

        :param str partition: The partition name, either IVI or SYS.
        :param parameter: The name of the parameter whose value is to be retrieved.
        :param list section: The section of the configuration to search in, represented as a list of keys (optional).
        :return: The value of the specified parameter, or None if the parameter is not found.
        :rtype: any or None
        """
        if partition == self.ivi_partition_name:
            return self.get_ivi_rsi_gateway_parameter_value(section, parameter)
            
        if partition == self.sys_partition_name:
            return self.get_sys_rsi_gateway_parameter_value(section, parameter)

    def get_vehicle_platform_config(self, partition:str ,vehicle_platform:str):
        """Retrieve the vehicle platform configuration based on the partition.

        :param str partition: The partition name, either IVI or SYS.
        :param str vehicle_platform: The name of the vehicle platform.
        :return: The vehicle platform configuration.
        :rtype: dict or None
        """
        if partition == self.ivi_partition_name:
            return self.get_ivi_vehicle_platform_config(vehicle_platform)
        elif partition == self.sys_partition_name:
            return self.get_sys_vehicle_platform_config(vehicle_platform) 

    def get_ivi_vehicle_platform_config(self,vehicle_platform:str):
        """Retrieve the IVI vehicle platform configuration.

        :param str vehicle_platform: The name of the vehicle platform.
        :return: The vehicle platform configuration.
        :rtype: dict
        """
        if self.vehicle_config == "":
            oneinfo_main_path = os.path.join(os.path.abspath(os.path.join(os.path.abspath(".env"), os.pardir)), 'oneinfotainment.main-project')
            self.vehicle_config = os.path.join(oneinfo_main_path, f"Platforms/{vehicle_platform}/network_config/network_config_ivi_viwi.json")
            # Copy file to report path
            self.copy_file_to_execution_report(self.vehicle_config,'network_config_ivi_viwi.json')
        with open(self.vehicle_config) as jsonfile:
            vehicle_config = json.load(jsonfile)
            
        return vehicle_config
    
    def get_sys_vehicle_platform_config(self,vehicle_platform:str):
        """Retrieve the SYS vehicle platform configuration.

        :param str vehicle_platform: The name of the vehicle platform.
        :return: The vehicle platform configuration.
        :rtype: dict
        """
        if self.vehicle_config == "":
            oneinfo_main_path = os.path.join(os.path.abspath(os.path.join(os.path.abspath(".env"), os.pardir)), 'oneinfotainment.main-project')
            self.vehicle_config = os.path.join(oneinfo_main_path, f"Platforms/{vehicle_platform}/network_config/network_config_sys_viwi.json")
            # Copy file to report path
        self.copy_file_to_execution_report(self.vehicle_config,'network_config_sys_viwi.json')
        with open(self.vehicle_config) as jsonfile:
            vehicle_config = json.load(jsonfile)
            
        return vehicle_config

    def modify_rsi_gateway_config(self, partition:str, parameter:str, value, section=[]):
        """Modify a specific parameter in the RSI gateway configuration based on the partition.

        :param str partition: The partition name, either IVI or SYS.
        :param list section: The section of the configuration to modify, represented as a list of keys.
        :param str parameter: The name of the parameter to be modified.
        :param value: The new value for the parameter.
        :return: True if the modification was successful, False otherwise.
        :rtype: bool
        """
        if partition == self.ivi_partition_name:
            return self.modify_ivi_rsi_gateway_config(section, parameter,value)
            
        if partition == self.sys_partition_name:
            return self.modify_sys_rsi_gateway_config(section, parameter, value)

    def modify_ivi_rsi_gateway_config(self,section, parameter, value):
        """Modify a specific parameter in the IVI RSI gateway configuration.

        :param list section: The section of the configuration to modify, represented as a list of keys.
        :param str parameter: The name of the parameter to be modified.
        :param value: The new value for the parameter.
        :return: True if the modification was successful, False otherwise.
        :rtype: bool
        """
        if self.backup_rsi_gateway_config_file == "":
            self.backup_ivi_rsi_gateway_config()

        if self.modified_rsi_gateway_config == "":
                self.modified_rsi_gateway_config = self.download_ivi_rsi_gateway_config()
        
        rsi_gateway_config = self.remove_comments_from_json_file(self.modified_rsi_gateway_config )

        if section:
            current_section = rsi_gateway_config
            try:
                for key in section:
                    current_section = current_section.setdefault(key, {})
                    # current_section = current_section[key]
                current_section[parameter] = value    
            except (KeyError, TypeError):
                self._reporting.add_report_message_ta_error(f'Access to {parameter} in {section} in ivi rsi config- Failed ')
                return False
             
        else:
            rsi_gateway_config[parameter] = value
        # Save changes 
        with open(self.modified_rsi_gateway_config, 'w') as jsonfile:
            json.dump(rsi_gateway_config, jsonfile, indent=2)     
        self._reporting.add_report_message_info(f'change {parameter} value to {value} in ivi rsi config- Success ') 
        return True

    def modify_sys_rsi_gateway_config(self,section, parameter, value):  
        """Modify a specific parameter in the SYS RSI gateway configuration.

        :param list section: The section of the configuration to modify, represented as a list of keys.
        :param str parameter: The name of the parameter to be modified.
        :param value: The new value for the parameter.
        :return: True if the modification was successful, False otherwise.
        :rtype: bool
        """
        if self.backup_rsi_gateway_config_file == "":
            self.backup_sys_rsi_gateway_config()
        
        if self.modified_rsi_gateway_config == "":
            self.modified_rsi_gateway_config = self.download_sys_rsi_gateway_config()
        
        rsi_gateway_config = self.remove_comments_from_json_file(self.modified_rsi_gateway_config)

        if section:
            current_section = rsi_gateway_config
            try:
                for key in section:
                    current_section = current_section.setdefault(key, {})
                    # current_section = current_section[key]
                current_section[parameter] = value    
            except (KeyError, TypeError):
                self._reporting.add_report_message_ta_error(f'Access to {parameter} in {section} in ivi rsi config- Failed ')
                return False 
        else:
            rsi_gateway_config[parameter] = value
        # Save changes 
        with open(self.modified_rsi_gateway_config, 'w') as jsonfile:
            json.dump(rsi_gateway_config, jsonfile, indent=2)     
        self._reporting.add_report_message_info(f'change {parameter} value to {value} in ivi rsi config- Success ') 
        return True

    def change_server_tcp_keepAlive_parameters(self, tcp_keep_alive_time: int ,tcp_keep_alive_intvl : int, tcp_keep_alive_probes : int , service_name:str = ""):
        """Change the values of "tcp_keep_alive_time", "tcp_keep_alive_intvl", and "tcp_keep_alive_probes" for one given service name within server tcp parameters defined in IVI RSI Gateway 
           within "server_general_options".

        :param int tcp_keep_alive_time: the time, in second between the last tcp data packet sent and the first tcp keepalive packet.
        :param int tcp_keep_alive_intvl: The time, in seconds, between two tcp keepalive packets.
        :param int tcp_keep_alive_probes: The maximum number of tcp keepalive packets should be sent before closing server socket connection.
        :param str service_name : the service name to be configured within the given tcp keepAlive parameters.
        :return: True if the values were successfully changed, False otherwise.
        :rtype: bool
        """
        self.modified_rsi_gateway_config = os.path.join(os.path.abspath(os.path.dirname(ivi_rsi_gw_configs.__file__)), f'rsi_gw_config_IVI_changes'+ datetime.datetime.now().strftime('%m_%d_%Y_%H_%M_%S') + '.json')   
        self.adb_command = f"adb connect 172.16.250.248:5555 && adb root && adb pull {self.ivi_rsi_gw_path} {self.modified_rsi_gateway_config}"
        self.execute_command(self.adb_command)

        if service_name == "":
            return self.change_general_server_tcp_keepAlive_parameters(tcp_keep_alive_time, tcp_keep_alive_intvl, tcp_keep_alive_probes)
           
        else:
            return self.change_server_service_tcp_keepAlive_parameters(tcp_keep_alive_time, tcp_keep_alive_intvl, tcp_keep_alive_probes, service_name)

    def change_general_server_tcp_keepAlive_parameters(self, tcp_keep_alive_time:int, tcp_keep_alive_intvl:int, tcp_keep_alive_probes:int):
        """Change the values of "tcp_keep_alive_time", "tcp_keep_alive_intvl", and "tcp_keep_alive_probes" for a given service name within server TCP parameters defined in IVI RSI Gateway.

        :param int tcp_keep_alive_time: The time, in seconds, between the last TCP data packet sent and the first TCP keepalive packet.
        :param int tcp_keep_alive_intvl: The time, in seconds, between two TCP keepalive packets.
        :param int tcp_keep_alive_probes: The maximum number of TCP keepalive packets that should be sent before closing the server socket connection.
        :param str service_name: The service name to be configured with the given TCP keepalive parameters (optional).
        :return: True if the values were successfully changed, False otherwise.
        :rtype: bool
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nChange values of "tcp_keep_alive_time" , "tcp_keep_alive_intvl" and "tcp_keep_alive_probes"  defined in IVI RSI Gateway within "server_general_options" \n{"#" * 100}\n')
            with open(self.modified_rsi_gateway_config) as jsonfile:
                #Remove comments lines as they are not supported by JSON
                json_data = ''.join(line for line in jsonfile if not '#' in line)
                rsi_gateway_config = json.loads(json_data)
                # Modify the relevant parameters
                rsi_gateway_config['server_general_options']['tcp_keep_alive_time'] = tcp_keep_alive_time
                self._reporting.add_report_message_info(f'server tcp_keep_alive_time is set to {tcp_keep_alive_time} s')
                rsi_gateway_config['server_general_options']['tcp_keep_alive_intvl'] = tcp_keep_alive_intvl
                self._reporting.add_report_message_info(f'server tcp_keep_alive_intvl is set to {tcp_keep_alive_intvl} s')
                rsi_gateway_config['server_general_options']['tcp_keep_alive_probes'] = tcp_keep_alive_probes
                self._reporting.add_report_message_info(f'server tcp_keep_alive_probes is set to {tcp_keep_alive_probes} s')
            # Save changes 
            with open(self.modified_rsi_gateway_config, 'w') as jsonfile:
                json.dump(rsi_gateway_config, jsonfile, indent=2)
            self._reporting.add_report_message_info('Changing values of "tcp_keep_alive_time" , "tcp_keep_alive_intvl" and "tcp_keep_alive_probes" within "server_general_options" defined in IVI RSI_Gateway.json file - Success')
            return True
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Changing values of "tcp_keep_alive_time" , "tcp_keep_alive_intvl" and "tcp_keep_alive_probes" within "server_general_options" defined in IVI RSI_Gateway.json file - Failed: {error}')
            return False         
    
    def change_server_service_tcp_keepAlive_parameters(self,partition:str, tcp_keep_alive_time: int ,tcp_keep_alive_intvl : int, tcp_keep_alive_probes : int , service_name:str):
        """Change the general server TCP keepalive parameters within IVI RSI Gateway.

        :param int tcp_keep_alive_time: The time, in seconds, between the last TCP data packet sent and the first TCP keepalive packet.
        :param int tcp_keep_alive_intvl: The time, in seconds, between two TCP keepalive packets.
        :param int tcp_keep_alive_probes: The maximum number of TCP keepalive packets that should be sent before closing the server socket connection.
        :return: True if the values were successfully changed, False otherwise.
        :rtype: bool
        """
        try:
            if partition == self.ivi_partition_name:
                if self.backup_rsi_gateway_config_file == "":
                    result = self.backup_rsi_gateway_config(partition)
                    if not result:
                        return False
                if self.modified_rsi_gateway_config == "":
                    self.modified_rsi_gateway_config = self.download_ivi_rsi_gateway_config()

                rsi_gateway_config = self.remove_comments_from_json_file(self.modified_rsi_gateway_config)
                
                try:
                    if rsi_gateway_config['service_ports'][f'/{service_name}']:
                        service_instance_id = None
                        service_instance_id = rsi_gateway_config['service_ports'][f'/{service_name}'][0]
                        
                        self._reporting.add_report_message_info(f'service_instance_is:{service_instance_id}')
                        if service_instance_id is not None:
                            service_viwi_frontend = None
                            for element in rsi_gateway_config['viwi_frontends']:
                                if element['frontend_instance_id']== service_instance_id:
                                    service_viwi_frontend = element
                            if service_viwi_frontend is not None:
                                if "security_level" in service_viwi_frontend:
                                    service_viwi_frontend['security_level'] = "none"
                                listening_port =  service_viwi_frontend["listening_ports"]
                                service_port = r'\[(.*?)\]:(\d+)'
                                match = re.search(service_port, listening_port)
                                if match:
                                    service_port = int(match.group(2))
                                    service_viwi_frontend["listening_ports"] = f'[{self.ivi_ip}]:{service_port}'
                                    service_viwi_frontend['tcp_keep_alive_time'] = tcp_keep_alive_time
                                    service_viwi_frontend['tcp_keep_alive_intvl'] = tcp_keep_alive_intvl
                                    service_viwi_frontend['tcp_keep_alive_probes'] = tcp_keep_alive_probes   

                except Exception as error:
                    self._reporting.add_report_message_system_error(f'error occured during changing {service_name} paramaters  : {error}')     
                    return False , 0
                
                # Save changes 
                with open(self.modified_rsi_gateway_config, 'w') as jsonfile:
                    json.dump(rsi_gateway_config, jsonfile, indent=2) 

                self._reporting.add_report_message_info(f'Changing {service_name}  parameters values defined in IVI RSI Gateway - Success')
                return True , service_port
            
            if partition == self.sys_partition_name:
                return False , 0
                #need to be implemented
        except Exception as error:
            self._reporting.add_report_message_info(f'error has occured:{error}')
            return False , 0
     

    def change_client_service_tcp_keepAlive_parameters(self, partition:str, service: str, keepalive_time: int, keepalive_intvl: int, keepalive_probes:int):
        """Change Client TCP keepAlive parameters in RSI Gateway configuration file.

        :param int keepalive_time: The time, in seconds, between the last tcp packet and the first tcp keepAlive packet.
        :param int keepalive_intvl: The time, in seconds, between two successive tcp keepalive packets.
        :param int keepalive_probes: The maximum number of tcp keepalive packets that sould be sent before closing the client socket connection.
        :return: True if the parameters are successfully changed, False otherwise.
        :rtype: bool
        """
        try:
            self.modify_rsi_gateway_config(partition = partition, parameter = "tcp_keep_alive_time", value = keepalive_time, section = ["client_connections",f'/{service}'])
            self.modify_rsi_gateway_config(partition = partition, parameter = "tcp_keep_alive_intvl", value = keepalive_intvl, section = ["client_connections",f'/{service}'])
            self.modify_rsi_gateway_config(partition = partition, parameter = "tcp_keep_alive_probes", value = keepalive_probes, section = ["client_connections",f'/{service}'])
            return True
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Change client service tcp keepAlive parameters - Failed: {error}')
            return False
        
    def start_sending_clamp15_and_NM_simulation(self):
        """ Start sending the Clamp15 and NM simulation.

        This function starts the sending of keep-alive signals Clamp15 and NM simulation fixtures. 
        It reports the success or failure of the operation.

        Return:
            bool: True if starting the simulation was successful, False otherwise.
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nStart Clamp15 simulation and NM simulation for NM_Gateway message 0x1B000010 with signal NM_Gateway_NM_State value equal to 0x4(NM_NO_aus_RM)\n{"#" * 100}\n')
            self.keepalive_sim.start_sending()
            self._reporting.add_report_message_info('Start Clamp15 and NM simulation - Successful')
            return True
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Start Clamp15 and NM simulation - Failed :{error}')
            return False   

    def stop_sending_clamp15_and_NM_simulation(self):
        """Start sending the Clamp15 and NM simulation.

        :return: True if starting the simulation was successful, False otherwise.
        :rtype: bool
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nStop Clamp15 and NM simulation\n{"#" * 100}\n')
            self.keepalive_sim.stop_sending()   
            time.sleep(5)
            self._reporting.add_report_message_info('Stop Clamp15 and NM simulation - Successful')
            return True
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Stop Clamp15 and NM simulation - Failed :{error}')
            return False
      
    def compare_least_significant_bits(self, value: int, hex_string: str) -> bool:
        """ Compare the least significant 29 bits of a 32-bit unsigned integer with a provided hexadecimal string.

        This function extracts the least significant 29 bits from the provided uint32_number and converts it to a hexadecimal string.
        It then performs a case-insensitive comparison with the provided hex_string.

        :param int value: A 32-bit unsigned integer.
        :param str hex_string: A hexadecimal string representing the expected value of the least significant 29 bits.
        :return: True if the extracted least significant bits match the provided hex_string, False otherwise.
        :rtype: bool
        """
        mask = 0x1FFFFFFF  # 29 bits set to 1
        extracted_bits = value & mask
        extracted_hex_string = f"0x{extracted_bits:08X}"
        comparison_result = extracted_hex_string.lower() == hex_string.lower()
        return comparison_result
    
    def wait_for(self, seconds: float):
        """ Pause execution for a specified number of seconds.

        :param int seconds: Pauses execution for a specified number of seconds.
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nWait for {seconds} seconds\n{"#" * 100}\n')
        time.sleep(seconds)
        self._reporting.add_report_message_info(f'Wait for {seconds} seconds - Done')
        
    def start_capturing_can_messages(self, can_msg_id :list[str] , capturing_time:int): 
        """Start capturing CAN messages for a specified duration.

        :param list[str] can_msg_id: The list of CAN message IDs to capture.
        :param int capturing_time: The duration for which to capture the CAN messages, in seconds.
        :return: None
        """
        self.start_can_listener(can_msg_id)
        self.wait_for(capturing_time)
        self.stop_can_listener()
        self._reporting.add_report_message_info('Start capturing CAN messages - Successful')
            
    def check_can_signal_value(self,can_msg_id:str, signal_start_byte:int, signal_bit_length:int ,desired_signal_value:int):
        """ Check if a specific CAN signal value matches a predefined value in the CAN messages.
        :param str can_msg_id: the message ID contains the signal value.
        :param int signal_start_byte: The byte index where the signal starts (1-based indexing).
        :param int signal_bit_length: The length of the signal in bits.
        :param int desired_signal_value: The desired value of the signal to be matched.
        :return: True if the specified CAN signal value is found in any of the messages, False otherwise.
        :rtype: bool
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nCheck CAN signal value\n{"#" * 100}\n')
        right_signal_value = False
        can_msg_byte = None

        for can_message in self.can_messages_queue.queue:
            if self.compare_least_significant_bits(can_message.can_header.message_id,can_msg_id):
                can_msg_byte= bytes(can_message.payload)
                break
        if  can_msg_byte is None:
            return False 
              
        # Calculate the byte index and bit mask based on signal_start_byte and signal_bit_length
        byte_index = signal_start_byte - 1  # Convert to zero-based indexing
        bit_mask = (1 << signal_bit_length) - 1  # Create a bitmask with the specified number of bits
        # Extracting the specified bits from the specified byte and converting to an integer
        signal_value = (can_msg_byte[byte_index]) & bit_mask
        if signal_value == desired_signal_value:
            right_signal_value = True
            self._reporting.add_report_message_info('Check CAN signal value - Successful')
        if right_signal_value is False:
            self._reporting.add_report_message_system_error(f'Check CAN signal value - Failed')

        return right_signal_value    

    def start_can_listener(self, searched_can_message_ids: list[str]):
        """ Start capturing CAN messages using a message sniffer.

        This method initiates the capturing of CAN messages using a message sniffer. It sets up the necessary configurations
        for capturing CAN messages and starts the capture process.

        :param str searched_can_message_ids: The message ID of the CAN message to search for during the capture process.
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nStart capturing CAN messages\n{"#" * 100}\n')
            logging_channel = andisdk.andi.create_channel(os.environ.get('logging_adapter', 'logs'))
            self.eth_message_listner = andisdk.message_builder.create_ethernet_message(sender=logging_channel, receiver=logging_channel)
            self.callback_func = self.can_callback_function(searched_can_message_ids)
            self.eth_message_listner.on_message_received += self.callback_func
            self.eth_message_listner.start_capture()
            self._reporting.add_report_message_info('Start capturing CAN messages - Successful')

        except Exception as error:
            self._reporting.add_report_message_ta_error(f'Start capturing CAN messages - Failed: {error}')
            
    def can_callback_function(self, searched_can_message_ids: list[str]):
        def can_msg_received_callback(msg: andisdk.MessageEthernet):
            """ Process a received CAN message and add it to the message queue if it matches the searched CAN message ID.

            :param andisdk.MessageEthernet msg: The received Ethernet message containing the CAN message.
            :param list[str] searched_can_message_ids: list of CAN message IDs to search for.
            """
            can_msg = msg.get_can_layer()
            if can_msg != None :
                for each_can_msg_id in searched_can_message_ids:
                    if self.compare_least_significant_bits(can_msg.can_header.message_id,each_can_msg_id):
                        self.can_messages_queue.put(can_msg)

        return can_msg_received_callback

    def stop_can_listener(self):
        """ Stops capturing CAN messages.
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nStop capturing CAN messages\n{"#" * 100}\n')
        self.eth_message_listner.on_message_received -= self.callback_func
        self.eth_message_listner.stop_capture()
        self._reporting.add_report_message_info('Stop capturing CAN messages - Successful')

    def start_sd_offers_listener(self,partition:str):
        """ Start capturing SOME/IP SD offers messages using a message sniffer.

        This method initiates the capturing of SOME/IP SD offers using a message sniffer. It sets up the necessary configurations
        for capturing SOME/IP SD offers and starts the capture process.
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nStart capturing SD offers\n{"#" * 100}\n')
            logging_channel = andisdk.andi.create_channel(os.environ.get('stimulation_adapter', 'logs'))
            self.sd_offers_listner = andisdk.message_builder.create_ethernet_message(sender=logging_channel, receiver=logging_channel)
            self.sd_callback_func = self.sd_callback_function(partition)
            self.sd_offers_listner.on_message_received += self.sd_callback_func
            self.sd_offers_listner.start_capture()
            self._reporting.add_report_message_info('Start capturing SD offers - Successful')

        except Exception as error:
            self._reporting.add_report_message_ta_error(f'Start capturing SD offers - Failed: {error}')

    def sd_callback_function(self, partition):
        def sd_offers_received_callback(msg: andisdk.MessageEthernet):
            """ Process a received SOME/IP SD offers and add it to the message queue.

            :param andisdk.MessageEthernet msg: The received Ethernet message containing SOME/IP SD offer.
            """
            udp_msg:andisdk.MessageUDP = msg.get_udp_layer()
            if not udp_msg  or udp_msg.udp_header.port_destination != 30491:
                   return 
            if partition == self.ivi_partition_name:

                if udp_msg.ip_header.ip_address_source == self.ivi_ip:
                        self.ivi_sd_offers_queue.put(msg)
            elif partition == self.sys_partition_name:
               
               if  udp_msg.ip_header.ip_address_source == self.sys_ip:
                   self.sys_sd_offers_queue.put(msg)
              
        return sd_offers_received_callback
    
    def stop_sd_offers_listener(self):
        """ Stop capturing SOME/IP SD offers.
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nStop capturing SOME/IP SD offers\n{"#" * 100}\n')
        self.sd_offers_listner.on_message_received -= self.sd_callback_func
        self.sd_offers_listner.stop_capture()
        self._reporting.add_report_message_info('Stop SOME/IP SD offers - Successful')

    def check_viwi_sd_offers(self, partition:str, capturing_time:int, service_name:str=""):
        """ Check ViWi SOME/IP SD offers availability.

        :param partition: target partition
        :param capturing_time: the capturing time
        :param service_name: service name
        :return: 
        :rtype: bool
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nCheck ViWi SOME/IP SD offer availability\n{"#" * 100}\n')
            self.start_sd_offers_listener(partition)
            self.wait_for(capturing_time)
            self.stop_sd_offers_listener()

            if partition == self.ivi_partition_name:
                return self.check_viwi_ivi_sd_offer(service_name)
            elif partition == self.sys_partition_name:
                return self.check_viwi_sys_sd_offer(service_name)
            else:
                return False
            
        except Exception as error:
            self._reporting.add_report_message_ta_error(f'ViWi SOME/IP SD offers captured - Failed: {error}')
            return False
        
    def check_viwi_ivi_sd_offer(self, service_name:str =""):
        """Check if a VIWI IVI SD offer contains a specific service.

        :param str service_name: The name of the service to check (optional).
        :return: True if the service is found in the IVI SD offer list (or if the list is not empty), False otherwise.
        :rtype: bool
        """
        msg : andisdk.MessageEthernet
        
        for msg in self.ivi_sd_offers_queue.queue:

            sd_header = andisdk.MessageSomeIPSD(msg.get_someip_sd_layer())
            offer_entries = list(sd_header.get_offer_service_entries())
            if offer_entries:
                for offer_entry in offer_entries:
                    for option in offer_entry.options:
                        self.ivi_sd_offer_list.append(str(option.configuration))
        if service_name !="":
                    return service_name in self.ivi_sd_offer_list
        else:
            return len(self.ivi_sd_offer_list) != 0
        
    def check_viwi_sys_sd_offer(self, service_name:str =""):
        """Check if a VIWI SYS SD offer contains a specific service.

        :param str service_name: The name of the service to check (optional).
        :return: True if the service is found in the IVI SD offer list (or if the list is not empty), False otherwise.
        :rtype: bool
        """
        msg : andisdk.MessageEthernet
        if service_name !="":

            for msg in self.sys_sd_offers_queue.queue:

                sd_header = andisdk.MessageSomeIPSD(msg.get_someip_sd_layer())
                offer_entries = list(sd_header.get_offer_service_entries())
                if offer_entries:
                    for offer_entry in offer_entries:
                        for option in offer_entry.options:
                            self.sys_sd_offer_list.append(str(option.configuration))

                    return service_name in self.ivi_sd_offer_list
        else:
            return len(self.sys_sd_offer_list) != 0
        
    def disable_partition_firewall(self, partition:str):
        #use partition name 
        """ Disable (IVI) firewall.
        :param str partition : the partition target to disable its Firewall.
        """
        if partition == self.ivi_partition_name:
            self.disable_ivi_firewall()

        elif partition == self.sys_partition_name:
            self._reporting.add_report_message_system_error("NEED TO BE CONFIGURED !!")
            raise NotImplementedError
        else:
            self._reporting.add_report_message_system_error("Wrong Partition IP")
            
    def disable_ivi_firewall(self):
        """Disable the IVI firewall
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nDisabling IVI firewall\n{"#" * 100}\n')
            self.adb_command = f'adb connect 172.16.250.248:5555 && adb root && adb remount'
            self.execute_command(self.adb_command)
            self.adb_command = f'adb shell "ip6tables -j ACCEPT -I OUTPUT" && adb shell "ip6tables -j ACCEPT -I INPUT" && adb shell "ip6tables -j ACCEPT -I FORWARD"'
            self.execute_command(self.adb_command)
            self._reporting.add_report_message_info("Disabling IVI firewall -Success")
        except Exception as error:
            self._reporting.add_report_message_ta_error(f'Disabling IVI firewall - Failed: {error}')

    def apply_config_changes(self, partition:str):
        """ Push the changes made to the RSI Gateway configuration file and reboot the specified partition.

        :param str partition: The partition to which the changes should be pushed. 
        :return: True if the changes were successfully pushed and the partition rebooted, False otherwise.
        :rtype: bool
        """
        try:    
            if partition == self.ivi_partition_name:
                return self.apply_ivi_config_changes()
            
            if partition == self.sys_partition_name:

                self._reporting.add_test_result_system_error("NEED TO BE IMPLEMENTED !!")
                raise NotImplementedError("NEED TO BE IMPLEMENTED !!")
            else:
                raise ValueError("Invalid partition specified.")
        except NotImplementedError as error:
            return False
        
        except ValueError as error:
            self._reporting.add_report_message_system_error(f'Invalid partition specified: {error}')
            return False
    
    def apply_ivi_config_changes(self):
        """Apply the configured changes to the IVI.

        :return: True if the changes were successfully applied, False otherwise.
        :rtype: bool
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nPush new configured rsi_gateway-userdebug.json to IVI \n{"#" * 100}\n')
            # Copy file to report path
            self.copy_file_to_execution_report(self.modified_rsi_gateway_config, 'rsi_gw_config_ivi_modified.json')
            self.adb_command = f'adb connect 172.16.250.248:5555 && adb root && adb remount && adb push {self.modified_rsi_gateway_config} {self.ivi_rsi_gw_path}'
            self.execute_command(self.adb_command)
            self.reboot_ivi()
            self._reporting.add_report_message_info('Push new configured rsi_gateway-userdebug.json to IVI - Success')
            return True
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Push new configured rsi_gateway-userdebug.json to IVI - Failed :{error}')
            return False
        
    def reboot_ivi(self):
        """Reboot the IVI device.
        """
        self.adb_command = f'adb connect 172.16.250.248:5555 && adb root && adb shell "reboot"'
        self.execute_command(self.adb_command)
        # wait for restart
        self._reporting.add_report_message_info('Waiting for reboot')
        self.wait_for(hcp3_reboot_time)

    def restore_initial_rsi_config(self, partition:str):
        """Restore the initial RSI Gateway configuration file.

        :param str partition: The partition to  which the initial configuration should be restored. 
        :return: True if the initial configuration was successfully restored, False otherwise.
        :rtype: bool
        """
        try:
            if partition == self.ivi_partition_name:
                self.adb_command = f'adb connect 172.16.250.248:5555 && adb root && adb remount && adb push {self.backup_rsi_gateway_config_file} {self.ivi_rsi_gw_path}'
                self.execute_command(self.adb_command)
                self.reboot_ivi()
                self._reporting.add_report_message_info('Restoring initial config of IVI RSI Gateway file - Success') 
                return True
            if partition == self.sys_partition_name:
                self._reporting.add_report_message_info('NEED TO BE CONFIGURED !!') 
                return False
        except Exception as error:
            self._reporting.add_report_message_ta_error(f'Restoring initial config of RSI Gateway file to {partition} - Failed: {error}')
            return False
    
    def resume_sending_tcp_messages(self):
        """ Cleanup PC firewall configuration.
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nCleanup PC firewall configuration\n{"#" * 100}\n')
            self.adb_command = 'sudo ip6tables -F'
            self.execute_command(self.adb_command)
            self._reporting.add_report_message_info("Cleanup PC firewall configuration - Success")
        except Exception as error:
            self._reporting.add_report_message_ta_error(f"Cleanup PC firewall configuration - Failed: {error}")

    def start_capturing_tcp_messages(self, callback_func:Callable):
        """ Start capturing TCP packets using a message sniffer.

        This method initiates the capturing of TCP packets using a message sniffer. It sets up the necessary configurations
        for capturing TCP packets and starts the capture process.

        :param function callback_func: The callback function to filter on TCP messages.
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nStart capturing TCP packets\n{"#" * 100}\n')
            logging_channel = andisdk.andi.create_channel(os.environ.get('stimulation_adapter', 'logs'))
            self.tcp_packets_listner = andisdk.message_builder.create_ethernet_message(sender=logging_channel, receiver=logging_channel)
            self.tcp_callback_func = callback_func
            self.tcp_packets_listner.on_message_received += self.tcp_callback_func
            self.tcp_messages_queue = queue.Queue()
            self.tcp_packets_listner.start_capture()
            self._reporting.add_report_message_info('started capturing TCP packets - Success')
        except Exception as error:
            self._reporting.add_report_message_ta_error(f'Start capturing TCP packets - Failed: {error}')

    def stop_capturing_tcp_messages(self):
        """ Stop the capturing of TCP packets.
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\nStop capturing TCP packets\n{"#" * 100}\n')
        self.tcp_packets_listner.on_message_received -= self.tcp_callback_func
        self.tcp_packets_listner.stop_capture()
        self._reporting.add_report_message_info('Stop capturing TCP packets - Successful')
    
    def stop_sending_tcp_messages(self, port:int, flags:str, port_direction:str='d'):
        """ Stop sending TCP messages.

        :param int port: The port number
        :param str flags: The TCP flags to be dropped, e.g., 'ACK,PSH'
        :param str port_direction: The direction of traffic, 'Source' or 'Destination' (default is 'Destination')
        """
        try:
            # Drop TCP messages
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nStopping sending TCP messages to/from : {port_direction}port: {port} \n{"#" * 100}\n')
            command = f'sudo ip6tables -A OUTPUT -p tcp --{port_direction}port {port} --tcp-flags {flags} -j DROP'
            self.execute_command(command)
            self._reporting.add_report_message_pass(f'TCP messages with flags {flags} on {port_direction}port {port} are stopped')
        except Exception as error:
            self._reporting.add_report_message_system_error(f"Error occurred while stopping sending TCP messages:{error}")
            
    def create_ws_connection(self, uri:str):
        """Create a WebSocket connection.

        :param str uri: The URI to connect to.
        :return: WebSocket connection object if successful, None otherwise.
        """
        try:
            self._reporting.add_report_message_info(f'create WS connection on : {uri}')
            ws = create_connection(uri, timeout=10)
            self._reporting.add_report_message_info(f'WS create connection on :{uri} - Success')
            return ws

        except Exception as error:
            self._reporting.add_report_message_system_error(f"WS create connection -Failed: {error}")
    
    def send_ws_subscription_request(self, ws: websocket, service: str, resource: str, element: str = "", autosubscribe: bool = False):
        """Send a WebSocket subscription request.

        :param websocket ws: The WebSocket connection object.
        :param str service: The service name.
        :param str resource: The resource name.
        :param str element: The element name (optional).
        :param bool autosubscribe: Whether to automatically subscribe to updates (default is False).
        :return: None
        """
        self._reporting.add_report_message_info(f'Send WS subscription request for {service}/{resource}/{element}')
        subscribe_data = {'type': 'subscribe', 'event': f'/{service}/{resource}/{element}', 'autosubscribe': autosubscribe}
        ws.send(json.dumps(subscribe_data))
        self._reporting.add_report_message_info(f'Send WS subscription request for {service}/{resource}/{element} - Success')
    
    def receive_next_ws_event(self, ws:websocket):
        """Receive the next WebSocket event.

        :param websocket ws: The WebSocket connection object.
        :return: The received WebSocket event.
        """
        ws.settimeout(10)
        received_event = json.loads(ws.recv())
        self._reporting.add_report_message_info(f'Received Ws event - Success :{received_event}')
        return received_event
    
    def send_ws_subscription_request_and_check_tcp_parameters(self, host:str, port:int, service:str, resource:str, keepalive_time:int, keepalive_intvl:int, keepalive_probes:int, capturing_time:int):
        """Send a WebSocket subscription request and check TCP parameters.

        :param str host: The host address.
        :param int port: The port number.
        :param str service: The service name.
        :param str resource: The resource name.
        :param int keepalive_time: The TCP keep-alive time, in seconds.
        :param int keepalive_intvl: The TCP keep-alive interval, in seconds.
        :param int keepalive_probes: The maximum number of TCP keep-alive probes.
        :param int capturing_time: The duration for capturing TCP messages, in seconds.
        :return: True if the TCP parameters are as expected, False otherwise.
        :rtype: bool
        """
        try:
            self.disable_partition_firewall(self.ivi_partition_name)
            self.start_capturing_tcp_messages(self.tcp_keepalive_callback(port))

            # self._reporting.add_report_message_info(f'\n{"#" * 100}\nSend WS subscription on "{uri}" resource to IVI\n{"#" * 100}\n')
            ws_uri = f'ws://[{host}]:{port}/{service}'
            self.ws = self.create_ws_connection(ws_uri)
            self.send_ws_subscription_request(self.ws, service, resource)
            subscription_ack_message = self.receive_next_ws_event(self.ws)
            # use report for check status
            if  subscription_ack_message["status"] != "ok":
                self._reporting.add_report_message_system_error(f'ws subscription on {ws_uri} - Failed :{subscription_ack_message} ')
                return False

            initial_event = self.receive_next_ws_event(self.ws)

            if not initial_event:
                self._reporting.add_report_message_system_error('ws receiving intial event - Failed')
                return False

            self.stop_sending_tcp_messages(port, flags="ACK,PSH ACK")
            self.wait_for(capturing_time)
            self.stop_capturing_tcp_messages()
            self.resume_sending_tcp_messages()
            result = self.check_tcp_keep_alive_parameters(keepalive_time, keepalive_intvl ,keepalive_probes, port)
            return result
        
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Subscribing on {ws_uri} resource and receiving initial event - Failed : {error}')
            return False
    
    def tcp_keepalive_callback(self, port:int):
        """Create a TCP keep-alive received callback function.

        :param int port: The port number to filter TCP messages.
        :return: The callback function for processing received TCP messages.
        """
        def tcp_keepalive_received_callback(msg: andisdk.MessageEthernet):
                tcp_message: andisdk.MessageTCP = msg.get_tcp_layer()

                if tcp_message and \
                (tcp_message.transport_header.port_source == port) and \
                        tcp_message.tcp_header.flags == 0x10:
                    self.tcp_messages_queue.put(tcp_message)
        return tcp_keepalive_received_callback
    
    def check_tcp_keep_alive_parameters(self, keepalive_time: int, keepalive_intvl: int, keepalive_probes:int ,port:int):
        """ Check TCP keepAlive parameters.

        :param int keepalive_time: The time, in seconds, between the last tcp packet and the first tcp keepAlive packet.
        :param int keepalive_intvl: The time, in seconds, between two successive tcp keepalive packets.
        :param int keepalive_probes: The maximum number of tcp keepalive packets that sould be sent before closing the tcp socket connection.
        :param int port: The port to which tcp keepalive messages are being sent.
        :return: True if the TCP keepAlive parameters are correct, False otherwise.
        :rtype: bool
        """
        try:
            self._reporting.add_report_message_info(f'\n{"#" * 100}\nCheck TCP keepAlive parameters\n{"#" * 100}\n')

            current_packet = self.tcp_messages_queue.get(timeout=1)
            is_last_comm_packet = True

            #init timestamp
            ref_timestamp = 0
            delta_time = 0
            
            keepalive_probes_received = 0
            stream_src_port = port
            
            for current_packet in self.tcp_messages_queue.queue:
                if current_packet != None:
                    if (current_packet.transport_header.port_source == stream_src_port or
                         current_packet.transport_header.port_destination == stream_src_port):
                        if is_last_comm_packet:
                            if ref_timestamp == 0:
                                ref_timestamp = current_packet.timestamp
                            else:
                                keepalive_probes_received += 1
                                is_last_comm_packet = False
                                delta_time = current_packet.timestamp - ref_timestamp
                                ref_timestamp = current_packet.timestamp
                                # check keepalibe_time
                                if delta_time < keepalive_time*0.9 or delta_time > keepalive_time*1.1:
                                    self._reporting.add_report_message_system_error(f"Wrong keepalive_time: expected {keepalive_time}, actual {delta_time}")
                                    return False
                        else:
                            keepalive_probes_received += 1
                            delta_time = current_packet.timestamp - ref_timestamp
                            ref_timestamp = current_packet.timestamp
                            # check keepalibe_time
                            if delta_time < keepalive_intvl*0.9 or delta_time > keepalive_intvl*1.1:
                                self._reporting.add_report_message_system_error(f"Wrong keepalive_interval: expected {keepalive_time}, actual {delta_time}")
                                return False
            # Check probes number
            if keepalive_probes != keepalive_probes_received:
                self._reporting.add_report_message_system_error(f"Wrong keepalive_probes: expected {keepalive_probes}, actual {keepalive_probes_received}")
                return False
            
            self._reporting.add_report_message_pass('Check TCP keepAlive parameters')
            return True        
        except Exception as error:
            self._reporting.add_report_message_system_error(f"Error has occured during Check TCP keepAlive parameters: {error}")
            return False
    
    def register_service(self, service: str, server_ip: str, server_port: str, host: str, port: str):
        """Register a service.

        :param str service: The name of the service to register.
        :param str server_ip: The IP address of the server providing the service.
        :param str server_port: The port on which the server is listening for the service.
        :param str host: The host IP address of the registration server.
        :param str port: The port on which the registration server is running.
        :return: True if the service registration was successful, False otherwise.
        :rtype: bool
        """
        try:
            # Register service with PUT
            put_request_payload = {
                    'port': server_port,
                    'http_uri': f"http://[{server_ip}]:{server_port}/{service}"
                }
            res = requests.put(f'http://[{host}]:{port}/{service}', json=put_request_payload, timeout=15)
            if res.status_code == 201:
                self.registered_service_location = res.headers['Location']
                self._reporting.add_report_message_info(f"Successfully registered service {service} with PUT request. Response: {res}")
                return True
            else:
                self._reporting.add_report_message_system_error(f"Failed to register service {service}. Unexpected response: {res}")
                return False

        except requests.HTTPError as e:
                self._reporting.add_report_message_system_error(f"Exception occurred while registering service {service}: {e}")
                return False

    def mock_service(self, service: str, host: str, port: str):
        """Mock a service.

        :param str service: The name of the service to mock.
        :param str host: The host IP address of the service.
        :param str port: The port on which the service is running.
        :return: A thread object representing the mock service operation.
        :rtype: threading.Thread
        """
        def mock_service_request():
            try:
                # Mock Get request
                http_request_url = f'http://[{host}]:{port}/{service}'
                resp = requests.get(http_request_url, timeout=10)
                self._reporting.add_report_message_info(f"Successfully mocked service {service} with GET request. Response: {resp}")
                return True
            except requests.HTTPError as e:
                self._reporting.add_report_message_system_error(f"Exception occurred while mocking service {service}: {e}")
                return False

        mock_thread = threading.Thread(target=mock_service_request)
        mock_thread.start()
        return mock_thread    

    def start_capturing_esotrace(self, partition_name: str, esotrace_callback_func:Callable):
        """Start capturing esotrace messages.

        :param str partition_name: The name of the partition to capture esotrace messages from.
        :param Callable esotrace_callback_func: The callback function to handle the received ESOTRACE messages.
        :return: None
        """
        try:
            self._reporting.add_report_message_info(f'\n{"*" * 100}\n Start esotraces capturing\n{"*" * 100}\n')
            self.ServerRegistry = Server(partition_name)
            self.ServerRegistry.connect()
            self.ServerRegistry.wait_for_online()
            self.ServerRegistry.register('esotrace_message', esotrace_callback_func)
            self._reporting.add_report_message_info('Start esotraces capturing - Success')
        except Exception as e:
            self._reporting.add_report_message_system_error(f'Enable to start capturing esotraces: {e}')

    def stop_esotrace_capture(self):
        """Stop capturing esotrace messages
        """
        self.ServerRegistry.disconnect()
  
    def esotrace_on_service_callback(self, service_name: str):
        """Create a callback function to handle esotrace messages for a specific service.

        :param str service_name: The name of the service.
        :return: The callback function to handle esotrace messages.
        :rtype: Callable[['enna.core.interfaces.Data'], None]
        """
        def on_esotrace_message(msg: 'enna.core.interfaces.Data'):
            if not self.esotrace_queue_evt.is_set():
                if (f'rudi.service.{service_name}' in str(msg.value['channel_name'])) or (f'rudi.client.{service_name}') in str(msg.value['channel_name']):
                        self.esotrace_queue.put(msg)
        return on_esotrace_message
    
    def esotrace_actionError_callback(self, service_name: str):
        """Create a callback function to handle esotrace actionError messages for a specific service.

        :param str service_name: The name of the service.
        :return: The callback function to handle esotrace actionError messages.
        :rtype: Callable[['enna.core.interfaces.Data'], None]
        """
        def on_esotrace_message(msg: 'enna.core.interfaces.Data'):
            if not self.esotrace_queue_evt.is_set():
                if (f'rudi.service.{service_name}' in str(msg.value['channel_name'])) or (f'rudi.client.{service_name}') in str(msg.value['channel_name']) :
                    if 'actionError' in str(msg.value["message_data"]):
                        self._reporting.add_report_message_info(f'##### Esotrace actionError message captured: {msg}')
                        self.esotrace_actionerror_queue.put(msg)
        return on_esotrace_message
        
    def enable_service_channel_logs(self,service_name:str):
        """Enable channel logs for a specific service.

        :param str service_name: The name of the service.
        :return: None
        """
        try:
            self.wait_for(2) 
            self._reporting.add_report_message_info(f'\n{"#" * 100}\n Set channels loglevels to trace for {service_name}\n{"#" * 100}\n')
            cmd = f'java -jar jtracecmd.jar -H 172.16.250.248 -p 21002 -P traceserverIVI. channel rsi_gatewayIVI.rudi.service.{service_name} trace'
            cwd = '/home/jschaeferling/esoTraceTools-4.3.6/tools'
            self._reporting.add_report_message_info(f'performing following command to write loglevels: {cmd}')
            self.execute_command(cmd,cwd)
            cmd = f'java -jar jtracecmd.jar -H 172.16.250.248 -p 21002 -P traceserverIVI. channel rsi_gatewayIVI.rudi.service.{service_name}'
            self._reporting.add_report_message_info(f'performing following command to read loglevels: {cmd}')
            self.execute_command(cmd,cwd)
            self._reporting.add_report_message_pass(f'successfully enabled {service_name} channel logs')
        
        except Exception as e:
            self._reporting.add_report_message_system_error(F'Was not able to set levels for {service_name}, cannot guarantee results !! {e}')      
    
    def delete_registered_service(self, location):
        """Delete a created client.

        :param str location: The location of the service to be deleted.
        :return: The response object if the deletion was successful, None otherwise.
        :rtype: Optional[requests.Response]
        """
        try:
            res = requests.delete(location)
            self._reporting.add_report_message_info(f'successfully deleted the registred service: {res}')
            return res
        except Exception as e:
            self._reporting.add_report_message_system_error(f'Delete request failed: {e}')
            return None

    def simulate_viwi_ws_server(self):
        """Start simulating the ViWi Websocket Server.
        """
        self._reporting.add_report_message_info(f'\n{"#" * 100}\n Start simulating ViWi Websocket Server\n{"#" * 100}\n')
        self.viwi_ws_server = create_websocket_server(server_ip = tester_server_ip,
                                                        server_port = tester_server_port,
                                                            reporting = self._reporting)
        start_websocket_server(self.viwi_ws_server)
        
    def simulate_viwi_flask_server(self):
        """Start simulating the ViWi Flask Server.

        """
        self.flask_server = create_flask_server(reporting = self._reporting,
                                                    server_ip = tester_server_ip,
                                                        server_port = tester_server_port,
                                                            http_url = '/ViWiTestability/switchControls/',
                                                                websocket_url = '/')
        start_flask_server(self.flask_server)    
    
    def mock_ws_subscription(self, partition:str, service_name:str, service_port:int, service_resource:str, autosubscribe: bool = False):
        """Mock a websocket subscription.

        :param str partition: The partition where the service is located.
        :param str service_name: The name of the service to subscribe to.
        :param int service_port: The port of the service.
        :param str service_resource: The resource of the service to subscribe to.
        :param bool autosubscribe: autosubscription type to the service (default is False).
        :return: The websocket client object used for the subscription.
        """
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

        ws_uri = f'ws://[{host}]:{service_port}/{service_name}'
        client_ws = self.create_ws_connection(uri = ws_uri)
        self.client_ws_source_ports.append(client_ws.sock.getsockname()[1])
        
        self.send_ws_subscription_request(ws = client_ws,
                                            service = service_name,
                                                resource = service_resource,
                                                    autosubscribe = autosubscribe)
        return client_ws
    
    def receive_client_http_request(self):
        """Receive a client HTTP request.

        :return: True if the expected HTTP request is received, False otherwise.
        :rtype: bool
        """
        client_http_request = get_next_flask_server_http_request(self.flask_server)
        if client_http_request:
            if 'GET'  in client_http_request and '/ViWiTestability/switchControls' in client_http_request:
                self._reporting.add_report_message_info('Successfully received client http GET /ViWiTestability/switchControls request for the second subscription')
                return True
            else:
                self._reporting.add_report_message_info(f'Unexpected client http request is received: {client_http_request}')
                return False
        else:
            self._reporting.add_report_message_system_error('Failed to received client http GET request')
            return False  

    def check_mocked_client_subscription_acknowledgement(self, *client_ws_list):
        """Check the subscription acknowledgement for mocked WebSocket clients.

        :param client_ws_list: A variable number of WebSocket clients to check.
        :type client_ws_list: WebSocket
        :return: True if the subscription acknowledgement and initial event are received for each client, False otherwise.
        :rtype: bool
        """
        try:
            for client_ws in client_ws_list:
                client_ws.settimeout(10)
                self.client_ws_list.append(client_ws)
            
            for index, client_ws in enumerate(client_ws_list, start=1):
                subscription_ack_data = client_ws.recv()
                initial_event_data = client_ws.recv()

                if initial_event_data:
                    self._reporting.add_report_message_info(f'ws subscription acknowledgement is received for mocked client {index}: {subscription_ack_data}')
                    self._reporting.add_report_message_info(f'initial event is received for mocked client {index}: {initial_event_data}')
                else:
                    self._reporting.add_report_message_system_error(f'No initial event received for mocked client {index}.')
                    return False

            return True
        except socket.timeout:
            self._reporting.add_report_message_system_error('Timeout occurred while waiting for data from the clients.')
            return False
        except Exception as error:
            self._reporting.add_report_message_system_error(f'Failed to receive initial event for clients: {error}')
            return False   
        
    def hold_capturing_esotrace_messages(self):
        """Hold capturing of esotrace messages.
        """
        self.wait_for(2)
        self.esotrace_queue_evt.set()     

    def check_action_response_on_esotrace(self, request_ids:list):
        """Check for action response messages in esotrace.

        :param list request_ids: List of request IDs to check for action response messages.
        :return: True if all action responses are found, False otherwise.
        :rtype: bool
        """
        try:
            if len(request_ids) != 0:
                check_action_response = False
                self.hold_capturing_esotrace_messages()
                request_id_found = 0
                for id in self.request_ids_list:
                    if id not in self.request_ids_backup_list:
                        self.request_ids_backup_list.append(id)
                    for msg in self.esotrace_actionresponse_queue.queue:
                        if '"requestId"' in str(msg.value["message_data"]):
                            msg_data = str(msg.value["message_data"])
                            msg_split = msg_data.split(sep=",")
                            request_id = int(next((e.split(sep=":"))[1] for e in msg_split if 'requestId' in e))
                            if request_id == id:
                                self._reporting.add_report_message_info(f' successfully captured action response for request ID:{request_id}')
                                request_id_found += 1
                                break
                self.clear_esotrace_queue() 
                self.resume_capturing_esotrace_messages()
                check_action_response = len(request_ids) == request_id_found
                self.request_ids_list = []     
                return check_action_response
            else:
                self._reporting.add_report_message_system_error('Failed: Request IDs list is empty')
                return False
        except Exception as e:
            self._reporting.add_report_message_system_error(f'Error checking actionResponse message in esotraces:{e}')
            return False

    def check_action_request_on_esotrace(self):
        """Check for action request message in esotrace.

        :return: True if an action request message is found and added successfully, False otherwise.
        :rtype: bool
        """
        try:
            self.hold_capturing_esotrace_messages()
            request_id = None
            for msg in self.esotrace_actionrequest_queue.queue:
                if '"requestId"' in str(msg.value["message_data"]):
                    msg_data = str(msg.value["message_data"])
                    msg_split = msg_data.split(sep=",")
                    request_id = int(next((e.split(sep=":"))[1] for e in msg_split if 'requestId' in e))
                    break   
            if request_id is not None and request_id not in self.request_ids_list:
                self.request_ids_list.append(request_id)
                self._reporting.add_report_message_info(f" Successfully captured actionRequest ID : {request_id}")
                self.clear_esotrace_queue()
                self.resume_capturing_esotrace_messages()
                return True
            else:
                self._reporting.add_report_message_system_error('Failed to capture actionRequest ID ' )
                return False
        except Exception as e:
            self._reporting.add_report_message_system_error(f'Error checking actionRequest message in esotraces:{e}')
            return False
            
    def clear_esotrace_queue(self):
        """Clear the esotrace action request and response queues.
        """
        self.esotrace_actionrequest_queue = queue.Queue()
        self.esotrace_actionresponse_queue = queue.Queue()

    def resume_capturing_esotrace_messages(self):
           """Resume capturing esotrace messages.
           """
           self.esotrace_queue_evt.clear()    

    def close_client_websocket(self):
        """Close client WebSocket connections.
        """
        for client_ws in self.client_ws_list:
            try:
                client_ws.close()
            except Exception as e:
                self._reporting.add_report_message_system_error(f"Failed to close WebSocket client: {e}")

    def acknowledge_received_ws_subscription(self):
        """Acknowledge received WebSocket subscription.
        """
        client_request = get_next_flask_server_websocket_request(self.flask_server)

        if client_request is None:
            self._reporting.add_report_message_info("No client request received.")
            return

        if "subscribe" in client_request and "/ViWiTestability/switchControls" in client_request:
            self._reporting.add_report_message_info("Successfully mocked ws request")
            subscription_ack_response = {
                "type": "subscribe",
                "status": "ok",
                "event": "/ViWiTestability/switchControls/#1"
            }
            initial_event_message = {
                "type": "data",
                "status": "ok",
                "event": "/ViWiTestability/switchControls/#1",
                "data": [
                    {
                        "id": "91c71fa6-6d18-46c9-af23-5433b7313609",
                        "name": "switchCtrlOne",
                        "uri": "/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609",
                        "restrictionReason": "one",
                        "switchValue": "two",
                        "switchValueConfiguration": ["one", "two", "three"]
                    }
                ]
            }

            send_ws_server_response(self.flask_server, [subscription_ack_response, initial_event_message])

    def simulate_http_get_response(self):
        """Simulate HTTP GET response.
        """        
        http_response_data = {
                    "data": [
                        {
                            "id": "91c71fa6-6d18-46c9-af23-5433b7313609",
                            "name": "switchCtrlOne",
                            "uri": "/ViWiTestability/switchControls/91c71fa6-6d18-46c9-af23-5433b7313609",
                            "restrictionReason": "one",
                            "switchValue": "two",
                            "switchValueConfiguration": ["one", "two", "three"]
                        }
                    ],
                    "status": "ok"   }

        send_flask_server_http_response(self.flask_server, response = http_response_data)        
    
    def esotrace_action_message_callback(self,service_name:str):
        """Callback function for ESOTRACE action messages.
        
        :param str service_name: The name of the service.
        :return: Callback function to handle ESOTRACE messages.
        """
        def on_esotrace_message(msg: 'enna.core.interfaces.Data'):
            if not self.esotrace_queue_evt.is_set():
                if (f'rudi.service.{service_name}' in str(msg.value['channel_name'])) or (f'rudi.client.{service_name}') in str(msg.value['channel_name']) :
                    if 'actionRequest' in str(msg.value["message_data"]):
                        self._reporting.add_report_message_info(f'##### Esotrace actionRequest message captured: {msg}')
                        self.esotrace_actionrequest_queue.put(msg)
                    elif 'actionResponse' in str(msg.value["message_data"]):
                        self._reporting.add_report_message_info(f'##### Esotrace actionResponse message captured: {msg}')
                        self.esotrace_actionresponse_queue.put(msg)   
                    # Filter and process ESOTRACE messages here
                    if (f'rudi.service.{service_name}' in str(msg.value['channel_name'])) or (f'rudi.client.{service_name}') in str(msg.value['channel_name']):
                        self.esotrace_queue.put(msg)
        return on_esotrace_message 