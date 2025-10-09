"""
Bulk OPC-UA Mapping Module

Provides intelligent bulk mapping generation for OPC-UA protocol
with smart node ID allocation and data type detection.
"""

from typing import List, Dict, Any, Optional
from .core.datastore import DATA_STORE
from .core.mapping_store import OPCUA_MAPPING


def _map_to_opcua_data_type(original_type: str, units: str = "", key_name: str = "") -> str:
    """
    Intelligently map original data type to appropriate OPC-UA data type
    
    Args:
        original_type: Original data type from data store
        units: Units string for additional context
        key_name: Key name for additional context
        
    Returns:
        Appropriate OPC-UA data type
    """
    original_type = original_type.lower()
    units = units.lower()
    key_name = key_name.lower()
    
    # Temperature measurements - use Double for precision
    if 'temp' in original_type or 'temp' in key_name or '°c' in units or '°f' in units:
        return 'Double'
    
    # Pressure measurements - use Double for precision
    if 'pressure' in original_type or 'pressure' in key_name or 'hpa' in units or 'bar' in units or 'psi' in units:
        return 'Double'
    
    # Flow rate measurements - use Double for precision
    if 'flow' in original_type or 'flow' in key_name or 'l/min' in units or 'm3/h' in units:
        return 'Double'
    
    # Vibration measurements - use Double for precision
    if 'vibrat' in original_type or 'vibrat' in key_name or 'mm/s' in units:
        return 'Double'
    
    # Power measurements - use Double for precision
    if 'power' in original_type or 'power' in key_name or 'kw' in units or 'w' in units:
        return 'Double'
    
    # Boolean/Status values - use Boolean
    if (original_type == 'bool' or original_type == 'boolean' or 
        'status' in key_name or 'enabled' in key_name or 'motor' in key_name):
        return 'Boolean'
    
    # Integer values - use appropriate integer type
    if original_type == 'int' or original_type == 'integer':
        # Check if it's a percentage (0-100) or small integer
        if 'position' in key_name or '%' in units or 'code' in key_name or 'alarm' in key_name:
            return 'Int16'
        else:
            return 'Int32'
    
    # Float values - use Double for precision
    if original_type == 'float' or original_type == 'double':
        return 'Double'
    
    # String values - use String
    if original_type == 'string' or original_type == 'str':
        return 'String'
    
    # Default to Double for unknown types
    return 'Double'


def _get_opcua_access_level(data_type: str, key_name: str = "") -> str:
    """
    Get appropriate access level for OPC-UA data type
    
    Args:
        data_type: OPC-UA data type
        key_name: Key name for context
        
    Returns:
        Access level string
    """
    key_name = key_name.lower()
    
    # Status/Control values - read-write
    if ('status' in key_name or 'enabled' in key_name or 'motor' in key_name or 
        'position' in key_name or 'valve' in key_name):
        return 'CurrentReadOrWrite'
    
    # Measurements - read-only
    if ('temp' in key_name or 'pressure' in key_name or 'flow' in key_name or 
        'vibrat' in key_name or 'power' in key_name):
        return 'CurrentRead'
    
    # Default to read-write for flexibility
    return 'CurrentReadOrWrite'


def _get_opcua_timestamps(data_type: str, key_name: str = "") -> str:
    """
    Get appropriate timestamp setting for OPC-UA data type
    
    Args:
        data_type: OPC-UA data type
        key_name: Key name for context
        
    Returns:
        Timestamp setting string
    """
    key_name = key_name.lower()
    
    # Measurements - both server and source timestamps
    if ('temp' in key_name or 'pressure' in key_name or 'flow' in key_name or 
        'vibrat' in key_name or 'power' in key_name):
        return 'Both'
    
    # Status values - server timestamp
    if ('status' in key_name or 'enabled' in key_name or 'motor' in key_name):
        return 'Server'
    
    # Default to both
    return 'Both'


