import os
import asyncio
from dotenv import load_dotenv
from asyncua import Server, ua
from ..core.datastore import DATA_STORE
from ..core.mapping_store import OPCUA_MAPPING
from threading import Event

# Load environment variables
load_dotenv()

def coerce_value_for_opcua(value):
    """Coerce values to appropriate OPC-UA types"""
    if value is None:
        return 0.0
    elif isinstance(value, bool):
        return bool(value)  # Keep as boolean
    elif isinstance(value, int):
        return int(value)  # Keep as int32
    elif isinstance(value, float):
        return float(value)  # Keep as double
    elif isinstance(value, str):
        try:
            # Try to parse as number first
            if '.' in value:
                return float(value)
            else:
                return int(value)
        except ValueError:
            return str(value)  # Keep as string
    else:
        return str(value)  # Convert to string as fallback

def node_id_to_string(node_id):
    """Convert asyncua NodeId to string representation"""
    if node_id.nodeidtype == ua.NodeIdType.FourByte:
        return f"ns={node_id.namespaceidx};i={node_id.identifier}"
    elif node_id.nodeidtype == ua.NodeIdType.String:
        return f"ns={node_id.namespaceidx};s={node_id.identifier}"
    elif node_id.nodeidtype == ua.NodeIdType.Guid:
        return f"ns={node_id.namespaceidx};g={node_id.identifier}"
    elif node_id.nodeidtype == ua.NodeIdType.ByteString:
        return f"ns={node_id.namespaceidx};b={node_id.identifier}"
    else:
        return str(node_id)

async def opcua_server_thread(stop_event: Event):
    host = os.getenv('SERVER_HOST', '0.0.0.0')
    port = int(os.getenv('OPCUA_PORT', '4840'))
    
    server = Server()
    await server.init()
    server.set_endpoint(f"opc.tcp://{host}:{port}")
    server.set_server_name("DataService OPC-UA Server")
    
    # Create namespace
    uri = "http://dataservice.gateway.io"
    idx = await server.register_namespace(uri)
    
    # Get Objects node
    objects = server.get_objects_node()
    
    # Create a folder for our data
    data_folder = await objects.add_folder(idx, "SensorData")
    
    # Variable cache by key
    key_to_var = {}
    key_to_type = {}
    
    print(f"OPC-UA server starting on {host}:{port}")
    print(f"Using namespace {idx}: {uri}")
    
    async with server:
        print(f"✓ OPC-UA server started successfully on {host}:{port}")
        
        # Main update loop
        while not stop_event.is_set():
            try:
                # Get all current data
                snapshot = DATA_STORE.snapshot()
                
                for key, value in snapshot.items():
                    # Create variable if it doesn't exist
                    if key not in key_to_var:
                        try:
                            # Auto-generate NodeId and create variable
                            coerced_value = coerce_value_for_opcua(value)
                            var = await data_folder.add_variable(idx, key, coerced_value)
                            await var.set_writable()
                            
                            # Get the auto-generated NodeId
                            actual_node_id = var.nodeid
                            node_id_str = node_id_to_string(actual_node_id)
                            
                            # Cache the variable
                            key_to_var[key] = var
                            key_to_type[key] = type(coerced_value)
                            
                            print(f"✓ Created OPC-UA variable: {key} -> {node_id_str} = {coerced_value}")
                            
                            # Update or create mapping with the actual NodeId
                            try:
                                # Get the data_id for this key
                                data_id = DATA_STORE.ensure_id(key)
                                
                                # Check if mapping already exists
                                existing_mapping = OPCUA_MAPPING.get_mapping(data_id)
                                if existing_mapping:
                                    # Update existing mapping with actual NodeId
                                    OPCUA_MAPPING.set_mapping(
                                        data_id, key, node_id_str,
                                        existing_mapping.get('browse_name', key),
                                        existing_mapping.get('display_name', key),
                                        existing_mapping.get('data_type', 'Float'),
                                        existing_mapping.get('value_rank', -1),
                                        existing_mapping.get('access_level', 'CurrentReadOrWrite'),
                                        existing_mapping.get('timestamps', 'Both'),
                                        idx,
                                        existing_mapping.get('description', f"Auto-generated mapping for {key}")
                                    )
                                    print(f"✓ Updated mapping for {key} with NodeId {node_id_str}")
                                else:
                                    # Create new mapping
                                    OPCUA_MAPPING.set_mapping(
                                        data_id, key, node_id_str, key, key,
                                        'Float', -1, 'CurrentReadOrWrite', 'Both', idx,
                                        f"Auto-generated mapping for {key}"
                                    )
                                    print(f"✓ Created mapping for {key} with NodeId {node_id_str}")
                            except Exception as e:
                                print(f"⚠ Failed to update mapping for {key}: {e}")
                                
                        except Exception as e:
                            print(f"✗ Failed to create variable for {key}: {e}")
                            continue
                    
                    # Update variable value
                    var = key_to_var.get(key)
                    if var is not None:
                        try:
                            # Coerce value to the type we established for this variable
                            expected_type = key_to_type.get(key, type(value))
                            if expected_type == float:
                                new_value = float(value) if value is not None else 0.0
                            elif expected_type == int:
                                new_value = int(value) if value is not None else 0
                            elif expected_type == bool:
                                new_value = bool(value) if value is not None else False
                            else:
                                new_value = str(value) if value is not None else ""
                            
                            await var.set_value(new_value)
                        except Exception as e:
                            print(f"✗ Failed to update value for {key}: {e}")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"OPC-UA update error: {e}")
                await asyncio.sleep(1)
                
    print("OPC-UA server stopped")
