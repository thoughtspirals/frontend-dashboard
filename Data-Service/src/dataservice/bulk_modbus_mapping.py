"""
Bulk Modbus Mapping Module

Provides intelligent bulk mapping generation for Modbus protocol
with smart address allocation and data type detection.
"""

from typing import List, Dict, Any, Optional
from ..core.datastore import DATA_STORE
from ..core.mapping_store import MODBUS_MAPPING


def _map_to_modbus_data_type(original_type: str, units: str = "") -> str:
    """
    Intelligently map original data type to appropriate Modbus data type
    
    Args:
        original_type: Original data type from data store
        units: Units string for additional context
        
    Returns:
        Appropriate Modbus data type
    """
    original_type = original_type.lower()
    units = units.lower()
    
    # Temperature sensors - use float32 for precision
    if 'temp' in original_type or '°c' in units or '°f' in units:
        return 'float32'
    
    # Pressure sensors - use float32 for precision  
    if 'pressure' in original_type or 'hpa' in units or 'bar' in units or 'psi' in units:
        return 'float32'
    
    # Flow rates - use float32 for precision
    if 'flow' in original_type or 'l/min' in units or 'm3/h' in units:
        return 'float32'
    
    # Vibration - use float32 for precision
    if 'vibrat' in original_type or 'mm/s' in units:
        return 'float32'
    
    # Power consumption - use float32 for precision
    if 'power' in original_type or 'kw' in units or 'w' in units:
        return 'float32'
    
    # Boolean values - use single register
    if original_type == 'bool' or original_type == 'boolean':
        return 'int16'
    
    # Integer values
    if original_type == 'int' or original_type == 'integer':
        # Check if it's a percentage (0-100)
        if 'position' in original_type or '%' in units:
            return 'int16'
        # Check if it's a status code
        elif 'status' in original_type or 'code' in original_type or 'alarm' in original_type:
            return 'int16'
        else:
            return 'int32'
    
    # Float values - use float32 for precision
    if original_type == 'float' or original_type == 'double':
        return 'float32'
    
    # String values - use multiple registers (4 registers = 8 bytes)
    if original_type == 'string' or original_type == 'str':
        return 'string8'
    
    # Default to int16 for unknown types
    return 'int16'


def _get_register_count(modbus_data_type: str) -> int:
    """
    Get the number of Modbus registers needed for a data type
    
    Args:
        modbus_data_type: Modbus data type
        
    Returns:
        Number of registers required
    """
    register_counts = {
        'int16': 1,
        'uint16': 1,
        'int32': 2,
        'uint32': 2,
        'float32': 2,
        'string8': 4,  # 8 bytes = 4 registers
        'string16': 8,  # 16 bytes = 8 registers
        'bool': 1
    }
    return register_counts.get(modbus_data_type, 1)


def _allocate_address_by_type(current_address: int, data_type: str, register_count: int) -> int:
    """
    Smart address allocation that groups by data type with padding
    
    Args:
        current_address: Current address position
        data_type: Modbus data type
        register_count: Number of registers needed
        
    Returns:
        Allocated starting address
    """
    # Define type-specific address ranges for better organization
    type_ranges = {
        'float32': (40001, 41000),    # Floating point values
        'int32': (41001, 42000),      # 32-bit integers
        'int16': (42001, 43000),      # 16-bit integers
        'string8': (43001, 44000),    # String values
        'string16': (44001, 45000),   # Long strings
        'bool': (45001, 46000)        # Boolean values
    }
    
    start_range, end_range = type_ranges.get(data_type, (40001, 50000))
    
    # Ensure we don't exceed the range
    if current_address + register_count > end_range:
        # Move to next available range
        return start_range
    
    # Add padding between different data types
    if current_address < start_range:
        return start_range
    
    return current_address


def auto_generate_modbus_mappings(
    data_ids: List[str],
    start_address: int = 40001,
    padding_strategy: str = 'data_type',
    function_code: int = 3,
    access: str = 'rw',
    endianess: str = 'big'
) -> Dict[str, Any]:
    """
    Bulk auto-generate Modbus mappings with intelligent address allocation
    
    Args:
        data_ids: List of data IDs to map
        start_address: Starting address for allocation
        padding_strategy: 'data_type' or 'sequential'
        function_code: Modbus function code (default: 3 for Holding Register)
        access: Access level ('rw' or 'r')
        endianess: Endianess ('big' or 'little')
        
    Returns:
        Dictionary with results and mapping information
    """
    results = []
    errors = []
    current_address = start_address
    
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
            
            # Smart Modbus data type mapping
            modbus_data_type = _map_to_modbus_data_type(original_data_type, units)
            
            # Calculate register count based on data type
            register_count = _get_register_count(modbus_data_type)
            
            # Smart address allocation
            if padding_strategy == 'data_type':
                # Group by data type and allocate ranges
                current_address = _allocate_address_by_type(
                    current_address, modbus_data_type, register_count
                )
            else:
                # Sequential allocation
                current_address = start_address + (i * register_count)
            
            # Create mapping
            MODBUS_MAPPING.set_mapping(
                data_id, key, current_address, function_code,
                modbus_data_type, access, 1.0, endianess,
                f"Auto-generated for {key} ({original_data_type})"
            )
            
            results.append({
                'data_id': data_id,
                'key': key,
                'register_address': current_address,
                'data_type': modbus_data_type,
                'register_count': register_count,
                'original_data_type': original_data_type,
                'units': units,
                'ok': True
            })
            
            # Move to next address
            current_address += register_count
            
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
        'address_range': {
            'start': start_address,
            'end': current_address - 1,
            'total_registers': current_address - start_address
        }
    }


def get_modbus_data_types() -> Dict[str, Dict[str, Any]]:
    """
    Get information about supported Modbus data types
    
    Returns:
        Dictionary with data type information
    """
    return {
        'int16': {
            'description': '16-bit signed integer',
            'registers': 1,
            'range': '-32,768 to 32,767',
            'use_cases': ['Status codes', 'Percentages', 'Boolean values']
        },
        'uint16': {
            'description': '16-bit unsigned integer',
            'registers': 1,
            'range': '0 to 65,535',
            'use_cases': ['Counters', 'Positive values']
        },
        'int32': {
            'description': '32-bit signed integer',
            'registers': 2,
            'range': '-2,147,483,648 to 2,147,483,647',
            'use_cases': ['Large counters', 'Precise integers']
        },
        'uint32': {
            'description': '32-bit unsigned integer',
            'registers': 2,
            'range': '0 to 4,294,967,295',
            'use_cases': ['Large positive values', 'Timestamps']
        },
        'float32': {
            'description': '32-bit floating point (IEEE 754)',
            'registers': 2,
            'range': '±3.4 × 10^38',
            'use_cases': ['Temperature', 'Pressure', 'Flow rates', 'Vibration']
        },
        'string8': {
            'description': '8-byte string',
            'registers': 4,
            'range': '8 characters',
            'use_cases': ['Short text', 'Status messages']
        },
        'string16': {
            'description': '16-byte string',
            'registers': 8,
            'range': '16 characters',
            'use_cases': ['Longer text', 'Descriptions']
        }
    }