def _allocate_node_id_by_type(current_node_id: int, data_type: str, key_name: str = "", namespace: int = 2) -> int:
    """
    Smart node ID allocation that groups by data type and avoids conflicts
    
    Args:
        current_node_id: Current node ID position
        data_type: OPC-UA data type
        key_name: Key name for context
        namespace: OPC-UA namespace
        
    Returns:
        Allocated node ID that does not conflict with existing mappings
    """
    # Define type-specific node ID ranges for better organization
    type_ranges = {
        "Double": (100, 200),      # Floating point measurements
        "Int32": (200, 300),       # 32-bit integers
        "Int16": (300, 400),       # 16-bit integers
        "Boolean": (400, 500),     # Boolean values
        "String": (500, 600),      # String values
        "Float": (600, 700),       # Float values
        "Byte": (700, 800),        # Byte values
        "SByte": (800, 900)        # Signed byte values
    }
    
    start_range, end_range = type_ranges.get(data_type, (100, 1000))
    
    # Get all existing mappings to check for conflicts
    existing_mappings = OPCUA_MAPPING.all()
    used_node_ids = set()
    
    for mapping in existing_mappings.values():
        node_id_str = mapping.get("node_id", "")
        if node_id_str.startswith(f"ns={namespace};i="):
            try:
                node_num = int(node_id_str.split("i=")[1])
                if start_range <= node_num <= end_range:
                    used_node_ids.add(node_num)
            except (ValueError, IndexError):
                continue
    
    # Find next available ID starting from the appropriate range
    search_start = max(current_node_id, start_range)
    for candidate_id in range(search_start, end_range + 1):
        if candidate_id not in used_node_ids:
            return candidate_id
    
    # If no available ID in range, return start of range (should handle overflow)
    return start_range


def auto_generate_opcua_mappings(
    data_ids: List[str],
    start_namespace: int = 2,
    start_node_id: int = 100,
    padding_strategy: str = 'data_type',
    access_level: str = 'auto',
    timestamps: str = 'auto',
    value_rank: int = -1
) -> Dict[str, Any]:
    """
    Bulk auto-generate OPC-UA mappings with intelligent node ID allocation
    
    Args:
        data_ids: List of data IDs to map
        start_namespace: Starting namespace for allocation
        start_node_id: Starting node ID for allocation
        padding_strategy: 'data_type' or 'sequential'
        access_level: Access level ('auto', 'CurrentRead', 'CurrentWrite', 'CurrentReadOrWrite')
        timestamps: Timestamp setting ('auto', 'None', 'Server', 'Source', 'Both')
        value_rank: Value rank (-1=Scalar, 0=Array, >0=specific dimension)
        
    Returns:
        Dictionary with results and mapping information
    """
    results = []
    errors = []
    current_node_id = start_node_id
    
    # Get detailed data store info for smart type detection
    detailed_snapshot = DATA_STORE.detailed_snapshot()
    
    for i, data_id in enumerate(data_ids):
        try:
            # Find the data point by ID
            data_point = None
            for key, info in detailed_snapshot.items():
                if DATA_STORE._key_to_id.get(key) == data_id:
                    data_point = info
                    break
            
            if not data_point:
                errors.append(f"Data ID {data_id} not found in data store")
                results.append({
                    'data_id': data_id,
                    'ok': False,
                    'error': 'Data ID not found'
                })
                continue
            
            key = data_point['key']
            original_data_type = data_point['data_type']
            units = data_point.get('units', '')
            
            # Smart OPC-UA data type mapping
            opcua_data_type = _map_to_opcua_data_type(original_data_type, units, key)
            
            # Smart node ID allocation
            if padding_strategy == 'data_type':
                # Group by data type and allocate ranges
                current_node_id = _allocate_node_id_by_type(current_node_id, opcua_data_type, key, start_namespace)
            else:
                # Sequential allocation
                current_node_id = start_node_id + i
            
            # Determine access level
            if access_level == 'auto':
                determined_access = _get_opcua_access_level(opcua_data_type, key)
            else:
                determined_access = access_level
            
            # Determine timestamps
            if timestamps == 'auto':
                determined_timestamps = _get_opcua_timestamps(opcua_data_type, key)
            else:
                determined_timestamps = timestamps
            
            # Create node ID
            node_id = f"ns={start_namespace};i={current_node_id}"
            browse_name = key
            display_name = f"{key} ({units})" if units else key
            
            # Create mapping
            OPCUA_MAPPING.set_mapping(
                data_id, key, node_id, browse_name, display_name,
                opcua_data_type, value_rank, determined_access, 
                determined_timestamps, start_namespace,
                f"Auto-generated for {key} ({original_data_type})"
            )
            
            results.append({
                'data_id': data_id,
                'key': key,
                'node_id': node_id,
                'browse_name': browse_name,
                'display_name': display_name,
                'data_type': opcua_data_type,
                'access_level': determined_access,
                'timestamps': determined_timestamps,
                'value_rank': value_rank,
                'namespace': start_namespace,
                'original_data_type': original_data_type,
                'units': units,
                'ok': True
            })
            
            # Move to next node ID
            current_node_id += 1
            
        except Exception as e:
            errors.append(f"Error processing {data_id}: {str(e)}")
            results.append({
                'data_id': data_id,
                'ok': False,
                'error': str(e)
            })
    
    return {
        'ok': len(errors) == 0,
        'total_requested': len(data_ids),
        'successful': len([r for r in results if r.get('ok')]),
        'failed': len([r for r in results if not r.get('ok')]),
        'results': results,
        'errors': errors,
        'node_range': {
            'start': start_node_id,
            'end': current_node_id - 1,
            'total_nodes': current_node_id - start_node_id,
            'namespace': start_namespace
        }
    }


