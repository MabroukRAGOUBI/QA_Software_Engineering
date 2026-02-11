import logging
import subprocess
import os
import json
import inspect
import enna.core.time
import enna.core.config
import enna.core.interfaces.server
import enna.core.reporting.server_junit
import enna.core.component_system.decorators
import enna.core.interfaces.testing
import enna.core.interfaces.component
import queue
from enna.data_interfaces.esotrace.server_socket import Server
import requests
from hcp3.viwi.tests.smoke_tests.ivi_testbase import HCP3IVITestbase, TestBase
import requests.adapters
import websocket
from urllib.parse import urlparse
import time
import socket, threading, json
from socketserver import TCPServer, BaseRequestHandler
from hcp3.viwi.fixtures import SetupEsotraceRecorder
import andisdk

@enna.core.component_system.decorators.RequireComponent('enna.core.reporting')
class ViWiHttpError400ivi(enna.core.interfaces.testing.Stimulation):
    name = os.path.splitext(os.path.basename(__file__))[0]
    test_factory: type[TestBase] = HCP3IVITestbase
    host = 'fd53:7cb8:383:3::130'
    port = 29796
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
    location = ""
    TIMEOUT_PARAMETER = 2
    ServerRegistry : Server
    esotrace_queue = queue.Queue()
    http_error_msg ='400 Bad Request'
    server : TCPServer
    server_thread: threading.Thread
    http_request = requests.Request(method='GET', url='http://[fd53:7cb8:383:3::3aa]:29797/WiperUI/')

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
            import time
            time.sleep(5)

            debug_channel = andisdk.andi.create_channel(os.environ.get('diagnosis_adapter', 'enp13s0f3'))
            self.debug_channel = andisdk.ChannelEthernet(debug_channel)
            self.debug_channel.start_record(os.path.join(report_path, 'debugging.pcapng'))
            self.ServerRegisterSetUp()

            return True
        
        except Exception as e:
            self.test.logger.error(f'FAILED - {e}')
            self.test.logger.exception(e)
            return False
        finally:
            self._reporting.start_testgroup(self.name)

    def _action(self, *args) -> bool:
        logger = self.test.logger.getChild('_action')
        self.simulate_server()
        
        try:
            self.trigger_request(self.http_request)
            time.sleep(2)
            self.send_delete_request(self.location)
            time.sleep(2)
            self.EndServerRegister()
            time.sleep(2)
            result = self.Server_find_action_error_message()
            if result:
                self._reporting.add_test_result_pass(self.name, 'SUCCESS')
                logger.info('[PASSED] execution was successful')
            else:
                self._reporting.add_test_result_ta_error(self.name, 'FAILED')
                logger.info('[FAILED] execution failed')
        except Exception as e:
            logger.error(f'[FAILED] execution threw an error - {e}')
            logger.exception(e)
            self._reporting.add_test_result_ta_error(self.name, str(e))
            return False
        return True
    
    def _postcondition(self) -> bool:
        logger = self.test.logger.getChild('_postcondition')
        logger.setLevel(logging.DEBUG)
        logger.info('*' * 100)
        logger.info('_postcondition')
        logger.info('*' * 100)
        try:
            try:
                self.server.server_close()
                self.server.shutdown()
                self.server_thread.join(timeout=2)
                print(self.server_thread.is_alive)
                if self.server_thread.is_alive():
                    self.server_thread._stop()
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
            self.debug_channel.stop_record()
            
    def simulate_server(self):
        try:
            self.server = TCPServerV6(('fd53:7cb8:383:3::3aa', 29797), bind_and_activate=False,RequestHandlerClass=HDLR)
            self.server.error_msg = self.http_error_msg
            self.server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.server_bind()
            self.server.server_activate()
            self.server_thread = threading.Thread(target=self.server.serve_forever)
            self.server_thread.start()
            self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', 'successfully started the viwi responder')
        except Exception as e:
            print(5*'*'+'failed to start server for simulation'+ 5*'*')
            self.test.logger.error(f'Server simulation failed: {e}')

    def trigger_request(self, request: requests.Request, debug_host='172.16.250.248', debug_port=14712):

            try:
                url = urlparse(request.url)
                ip, port = url.netloc.split(']:')
                ip = ip[1:]
                put_request_payload = {
                    'port': int(port),
                    'http_uri': f"http://[{ip}]:{port}/{url.path.split('/')[1]}",
                    'ws_uri': f"ws://[{ip}]:{port}/{url.path.split('/')[1]}"
                 }
                res = requests.put(f'http://{debug_host}:{debug_port}/{url.path.split("/")[1]}', json=put_request_payload)

            except requests.HTTPError as e:
                raise e
            # Evaluate response and store the location
            if res.status_code == 201:
                self.location = res.headers['Location']
                try: 
                    print("############### WIPERUI LOGLEVEL SET TO TRACE BEGIN ###########")
                    cmd = 'java -jar jtracecmd.jar -H 172.16.250.248 -p 21002 -P traceserverIVI. channel rsi_gatewayIVI.rudi.client.WiperUI trace'
                    self.test.logger.info(f'performing following command to write loglevels: {cmd}')
                    resp = subprocess.check_output(cmd, shell=True, cwd='/home/jschaeferling/esoTraceTools-4.3.6/tools')
                    print("############### WIPERUI LOGLEVEL SET TO TRACE END ###########")

                except Exception as e:
                    logging.error(F'Was not able to set levels, cannot guarantee results !! {e}')

            request.url = f'{url.scheme}://{debug_host}:{debug_port}{url.path}'
            if url.scheme == 'ws':
                connection = websocket.create_connection(request.url)
                connection.send(json.dumps({'type': 'subscribe', 'event': request.url}))
                return connection
            else:
                print(request.url)
                session = requests.Session()
                prep = session.prepare_request(request=request)
                returned_response=session.send(prep)
                print(f'the ECU response is: {returned_response}')
                self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', 'successfully mocked request and simulated response')
                return returned_response
        
    def send_delete_request(self, location):
        try:
            res = requests.delete(location)
            self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', 'successfully deleted the created client')
            return res
        except Exception as e:
            self.test.logger.error(f'Delete request failed: {e}')
            return None
        

    def ServerRegisterSetUp(self):
        #Enna Server Regisery for msg search in esotraces
        try:
            self.ServerRegistry = Server('ivi')
            self.ServerRegistry.connect()
            self.ServerRegistry.wait_for_online()
            self.ServerRegistry.register('esotrace_message', self.on_esotrace_message)
        except Exception as e:
            self.test.logger.error(f'enable to start capturing esotraces:{e}')

    def EndServerRegister(self):
        # Clean up resources if needed
        self.ServerRegistry.disconnect()

    def on_esotrace_message(self, msg: 'enna.core.interfaces.Data'):
        # Filter and process ESOTRACE messages here
        if ('rudi.client.WiperUI' in str(msg.value['channel_name']) or 'rudi.service.WiperUI' in str(msg.value['channel_name'])) and '"type":"actionError"' in str(msg.value["message_data"]):
            self.esotrace_queue.put(msg)
    
    def Server_find_action_error_message(self):
        try:
            msg_is_found= False
            while self.esotrace_queue.qsize != 0:
                msg = self.esotrace_queue.get(timeout=5)
                if f'"statusCode":{self.http_error_msg.split()[0]}' in str(msg.value["message_data"]):
                    self.test.logger.info(f'WiperUI error action Message: {msg}')
                    msg_is_found= True
                    self._reporting.add_test_result_pass(f'{self.name}.{inspect.stack()[0][3]}', 'successfully found the esotrace message')
                    break   
                    
            return msg_is_found
        except Exception as e:
            raise e


class TCPServerV6(TCPServer):
    address_family = socket.AF_INET6
    error_msg :str

class HDLR(BaseRequestHandler):
  
    def handle(self):
     
        # Receive the request data from the ECU
        request_data = self.request.recv(1024).strip()
        request_str = request_data.decode('utf-8')  
        print(f'The client request is: {request_str}')
        error_msg=self.server.error_msg
        print(f'error msg to be sent:{error_msg}')

        if 'GET /WiperUI' in request_str:
            # Respond with http error msg for HTTP GET requests targeting "WiperUI"
            
            error_msg_to_byte = 'HTTP/1.1 ' + error_msg + ' \r\n'
            error_msg_to_byte= bytes(error_msg_to_byte, 'utf-8')
            response = error_msg_to_byte
            response += b'Connection: keep-alive\r\n\r\n'
            self.request.sendall(response)