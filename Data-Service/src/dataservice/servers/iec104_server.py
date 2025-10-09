import os
import time
import socket
from dotenv import load_dotenv
from ..core.datastore import DATA_STORE
from threading import Event
from ..core.mapping_store import IEC104_MAPPING

# Load environment variables
load_dotenv()

# Try to import c104, fall back to basic TCP server if not available
try:
    import c104
    C104_AVAILABLE = True
except ImportError:
    C104_AVAILABLE = False
    print("Warning: c104 library not available, using basic IEC104 simulation")

def _type_to_c104(type_str: str):
    if not C104_AVAILABLE:
        return type_str
        
    mapping = {
        'M_SP_NA_1': c104.Type.M_SP_NA_1,
        'M_ME_NA_1': c104.Type.M_ME_NA_1,
        'M_ME_NB_1': c104.Type.M_ME_NB_1,
        'M_ME_NC_1': c104.Type.M_ME_NC_1,
        'M_ME_NF_1': c104.Type.M_ME_NC_1,  # Fallback for floating point
    }
    return mapping.get(type_str, c104.Type.M_ME_NC_1)

def basic_iec104_server(host: str, port: int, stop_event: Event):
    """Basic IEC104 server simulation using TCP socket with proper IEC104 frame structure"""
    print(f"Starting basic IEC104 simulation on {host}:{port}")
    
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((host, port))
        server_socket.listen(5)
        server_socket.settimeout(1.0)  # Non-blocking accept
        
        print(f"✓ IEC 60870-5-104 server started on {host}:{port}")
        
        clients = []
        last_send_time = 0
        
        while not stop_event.is_set():
            try:
                # Accept new connections
                try:
                    client_socket, addr = server_socket.accept()
                    print(f"IEC104 client connected from {addr}")
                    client_socket.settimeout(1.0)
                    clients.append(client_socket)
                    
                    # Send STARTDT act (IEC104 connection initiation)
                    startdt_act = bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00])
                    client_socket.send(startdt_act)
                    print(f"Sent STARTDT act to {addr}")
                    
                except socket.timeout:
                    pass
                except Exception as e:
                    print(f"IEC104 accept error: {e}")
                
                # Send data to connected clients (proper IEC104 ASDU frames)
                current_time = time.time()
                if clients and (current_time - last_send_time) >= 2.0:  # Send every 2 seconds
                    maps = IEC104_MAPPING.all()
                    if maps:  # Only send if we have mappings
                        for data_id, meta in maps.items():
                            key = str(meta['key'])
                            ioa = int(meta['ioa'])
                            value = DATA_STORE.read(key)
                            
                            if value is not None:
                                # Create simplified IEC104 ASDU frame
                                # Format: [Length][Type][SQ][COT][ORG][ASDU_ADDR][IOA][Value][Timestamp]
                                asdu_type = 0x09  # M_ME_NC_1 (measured value, short float)
                                cot = 0x03  # Spontaneous
                                org = 0x00
                                asdu_addr = 0x0001
                                
                                # Convert value to IEEE 754 float bytes
                                import struct
                                value_bytes = struct.pack('<f', float(value))
                                
                                # Build ASDU
                                asdu_data = bytes([asdu_type, 0x01, cot, org])  # Type, SQ, COT, ORG
                                asdu_data += struct.pack('<H', asdu_addr)  # ASDU address
                                asdu_data += struct.pack('<I', ioa)  # IOA (3 bytes)
                                asdu_data += value_bytes  # Value
                                asdu_data += bytes(3)  # Timestamp (simplified)
                                
                                # Build complete frame: [Length][ASDU]
                                frame_length = len(asdu_data)
                                frame = bytes([0x68, frame_length]) + asdu_data
                                
                                # Send to all connected clients
                                connected_clients = []
                                for client in clients:
                                    try:
                                        client.send(frame)
                                        connected_clients.append(client)
                                    except Exception as e:
                                        print(f"IEC104 send error to client: {e}")
                                        try:
                                            client.close()
                                        except Exception:
                                            pass
                                clients = connected_clients
                    
                    last_send_time = current_time
                
                time.sleep(0.1)  # Shorter sleep for better responsiveness
                
            except Exception as e:
                print(f"IEC104 basic server error: {e}")
                time.sleep(1)
                
    except Exception as e:
        print(f"IEC104 server startup error: {e}")
    finally:
        # Cleanup
        for client in clients:
            try:
                client.close()
            except Exception:
                pass
        try:
            server_socket.close()
        except Exception:
            pass

def iec104_server_thread(stop_event: Event):
    host = os.getenv('SERVER_HOST', '0.0.0.0')
    port = int(os.getenv('IEC104_PORT', '2404'))

    if not C104_AVAILABLE:
        basic_iec104_server(host, port, stop_event)
        return

    server = None
    try:
        # Check if port is available
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            test_socket.bind((host, port))
            test_socket.close()
        except OSError as e:
            print(f"IEC104 port {port} not available: {e}")
            print("Trying alternative port 2405...")
            port = 2405

        server = c104.Server(ip=host, port=port)
        station = server.add_station(common_address=1)

        # cache: key -> (point, type)
        point_cache = {}

        server.start()
        print(f"✓ IEC 60870-5-104 server started on {host}:{port}")

        while not stop_event.is_set():
            try:
                # Ensure points exist for mappings
                maps = IEC104_MAPPING.all()
                for data_id, meta in maps.items():
                    key = str(meta['key'])
                    ioa = int(meta['ioa'])
                    type_id = _type_to_c104(str(meta['type']))
                    if data_id not in point_cache:
                        try:
                            pt = station.add_point(ioa, type_id)
                            point_cache[data_id] = (pt, type_id, key)
                            print(f"IEC104 created point: {key} at IOA {ioa}")
                        except Exception as e:
                            print(f"IEC104 add_point error for {key}/{ioa}: {e}")

                # Update and transmit values
                for data_id, (pt, type_id, key) in list(point_cache.items()):
                    try:
                        value = DATA_STORE.read(key)
                        if value is None:
                            continue
                            
                        if type_id == c104.Type.M_SP_NA_1:
                            # For single point information - use Byte32 directly
                            pt.value = c104.Byte32(bool(value))
                        elif type_id == c104.Type.M_ME_NA_1:
                            # For measured normalized values - use NormalizedFloat directly
                            normalized_val = float(value) / 32767.0  # Normalize to -1.0 to 1.0 range
                            pt.value = c104.NormalizedFloat(normalized_val)
                        elif type_id == c104.Type.M_ME_NB_1:
                            # For measured scaled values - use Int16 directly
                            pt.value = c104.Int16(int(float(value)))
                        else:
                            # For other values - use Int16 as fallback
                            pt.value = c104.Int16(int(float(value)))
                        pt.transmit(cause=c104.Cot.SPONTANEOUS)
                    except Exception as e:
                        print(f"IEC104 update error for {key}: {e}")

                time.sleep(1)
            except Exception as e:
                print(f"IEC104 main loop error: {e}")
                # If c104 server has issues, fall back to basic server
                if "c104" in str(e).lower() or "server" in str(e).lower():
                    print("IEC104 c104 server error, falling back to basic server...")
                    basic_iec104_server(host, port, stop_event)
                    return
                time.sleep(1)

    except Exception as e:
        print(f"IEC104 server error: {e}")
        # Fall back to basic server
        print("Falling back to basic IEC104 simulation...")
        basic_iec104_server(host, port, stop_event)
    finally:
        try:
            if server and server.is_running():
                server.stop()
        except Exception:
            pass
        print("IEC 60870-5-104 server stopped")
