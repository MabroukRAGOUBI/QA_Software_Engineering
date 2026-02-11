import datetime
import logging
import os
import inspect
import subprocess
import time
import andisdk
import enna.core.time
import enna.core.config
import enna.core.interfaces.server
import enna.core.reporting.server_junit
import enna.core.component_system.decorators
import enna.core.interfaces.testing
import enna.core.interfaces.component
import queue
from enna.data_interfaces.esotrace.server_socket import Server
######################################################
# Monkey patching fot the Flask server to shut it down
import werkzeug.serving

from hcp3.viwi.fixtures import ivi_rsi_gw_configs
flaskServer = queue.Queue()
old_make_server = werkzeug.serving.make_server
def make_server(*args, **kwargs):
    global flaskServer
    _srv = old_make_server(*args, **kwargs)
    flaskServer.put(_srv)
    return _srv
werkzeug.serving.make_server = make_server
######################################################
from flask import Flask, jsonify, request
from flask_sock import Sock
import requests
from hcp3.viwi.server.offer_viwi_service import ViWiOfferDaemon
from hcp3.viwi.tests.smoke_tests.ivi_testbase import HCP3IVITestbase, TestBase
import requests.adapters
import threading, json
import websocket

@enna.core.component_system.decorators.RequireComponent('enna.core.reporting')
class rsi_expandable_enum_unknown_value_viwi_ws_IVI(enna.core.interfaces.testing.Stimulation):
    name = os.path.splitext(os.path.basename(__file__))[0]
    test_factory: type[TestBase] = HCP3IVITestbase
    host = 'fd53:7cb8:383:3::130'
    port = 14714
    server_port = 29797
    server_ip = "fd53:7cb8:383:3::3aa"
    protocol = 'ws'
    logging_adapter = os.environ.get("logging_adapter", "OnlineLogging")
    cfg = {
        "serverUri": "http://[fd53:7cb8:383:3::130]:29796",
        "serverRootPath": "",
        "serverWsUri": "ws://[fd53:7cb8:383:3::130]:29796",
        "logCommunication": True,
        "tcTimeout": 10000,
        "additionalRequestOptions": {
            "rejectUnauthorized": False,
            "timeout": 5000
        }
    }
    teardown = []
    ServerRegistry : Server
    esotrace_actionrequest_queue = queue.Queue()
    server_thread: threading.Thread
    viwi_service="ElectricalParkingBrake"
    viwi_resource="/ElectricalParkingBrake/functionControls"
    evt = threading.Event()
    eso_queue_evt = threading.Event()
    location = ""
    mocking_websocket: threading.Thread
    app = Flask(__name__)
    sock = None
    first_ws_port = 0
    subscription_mocked = False
    connection_closed = False
    actionError_received = False

    def __init__(self, reporting: enna.core.reporting.server_junit, *args, **kwargs) -> None:
        super().__init__(reporting, *args, **kwargs)
        self._reporting._report_path.wait_for_value
        self.test: TestBase = None
        # clean up viwi server process and stop capture
        self._execute_postcondition_after_crash = True
        self.steps = {}

    def __setup_viwi_server(self):
        yield

    def __reset_ecu(self, *args, **kwargs):
        yield

    def _precondition(self) -> bool:
        try:
            report_base_path =  os.path.dirname(self._reporting.report_path.value)
            report_path = os.path.join(report_base_path, os.path.basename(inspect.getfile(self.__class__))[:-3])
            os.makedirs(report_path, exist_ok=True)
            self.test = self.test_factory(
                name = self.name,
                report_base_path = report_path, 
                logging_adapter=self.logging_adapter, 
                esotrace_filename=os.path.splitext(os.path.basename(inspect.getfile(self.__class__)))[0],
                esotrace_port=21002,
                esotrace_channels="traceserverIVI. channel rsi_gatewayIVI.RUDI.RUNTIME + channel rsi_gatewayIVI.RUDI.GATEWAY + channel rsi_gatewayIVI.RSI.GATEWAY + channel rsi_gatewayIVI.FW + channel rudi_registryIVI.RUDI.RUNTIME + channel rudi_registryIVI.RUDI.REGISTRY + channel rudi_registryIVI.FW"
            )

            if not getattr(self, 'setup_viwi_server', None):
                self.test.setup_viwi_server = self.__setup_viwi_server
            
            self.test.report_path = self.test.report_base_path
            self.test.setUp()
            return True
        
        except Exception as e:
            self.test.logger.error(f'FAILED - {e}')
            self.test.logger.exception(e)
            return False
        finally:
            self._reporting.start_testgroup(self.name)

    def _action(self, *args) -> bool:
        logger = self.test.logger.getChild('_action')
        try:        
            # Disable IVI firewall
            self.disable_ivi_firewall()
            # Start esotrace capture
            self.start_esotrace_capture()
            # Start WS server
            result = self.simulate_ws_server()
            if result:
                # Register first client
                result = self.register_client_with_PUT_Request(service=self.viwi_service)
                if result:
                    time.sleep(5)
                    # # Mock request
                    # self.mocking_websocket = self.mock_websocket_request()
                    if self.subscription_mocked:
                        self.subscription_mocked = False
                        # Check first actionRequest
                        # result, self.request_id = self.check_actionRequest_on_esotrace()
                        # if result and self.request_id > 0:
                        #     self.test.logger.info(f"Request mocked, RequestId={self.request_id}")
                        #     if result:
                        #         self._reporting.add_test_result_pass(self.name, 'SUCCESS')
                        #         logger.info('[PASSED] execution was successful')
                    self.evt.set()
                    # self.mocking_websocket.join(timeout=5)
                self.stop_ws_server()
            self.stop_esotrace_capture()
            
            if self. location != "":
                self.delete_registered_client(location=self.location)
            
            #Reporting
            if not result:
                self._reporting.add_test_result_ta_error(self.name, 'FAILED')
                logger.info('[FAILED] execution failed')
        except Exception as e:
            logger.error(f'[FAILED] execution threw an error - {e}')
            logger.exception(e)
            self._reporting.add_test_result_ta_error(self.name, str(e))
            result = False
            self.stop_ws_server()
        finally:
            self.cleanup_firewall()
    
    def _postcondition(self) -> bool:
        logger = self.test.logger.getChild('_postcondition')
        logger.setLevel(logging.DEBUG)
        logger.info('*' * 100)
        logger.info('_postcondition')
        logger.info('*' * 100)
        try:
            try:
                self.test.tearDown()
            except Exception as e:
                logger.error(f'was not able to teardown')
                logger.exception(e)
            return True
        except Exception as e:
            logger.error(f'FAILED - {e}')
            logger.exception(e)
            return False
        finally:
            self._reporting.end_testgroup()
    
    def disable_ivi_firewall(self):

        try:
            logging.info(f'Disabling IVI firewall')
            #Push The new rsi config to IVI
            self.adb_command = f'adb connect 172.16.250.248:5555 && adb root && adb remount'
            proc = subprocess.Popen(self.adb_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.test.logger.info(f'res {proc.communicate()}')
            proc.kill()
            self.adb_command = f'adb shell "ip6tables -j ACCEPT -I OUTPUT" && adb shell "ip6tables -j ACCEPT -I INPUT" && adb shell "ip6tables -j ACCEPT -I FORWARD"'
            proc = subprocess.Popen(self.adb_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.test.logger.info(f'res {proc.communicate()}')
            proc.kill()
            self._reporting.add_report_message_info(f'\n{"*" * 100}\nSUCCESS\nsuccessfully disabled IVI firewall\n{"*" * 100}\n')
            self.test.logger.info(f'\n{"*" * 100}\nSUCCESS\nsuccessfully disabled IVI firewall\n{"*" * 100}\n')
            self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', f'\nsuccessfully disabled IVI firewall')
        except Exception as e:
            self.test.logger.warn("Was not able to disable IVI firewall")
            self._reporting.add_report_message_info(f'\n{"*" * 100}\nFAILURE\nError disabling IVI firewall\n{"*" * 100}\n')
            self.test.logger.info(f'\n{"*" * 100}\nFAILURE\nFAILURE\nError disabling IVI firewall\n')
            self._reporting.add_test_result_ta_error(f'{self.name}.{inspect.stack()[0][3]}', f'FAILURE\nError disabling IVI firewall')
            self.test.logger.exception(e)

    def simulate_ws_server(self):
        try:
            self.sock = Sock(self.app)
            @self.sock.route('/')
            def echo(ws):
                # Keep the connection open
                while not self.evt.is_set():
                    try:
                        # Receive a message from the client with a timeout
                        message = ws.receive(timeout=1)
                    except Exception as e:
                        continue

                    if message != None:
                        self.test.logger.info(f"WS Server received message: {message}")

                        if '"subscribe"' in message and (self.viwi_resource + "/#") in message:
                            self.subscription_mocked = True
                            self._reporting.add_report_message_info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully received mocked websocket subscription\n{"*" * 100}\n')
                            self.test.logger.info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully received mocked websocket subscription\n{"*" * 100}\n')
                            self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', f'\nSuccessfully received mocked websocket subscription')
                            
                            data = json.loads(message)
                            # Assuming the UUID is in a field named 'uuid'
                            uuid = str(data.get('event')).split("#")[1]
                            
                            subscription_ack_data = {
                                "type": "subscribe",
                                "event": f"{self.viwi_resource}/#{uuid}",
                                "status": "ok"
                            }
                            initial_event_data = {
                                "data":[{"id":"49b7fe20-c300-0b00-0000-000000000000","name":"elementID0","uri":"/ElectricalParkingBrake/functionControls/49b7fe20-c300-0b00-0000-000000000000","elementId":0,"parkingBrakeState":{"id":"49b7fe20-c300-0b03-0000-000000000000","name":"elementID0","uri":"/ElectricalParkingBrake/switchIndications/49b7fe20-c300-0b03-0000-000000000000"},"parkingBrakeStateChangeRequest":{"id":"49b7fe20-c300-0b04-0000-000000000000","name":"elementID0","uri":"/ElectricalParkingBrake/switchControls/49b7fe20-c300-0b04-0000-000000000000"},"messageHint":"JustATestValue"}],
                                "type":"data",
                                "event":f"{self.viwi_resource}/#{uuid}",
                                "Content-Type":"application/json; charset=utf-8"
                            }

                            # Send the response back to the client
                            ws.send(json.dumps(subscription_ack_data))

                            # Send the initial event to the client
                            ws.send(json.dumps(initial_event_data))
                        
                               
                            self.test.logger.info("######## Autosubscribe to element ##########")
                            time.sleep(0.1)
                            subscription_ack_element_data = {
                                "type": "subscribe",
                                "event": f"{self.viwi_resource}/49b7fe20-c300-0b00-0000-000000000000/#{uuid}",
                                "status": "ok"
                            }

                            initial_event_element_data = {
                                "data":[{"id":"49b7fe20-c300-0b00-0000-000000000000","name":"elementID0","uri":"/ElectricalParkingBrake/functionControls/49b7fe20-c300-0b00-0000-000000000000","elementId":0,"parkingBrakeState":{"id":"49b7fe20-c300-0b03-0000-000000000000","name":"elementID0","uri":"/ElectricalParkingBrake/switchIndications/49b7fe20-c300-0b03-0000-000000000000"},"parkingBrakeStateChangeRequest":{"id":"49b7fe20-c300-0b04-0000-000000000000","name":"elementID0","uri":"/ElectricalParkingBrake/switchControls/49b7fe20-c300-0b04-0000-000000000000"},"messageHint":"JustATestValue"}],
                                "type":"data",
                                "status": "ok",
                                "event":f"{self.viwi_resource}/49b7fe20-c300-0b00-0000-000000000000#{uuid}"
                                }

                            # Autosubscribe to element element
                            ws.send(json.dumps(subscription_ack_element_data))

                            # Send the initial event to the client for element
                            ws.send(json.dumps(initial_event_element_data))
                ws.close(1000)

            self.server_thread = threading.Thread(target=self.start_ws_server, daemon=True)
            self.server_thread.start()
            self._reporting.add_report_message_info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully started websocket and http server\n{"*" * 100}\n')
            self.test.logger.info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully started websocket and http server\n{"*" * 100}\n')
            self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', f'\nSuccessfully started websocket and http server')
            return True
        except Exception as e:
            self.test.logger.warn(5*'*'+'failed to start server for simulation'+ 5*'*')
            self.test.logger.error(f'Server simulation failed: {e}')
            self._reporting.add_report_message_info(f'\n{"*" * 100}\nFAILURE\nError starting Websocket and HTTP server\n{"*" * 100}\n')
            self.test.logger.info(f'\n{"*" * 100}\nFAILURE\nFAILURE\nError starting Websocket and HTTP server\n')
            self._reporting.add_test_result_ta_error(f'{self.name}.{inspect.stack()[0][3]}', f'FAILURE\nError starting Websocket and HTTP server')
            return False

    def start_ws_server(self):
        try:
            self.test.logger.info(f'Starting websocket server')
            self.sock.init_app(app=self.app)
            self.app.run(host=self.server_ip, port=self.server_port)
            time.sleep(2)
        except Exception as e:
            self.test.logger.error(f'Exception while starting websocket server: {e}')
    
    def stop_ws_server(self):
        try:
            self.test.logger.info(f'Stopping websocket server')
            self.evt.set()
            if self.server_thread:
                self.server_thread.join(timeout=2)
                self.test.logger.info(self.server_thread.is_alive)
                serverInstance = flaskServer.get(timeout=1)
                serverInstance.shutdown()
            return True
        except Exception as e:
            self.test.logger.warn(5*'*'+'failed to stop websocket server'+ 5*'*')
            self.test.logger.error(f'Websocket Server stopping failed: {e}')
            return False
    
    def register_client_with_PUT_Request(self, service:str):
        try:
            # Register service with PUT
            put_request_payload = {
                    'port': self.server_port,
                    'http_uri': f"http://[{self.server_ip}]:{self.server_port}/{service}"
                 }
            res = requests.put(f'http://[{self.host}]:{self.port}/{service}', json=put_request_payload, timeout=15)
            self.test.logger.info(f"Response is received for the PUT request : {res}")

             # Evaluate response and store the location
            if res.status_code == 201 or res.status_code == 409:
                if res.status_code == 201:
                    self.location = res.headers['Location']
                    self._reporting.add_report_message_info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully registered client on ViWi service {service}\n{"*" * 100}\n')
                    self.test.logger.info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully registered client on ViWi service {service}\n{"*" * 100}\n')
                    self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', f'\nSuccessfully registered client on ViWi service {service}')
                try:
                    cmd = f'java -jar jtracecmd.jar -H 172.16.250.248 -p 21005 -P traceserverIVI. channel rsi_gatewaySYS.rudi.client.{service} trace'
                    self.test.logger.info(f'performing following command to write loglevels: {cmd}')
                    resp = subprocess.check_output(cmd, shell=True, cwd='/home/jschaeferling/esoTraceTools-4.3.6/tools')
                except Exception as e:
                    logging.warn(F'Was not able to set levels, cannot guarantee results !! {e}')
            
                try:
                    cmd = f'java -jar jtracecmd.jar -H 172.16.250.248 -p 21005 -P traceserverIVI. channel rsi_gatewaySYS.rudi.service.{service} trace'
                    self.test.logger.info(f'performing following command to write loglevels: {cmd}')
                    resp = subprocess.check_output(cmd, shell=True, cwd='/home/jschaeferling/esoTraceTools-4.3.6/tools')
                except Exception as e:
                    logging.warn(F'Was not able to set levels, cannot guarantee results !! {e}')
                return True
            else:
                self._reporting.add_report_message_info(f'\n{"*" * 100}\nFAILURE\nError registering client on ViWi service {service}\n{"*" * 100}\n')
                self.test.logger.info(f'\n{"*" * 100}\nFAILURE\nError registering client on ViWi service {service}\n')
                self._reporting.add_test_result_ta_error(f'{self.name}.{inspect.stack()[0][3]}', f'FAILURE\nError registering client on ViWi service {service}')
                return False
                        
        except requests.HTTPError as e:
                self.test.logger.warn(f"Exception by registering client using PUT request: {e}")
                self._reporting.add_report_message_info(f'\n{"*" * 100}\nFAILURE\nError registering client on ViWi service {service}\n{"*" * 100}\n')
                self.test.logger.info(f'\n{"*" * 100}\nFAILURE\nError registering client on ViWi service {service}\n')
                self._reporting.add_test_result_ta_error(f'{self.name}.{inspect.stack()[0][3]}', f'FAILURE\nError registering client on ViWi service {service}')
                return False
        
    def websocket_connect(self):
        try:
            # Connect
            socket = websocket.create_connection(f"ws://[{self.host}]:{self.port}", timeout=5)

            # Send subscription request
            subscription_data = {
                "type": "subscribe",
                "event": f"{self.viwi_resource}"
            }
            if socket:
                if self.first_ws_port == 0:
                    self.first_ws_port = socket.sock.getsockname()[1]
                    current_socket_port = self.first_ws_port
                
                socket.send(json.dumps(subscription_data))
                time.sleep(0.5)
                self._reporting.add_report_message_info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully mocked Websocket subscription on resource {self.viwi_resource}\n{"*" * 100}\n')
                self.test.logger.info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully mocked Websocket subscription on resource {self.viwi_resource}\n{"*" * 100}\n')
                self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', f'\nSuccessfully mocked Websocket subscription on resource {self.viwi_resource}')
                while not self.evt.is_set():
                    try:
                        socket.settimeout(1)
                        data = socket.recv()
                        if data:
                            self.test.logger.info(f"Received data through socket: {data}")
                            if f'"event":"{self.viwi_resource}"' in data and '"code":502' in data:
                                self.connection_closed = True
                    except websocket.WebSocketTimeoutException:
                        continue
            else:
                self._reporting.add_report_message_info(f'\n{"*" * 100}\nFAILURE\nError mocking second client websocket request\n{"*" * 100}\n')
                self.test.logger.info(f'\n{"*" * 100}\nFAILURE\nFAILURE\nError mocking second client websocket request\n')
                self._reporting.add_test_result_ta_error(f'{self.name}.{inspect.stack()[0][3]}', f'FAILURE\nError mocking second client websocket request')   
                return False, 0
        except Exception as e:
                self.test.logger.warn(f"Exception by websocket_connect: {e}")
                return False, 0
    
    def mock_websocket_request(self):
        try:
            websocket_thread = threading.Thread(target=self.websocket_connect)
            websocket_thread.start()
            time.sleep(2)
            return websocket_thread
        except Exception as e:
                self.test.logger.warn(f"Exception by mocking websocket request: {e}")
                return False, 0

    def delete_registered_client(self, location):
        try:
            res = requests.delete(location)
            self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', 'successfully deleted the created client')
            return res
        except Exception as e:
            self.test.logger.error(f'Delete request failed: {e}')
            return None
        

    def start_esotrace_capture(self):
        #Enna Server Regisery for msg search in esotraces
        try:
            self.ServerRegistry = Server('ivi')
            self.ServerRegistry.connect()
            self.ServerRegistry.wait_for_online()
            self.ServerRegistry.register('esotrace_message', self.on_esotrace_message)
            self._reporting.add_report_message_info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully started esotrace capture\n{"*" * 100}\n')
            self.test.logger.info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully started esotrace capture\n{"*" * 100}\n')
            self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', f'\nSuccessfully started esotrace capture')
        except Exception as e:
            self.test.logger.error(f'enable to start capturing esotraces:{e}')
            self._reporting.add_report_message_info(f'\n{"*" * 100}\nFAILURE\nError starting esotrace capture\n{"*" * 100}\n')
            self.test.logger.info(f'\n{"*" * 100}\nFAILURE\nError starting esotrace capture\n')
            self._reporting.add_test_result_ta_error(f'{self.name}.{inspect.stack()[0][3]}', f'FAILURE\nError starting esotrace capture')

    
    def stop_esotrace_capture(self):
        # Clean up resources if needed
        self.ServerRegistry.disconnect()

    
    def on_esotrace_message(self, msg: 'enna.core.interfaces.Data'):
        if not self.eso_queue_evt.is_set():
            # Filter and process ESOTRACE messages here
            if (f'{self.viwi_service}' in str(msg.value["message_data"])):
                if 'actionRequest' in str(msg.value["message_data"]):
                    self.test.logger.info(f'##### Esotrace actionRequest message captured: {msg}')
                    self.esotrace_actionrequest_queue.put(msg)
                elif 'actionError' in str(msg.value["message_data"]) and '"statusCode":502' in str(msg.value["message_data"]):
                    self.test.logger.info(f'##### Esotrace actionError message captured: {msg}')
                    self.actionError_received = True
                
    
    def check_actionRequest_on_esotrace(self):
        try:
            msg_is_found= False
            while self.esotrace_actionrequest_queue.qsize != 0:
                msg = self.esotrace_actionrequest_queue.get()
                if '"requestId"' in str(msg.value["message_data"]):
                    msg_data = str(msg.value["message_data"])
                    msg_split = msg_data.split(sep=",")
                    request_id = int(next((e.split(sep=":"))[1] for e in msg_split if 'requestId' in e))
                    msg_is_found= True
                    self._reporting.add_report_message_info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully check actionRequest on esotrace\n{"*" * 100}\n')
                    self.test.logger.info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully check actionRequest on esotrace\n{"*" * 100}\n')
                    self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', f'\nSuccessfully check actionRequest on esotrace')
                    break
            if not msg_is_found:
                self._reporting.add_report_message_info(f'\n{"*" * 100}\nFAILURE\nError checking actionRequest on esotrace\n{"*" * 100}\n')
                self.test.logger.info(f'\n{"*" * 100}\nFAILURE\nError checking actionRequest on esotrace\n')
                self._reporting.add_test_result_ta_error(f'{self.name}.{inspect.stack()[0][3]}', f'FAILURE\nError checking actionRequest on esotrace')
            return msg_is_found, request_id
        except Exception as e:
            self.test.logger.error(f'Error checking actionRequest message in esotraces:{e}')
            self._reporting.add_report_message_info(f'\n{"*" * 100}\nFAILURE\nError checking actionRequest on esotrace\n{"*" * 100}\n')
            self.test.logger.info(f'\n{"*" * 100}\nFAILURE\nError checking actionRequest on esotrace\n')
            self._reporting.add_test_result_ta_error(f'{self.name}.{inspect.stack()[0][3]}', f'FAILURE\nError checking actionRequest on esotrace')
            return False, 0

    def cleanup_firewall(self):

        try:
            logging.info(f'Cleanup firewall configuration')
            #Push The new rsi config to IVI
            self.adb_command = 'sudo ip6tables -F'
            proc = subprocess.Popen(self.adb_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.test.logger.info(f'res {proc.communicate()}')
            proc.kill()
        except Exception as e:
            self.test.logger.warn("Was not able to cleanup firewall configuration")
            self.test.logger.exception(e)