def get_opcua_data_types() -> Dict[str, Dict[str, Any]]:
    """
    Get information about supported OPC-UA data types
    
    Returns:
        Dictionary with OPC-UA data type information
    """
    return {
        'Boolean': {
            'description': 'Boolean value (true/false)',
            'use_cases': ['Status', 'On/Off', 'Enabled/Disabled'],
            'node_range': '400-499',
            'size': '1 bit'
        },
        'SByte': {
            'description': 'Signed 8-bit integer',
            'use_cases': ['Small counters', 'Status codes'],
            'node_range': '800-899',
            'size': '1 byte'
        },
        'Byte': {
            'description': 'Unsigned 8-bit integer',
            'use_cases': ['Small positive values', 'Flags'],
            'node_range': '700-799',
            'size': '1 byte'
        },
        'Int16': {
            'description': 'Signed 16-bit integer',
            'use_cases': ['Percentages', 'Small measurements', 'Status codes'],
            'node_range': '300-399',
            'size': '2 bytes'
        },
        'UInt16': {
            'description': 'Unsigned 16-bit integer',
            'use_cases': ['Counters', 'Positive values'],
            'node_range': '300-399',
            'size': '2 bytes'
        },
        'Int32': {
            'description': 'Signed 32-bit integer',
            'use_cases': ['Large counters', 'Timestamps', 'IDs'],
            'node_range': '200-299',
            'size': '4 bytes'
        },
        'UInt32': {
            'description': 'Unsigned 32-bit integer',
            'use_cases': ['Large positive values', 'Timestamps'],
            'node_range': '200-299',
            'size': '4 bytes'
        },
        'Int64': {
            'description': 'Signed 64-bit integer',
            'use_cases': ['Very large counters', 'Precise timestamps'],
            'node_range': '200-299',
            'size': '8 bytes'
        },
        'UInt64': {
            'description': 'Unsigned 64-bit integer',
            'use_cases': ['Very large positive values'],
            'node_range': '200-299',
            'size': '8 bytes'
        },
        'Float': {
            'description': '32-bit floating point',
            'use_cases': ['Basic measurements', 'Simple calculations'],
            'node_range': '600-699',
            'size': '4 bytes'
        },
        'Double': {
            'description': '64-bit floating point',
            'use_cases': ['Precise measurements', 'Temperature', 'Pressure', 'Flow'],
            'node_range': '100-199',
            'size': '8 bytes'
        },
        'String': {
            'description': 'Unicode string',
            'use_cases': ['Text', 'Descriptions', 'Messages'],
            'node_range': '500-599',
            'size': 'Variable'
        },
        'DateTime': {
            'description': 'Date and time',
            'use_cases': ['Timestamps', 'Scheduling'],
            'node_range': '900-999',
            'size': '8 bytes'
        },
        'Guid': {
            'description': 'Globally unique identifier',
            'use_cases': ['Unique IDs', 'References'],
            'node_range': '900-999',
            'size': '16 bytes'
        },
        'ByteString': {
            'description': 'Byte array',
            'use_cases': ['Binary data', 'Images', 'Files'],
            'node_range': '500-599',
            'size': 'Variable'
        }
    }


def get_opcua_access_levels() -> Dict[str, str]:
    """
    Get information about OPC-UA access levels
    
    Returns:
        Dictionary with access level descriptions
    """
    return {
        'CurrentRead': 'Read-only access to current value',
        'CurrentWrite': 'Write-only access to current value',
        'CurrentReadOrWrite': 'Read and write access to current value',
        'HistoryRead': 'Read access to historical data',
        'HistoryWrite': 'Write access to historical data',
        'SemanticChange': 'Access to semantic changes',
        'StatusWrite': 'Write access to status information',
        'TimestampWrite': 'Write access to timestamp information'
    }


def get_opcua_timestamps() -> Dict[str, str]:
    """
    Get information about OPC-UA timestamp settings
    
    Returns:
        Dictionary with timestamp descriptions
    """
    return {
        'None': 'No timestamps',
        'Server': 'Server timestamp only',
        'Source': 'Source timestamp only',
        'Both': 'Both server and source timestamps'
    }
