import asyncio
import threading
import time
import typing
import websockets
import enna.core.reporting.interface

if typing.TYPE_CHECKING:
    import enna.core.reporting.interface

class WebsocketServer():

    def __init__(self, server_ip:str, server_port:int, reporting: enna.core.reporting.interface.Interface) -> None:
        self.host = server_ip
        self.port = server_port
        self.event_loop = None
        self.ws_server_thread = None
        self.stop_event = threading.Event()
        self.websocket = None
        self.reporting = reporting

    def start_websocket_server(self):
        self.ws_server_thread = threading.Thread(target=self.run_server)
        self.ws_server_thread.start()

    def run_server(self):
        try:
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)
            self.server = websockets.serve(self.handle_websocket_requests, self.host, self.port)
            self.event_loop.run_until_complete(self.server)
            self.event_loop.run_forever()
            
        except Exception as e:
            self.reporting.add_report_message_ta_error(f'WebSocket Server simulation failed: {e}')
    
    async def handle_websocket_requests(self, websocket:websockets.WebSocketServerProtocol, path):
        self.reporting.add_report_message_info(f"Received WebSocket connection from {websocket.remote_address}")
        try:
            if self.websocket is None:
                self.websocket = websocket
            
            while not self.stop_event.is_set():
                await asyncio.sleep(1)

            await asyncio.wait_for(websocket.close(), timeout=5)
 
        except websockets.exceptions.ConnectionClosedError as e:
            self.reporting.add_report_message_ta_error(f"WebSocket connection with DUT at {websocket.remote_address} closed due to:{e}")
        except asyncio.TimeoutError:
            self.reporting.add_report_message_ta_error(f"Timeout while closing WebSocket connection !!")
        except Exception as e:
            self.reporting.add_report_message_ta_error(f'WebSocket connection handling error: {e}')

    def websocket_receive(self, rcv_timeout:int=2):
        return asyncio.run_coroutine_threadsafe(self.get_next_received_websocket_packet(rcv_timeout=rcv_timeout), self.event_loop)
        
    async def get_next_received_websocket_packet(self, rcv_timeout:int) -> str:
        self.reporting.add_report_message_info(f"Get WebSocket next packet from {self.websocket.remote_address}")
        try:
            message = await asyncio.wait_for(self.websocket.recv(), timeout=rcv_timeout)
            self.reporting.add_report_message_info(f"Received WebSocket packet from DUT: {message}")
            return message
        except asyncio.TimeoutError:
            self.reporting.add_report_message_ta_error(f"Websocket receive Timeout: Did not receive any WebSocket packet during the last {rcv_timeout} seconds !!")
        except Exception as e:
            self.reporting.add_report_message_ta_error(f'Get next received WebSocket packet error: {e}')

    def websocket_send(self, req_data:str):
        asyncio.run_coroutine_threadsafe(self.send_websocket_packet(req_data=req_data), self.event_loop)

    async def send_websocket_packet(self, req_data:str):
        self.reporting.add_report_message_info(f"Send WebSocket packet {req_data} from {self.websocket.remote_address}")
        try:
            await self.websocket.send(req_data)
        except Exception as e:
            self.reporting.add_report_message_ta_error(f'Sending WebSocket packet error: {e}')

    def stop_ws_server(self):
        try:
            self.stop_event.set()
            self.server.ws_server.server.close()
            self.server.ws_server.close()
            self.event_loop.call_soon_threadsafe(self.event_loop.stop)
            self.ws_server_thread.join(timeout=2)
            return True
        except Exception as e:
            self.reporting.add_report_message_ta_error(f'Websocket Server stopping failed: {e}')
            return False

def create_websocket_server(server_ip:str, server_port:int, reporting: enna.core.reporting.interface.Interface): 
    try:
        server = WebsocketServer(server_ip=server_ip, server_port=server_port, reporting=reporting)
        return server
    except Exception as e:
        reporting.add_report_message_ta_error(5*'*'+'failed to start server for simulation'+ 5*'*')

def start_websocket_server(server: WebsocketServer):
    try:
        server.start_websocket_server()
    except Exception as e:
        server.reporting.add_report_message_ta_error(5*'*'+'failed to start server'+ 5*'*')

def stop_websocket_server(server: WebsocketServer):
    try:
        server.stop_ws_server()
    except Exception as e:
        server.reporting.add_report_message_ta_error(5*'*'+'failed to stop server'+ 5*'*')

def get_next_websocket_server_request(server: WebsocketServer, timeout: int=2) -> typing.Optional[str]:
    try:
        return server.websocket_receive(rcv_timeout=timeout).result(timeout=timeout)
    except Exception as e:
        server.reporting.add_report_message_ta_error(5*'*'+ f'failed to get server received request: {e}' + 5*'*')

def send_websocket_server_response(server: WebsocketServer, response: str):
    try:
        server.websocket_send(response)
    except Exception as e:
        server.reporting.add_report_message_ta_error(5*'*'+ f'failed to send server response: {e}' + 5*'*')