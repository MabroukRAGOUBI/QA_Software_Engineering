import socket
from socketserver import BaseRequestHandler, TCPServer
import threading
import typing
import queue
import enna.core.reporting.interface
if typing.TYPE_CHECKING:
    import enna.core.reporting.interface

class HttpServer(TCPServer):
    address_family = socket.AF_INET6
    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=False):
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        self.evt = threading.Event()
        self.server_thread: threading.Thread
        self.reporting : enna.core.reporting.interface.Interface
        self.requests_queue = queue.Queue()
    
    # def server_bind(self):
    #     self.socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    #     self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    #     self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
    #     self.socket.bind(self.server_address)

    # def server_activate(self):
    #     self.socket.listen(self.request_queue_size)

class HttpServerHDLR(BaseRequestHandler):
    def handle(self):
        self.server: HttpServer
        try:
            while not self.server.evt.is_set():
                # Receive the request data from the ECU
                request_data = self.request.recv(1024).strip()
                request_str = request_data.decode('utf-8') 
                if request_str not in  ['',None]:
                    self.server.requests_queue.put((self.client_address[1], request_str))
                    self.server.reporting.add_report_message_info(message=f'HTTP Server received request: {request_str}')
        except ConnectionResetError as e:
            self.server.reporting.add_report_message_system_error(f"ConnectionResetError: {e}")

    def send_response(self, response: bytes):
        self.request.sendall(response)

def create_http_server(server_ip:str, server_port:int, service:str, handler: BaseRequestHandler, reporting : enna.core.reporting.interface.Interface): 
    try:
        server = HttpServer((server_ip, server_port), handler)
        server.service = service
        server.reporting = reporting
        server.server_bind()
        server.server_activate()
        return server
    except Exception as e:
        server.reporting.add_report_message_system_error(5*'*'+f'failed to start server for simulation: {e}' + 5*'*')

def start_http_server(server: HttpServer):
    try:
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()
        server.server_thread = server_thread
    except Exception as e:
        server.reporting.add_report_message_system_error(5*'*'+ f'failed to start server: {e}' + 5*'*')

def stop_http_server(server: HttpServer):
    try:
        server.evt.set()
        server.server_close()
        server.shutdown()
        server.server_thread.join(timeout=2)
        server.reporting.add_report_message_info(f'server thread is alive : {server.server_thread.is_alive()}')
        if server.server_thread.is_alive():
            server.server_thread._stop()
    except Exception as e:
        server.reporting.add_report_message_system_error(message = 5*'*'+ f'failed to stop server: {e}'+ 5*'*')

def send_http_server_response(server: HttpServer, response: bytes):
    try:
        server.RequestHandlerClass.send_response(response)
    except Exception as e:
        server.reporting.add_report_message_system_error(5*'*'+ f'failed to send server response: {e}' + 5*'*')

def get_next_http_server_request(server: HttpServer, timeout: int) -> tuple[int,str]:
    try:
        return server.requests_queue.get(timeout=timeout)
    except Exception as e:
        server.reporting.add_test_result_system_error(5*'*'+ f'failed to get server received request: {e}' + 5*'*')