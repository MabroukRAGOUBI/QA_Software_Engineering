import json
import queue
import threading
import time
import typing

import enna.core.reporting.interface
######################################################
# Monkey patching fot the Flask server to shut it down
import werkzeug.serving
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

if typing.TYPE_CHECKING:
    import enna.core.reporting.interface


class FlaskServer():
    def __init__(self, reporting: enna.core.reporting.interface.Interface, server_ip:str, server_port:int, http_url:str, websocket_url:str) -> None:
        self.evt = threading.Event()
        self.http_resp_evt = threading.Event()
        self.websocket_resp_evt = threading.Event()
        self.server_thread: threading.Thread
        self.reporting = reporting
        self.http_requests_queue = queue.Queue()
        self.websocket_requests_queue = queue.Queue()
        self.http_url = http_url
        self.websocket_url = websocket_url
        self.app = Flask(__name__)
        self.sock = None
        self.http_resp: dict[str, any] = {}
        self.websocket_resp_list = list()
        self.websocket_interval = 0
        self.server_ip = server_ip
        self.server_port = server_port
        
    def start_flask_server(self):
        try:
            self.sock = Sock(self.app)
            
            @self.app.route(self.http_url)
            def handle_data():
                if not self.evt.is_set():
                    self.reporting.add_report_message_info(f"Flask HTTP Server received request: {request}")
                    self.http_requests_queue.put(request.method + ' : '+ request.base_url)
                    self.http_resp_evt.wait(timeout=30)
                    return jsonify(self.http_resp)
            
            @self.sock.route(self.websocket_url)
            def echo(ws):
                while not self.evt.is_set():
                    try:
                        # Receive a message from the client with a timeout
                        message = ws.receive(timeout=1)
                    except Exception as e:
                        if "Connection closed" in str(e):
                            self.reporting.add_report_message_info(f"Client WS connection is closed: {e}")
                            self.evt.set()
                        else:
                            self.reporting.add_report_message_info(f"WS receive Exception: {e}")
                            continue

                    if message != None:
                        self.reporting.add_report_message_info(f"Flask Websocket Server received message: {message}")
                        self.websocket_requests_queue.put(message)

                    if self.websocket_resp_evt.is_set():
                        self.reporting.add_report_message_info(f'Flask Websocket Server sending frame: {self.websocket_resp_list}')
                        for resp in self.websocket_resp_list:
                            # Send the response back to the client
                            ws.send(json.dumps(resp))
                            if self.websocket_interval :
                                time.sleep(self.websocket_interval)
                        self.websocket_resp_list.clear()
                        self.websocket_resp_evt.clear()
                        
                ws.close(1000)

            self.server_thread = threading.Thread(target=self.simulate_flask_server, daemon=True)
            self.server_thread.start()
            self.reporting.add_report_message_info(f'\n{"*" * 100}\nSUCCESS\nSuccessfully started websocket and http server\n{"*" * 100}\n')
            return True
        except Exception as e:
            self.reporting.add_report_message_ta_error(5*'*'+'failed to start server for simulation'+ 5*'*')
            return False

    def simulate_flask_server(self):
        try:
            self.reporting.add_report_message_info(f'Starting websocket server')
            self.sock.init_app(app=self.app)
            self.app.run(host=self.server_ip, port=self.server_port)
            time.sleep(2)
        except Exception as e:
            self.reporting.add_report_message_ta_error(f'Exception while starting websocket server: {e}')
    
    def stop_flask_server(self):
        try:
            self.reporting.add_report_message_info(f'Stopping websocket server')
            self.evt.set()
            if self.server_thread:
                self.server_thread.join(timeout=2)
                self.reporting.add_report_message_info(f"Flask Server Thread state: {self.server_thread.is_alive}")
                serverInstance = flaskServer.get(timeout=1)
                serverInstance.shutdown()
            return True
        except Exception as e:
            self.reporting.add_report_message_ta_error(f'Websocket Server stopping failed: {e}')
            return False
    
    def get_next_server_http_request(self, timeout: int):
        try:
            return self.http_requests_queue.get(timeout=timeout)
        except Exception as e:
            self.reporting.add_report_message_ta_error(5*'*'+ f'failed to get next http server http request: {e}' + 5*'*')
            return False
    
    def send_server_http_response(self, response: dict[str,any]):
        try:
            self.http_resp = response
            self.http_resp_evt.set()
        except Exception as e:
            self.reporting.add_report_message_ta_error(5*'*'+ f'failed to send server response: {e}' + 5*'*')
            return False
        
    def get_next_received_websocket_packet(self, timeout:int) -> str:
        self.reporting.add_report_message_info("Get WebSocket next packet")
        try:
            return self.websocket_requests_queue.get(timeout=timeout)
        except Exception as e:
            self.reporting.add_report_message_ta_error(f'Get next received WebSocket packet error: {e}')

    def websocket_send(self, responses: list[dict[str,any]], inter_frames_time:int):
        # Append responses to server sending list
        for resp in responses:
            self.websocket_resp_list.append(resp)
        
        # Set sending event
        self.websocket_interval = inter_frames_time
        self.websocket_resp_evt.set()

def create_flask_server(reporting: enna.core.reporting.interface.Interface, server_ip:str, server_port:int, http_url:str="/", websocket_url:str="/"): 
    try:
        server = FlaskServer(server_ip=server_ip, server_port=server_port, reporting=reporting, http_url=http_url, websocket_url=websocket_url)
        return server
    except Exception as e:
        reporting.add_report_message_ta_error(5*'*'+'failed to start server for simulation'+ 5*'*')

def start_flask_server(server: FlaskServer):
    try:
        server.start_flask_server()
    except Exception as e:
        server.reporting.add_report_message_ta_error(5*'*'+'failed to start server'+ 5*'*')

def stop_flask_server(server: FlaskServer):
    try:
        server.stop_flask_server()
    except Exception as e:
        server.reporting.add_report_message_ta_error(5*'*'+'failed to stop server'+ 5*'*')

def get_next_flask_server_websocket_request(server: FlaskServer, timeout: int=2):
    try:
        return server.get_next_received_websocket_packet(timeout=timeout)
    except Exception as e:
        server.reporting.add_report_message_ta_error(5*'*'+ f'failed to get server received request: {e}' + 5*'*')

def send_ws_server_response(server: FlaskServer, responses: list[dict[str,any]], inter_frames_time:float=0):
    try:
        server.websocket_send(responses=responses, inter_frames_time=inter_frames_time)
    except Exception as e:
        server.reporting.add_report_message_ta_error(5*'*'+ f'failed to send server response: {e}' + 5*'*')

def send_flask_server_http_response(server: FlaskServer, response: dict[str,any]):
    try:
        server.send_server_http_response(response)
    except Exception as e:
        server.reporting(5*'*'+ f'failed to send server response: {e}' + 5*'*')

def get_next_flask_server_http_request(server: FlaskServer, timeout: int=2) -> str:
    try:
        return server.get_next_server_http_request(timeout)
    except Exception as e:
        server.reporting.add_report_message_ta_error(5*'*'+ f'failed to get server received request: {e}' + 5*'*')