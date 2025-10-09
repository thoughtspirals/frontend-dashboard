"""
Bulk IEC 104 Mapping Module

Provides intelligent bulk mapping generation for IEC 60870-5-104 protocol
with smart IOA (Information Object Address) allocation and data type detection.
"""

from typing import List, Dict, Any, Optional
from ..core.datastore import DATA_STORE
from ..core.mapping_store import IEC104_MAPPING


def _map_to_iec104_data_type(original_type: str, units: str = "", key_name: str = "") -> str:
    """
    Intelligently map original data type to appropriate IEC 104 data type
    
    Args:
        original_type: Original data type from data store
        units: Units string for additional context
        key_name: Key name for additional context
        
    Returns:
        Appropriate IEC 104 data type
    """
    original_type = original_type.lower()
    units = units.lower()
    key_name = key_name.lower()
    
    # Temperature measurements - use M_ME_NC_1 (measured value, short float)
    if 'temp' in original_type or 'temp' in key_name or '°c' in units or '°f' in units:
        return 'M_ME_NC_1'
    
    # Pressure measurements - use M_ME_NC_1 (measured value, short float)
    if 'pressure' in original_type or 'pressure' in key_name or 'hpa' in units or 'bar' in units or 'psi' in units:
        return 'M_ME_NC_1'
    
    # Flow rate measurements - use M_ME_NC_1 (measured value, short float)
    if 'flow' in original_type or 'flow' in key_name or 'l/min' in units or 'm3/h' in units:
        return 'M_ME_NC_1'
    
    # Vibration measurements - use M_ME_NC_1 (measured value, short float)
    if 'vibrat' in original_type or 'vibrat' in key_name or 'mm/s' in units:
        return 'M_ME_NC_1'
    
    # Power measurements - use M_ME_NC_1 (measured value, short float)
    if 'power' in original_type or 'power' in key_name or 'kw' in units or 'w' in units:
        return 'M_ME_NC_1'
    
    # Boolean/Status values - use M_SP_NA_1 (single point information)
    if (original_type == 'bool' or original_type == 'boolean' or 
        'status' in key_name or 'enabled' in key_name or 'motor' in key_name):
        return 'M_SP_NA_1'
    
    # Integer values - use M_ME_NB_1 (measured value, scaled)
    if original_type == 'int' or original_type == 'integer':
        # Check if it's a percentage (0-100)
        if 'position' in key_name or '%' in units:
            return 'M_ME_NB_1'
        # Check if it's a status code or alarm
        elif 'code' in key_name or 'alarm' in key_name:
            return 'M_ME_NB_1'
        else:
            return 'M_ME_NB_1'
    
    # Float values - use M_ME_NC_1 (measured value, short float)
    if original_type == 'float' or original_type == 'double':
        return 'M_ME_NC_1'
    
    # Default to measured value for unknown types
    return 'M_ME_NC_1'


def _get_iec104_cause_of_transmission(data_type: str, key_name: str = "") -> str:
    """
    Get appropriate cause of transmission for IEC 104 data type
    
    Args:
        data_type: IEC 104 data type
        key_name: Key name for context
        
    Returns:
        Cause of transmission string
    """
    key_name = key_name.lower()
    
    # Status/Boolean values - spontaneous
    if data_type == 'M_SP_NA_1':
        return 'spontaneous'
    
    # Measurements - periodic for continuous monitoring
    if data_type in ['M_ME_NC_1', 'M_ME_NB_1']:
        return 'periodic'
    
    # Default to spontaneous
    return 'spontaneous'


def _allocate_ioa_by_type(current_ioa: int, data_type: str, key_name: str = "") -> int:
    """
    Smart IOA allocation that groups by data type with padding
    
    Args:
        current_ioa: Current IOA position
        data_type: IEC 104 data type
        key_name: Key name for context
        
    Returns:
        Allocated IOA
    """
    # Define type-specific IOA ranges for better organization
    type_ranges = {
        'M_ME_NC_1': (1000, 2000),    # Measured values (float)
        'M_ME_NB_1': (2000, 3000),    # Scaled values (int)
        'M_SP_NA_1': (3000, 4000),    # Single point information (bool)
        'M_ME_NA_1': (4000, 5000),    # Normalized values
        'M_ME_NF_1': (5000, 6000)     # Floating point values
    }
    
    start_range, end_range = type_ranges.get(data_type, (1000, 10000))
    
    # Ensure we don't exceed the range
    if current_ioa + 1 > end_range:
        # Move to next available range
        return start_range
    
    # Add padding between different data types
    if current_ioa < start_range:
        return start_range
    
    return current_ioa


def auto_generate_iec104_mappings(
    data_ids: List[str],
    start_ioa: int = 1000,
    padding_strategy: str = 'data_type',
    cause: str = 'auto',
    quality: bool = True,
    timestamp: bool = True,
    access: str = 'r'
) -> Dict[str, Any]:
    """
    Bulk auto-generate IEC 104 mappings with intelligent IOA allocation
    
    Args:
        data_ids: List of data IDs to map
        start_ioa: Starting IOA for allocation
        padding_strategy: 'data_type' or 'sequential'
        cause: Cause of transmission ('auto', 'spontaneous', 'periodic', 'request')
        quality: Include quality descriptor
        timestamp: Include timestamp
        access: Access level ('r' or 'rw')
        
    Returns:
        Dictionary with results and mapping information
    """
    results = []
    errors = []
    current_ioa = start_ioa
    
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
            
            # Smart IEC 104 data type mapping
            iec104_data_type = _map_to_iec104_data_type(original_data_type, units, key)
            
            # Smart IOA allocation
            if padding_strategy == 'data_type':
                # Group by data type and allocate ranges
                current_ioa = _allocate_ioa_by_type(current_ioa, iec104_data_type, key)
            else:
                # Sequential allocation
                current_ioa = start_ioa + i
            
            # Determine cause of transmission
            if cause == 'auto':
                transmission_cause = _get_iec104_cause_of_transmission(iec104_data_type, key)
            else:
                transmission_cause = cause
            
            # Create mapping
            IEC104_MAPPING.set_mapping(
                data_id, key, current_ioa, iec104_data_type,
                transmission_cause, quality, timestamp, access,
                f"Auto-generated for {key} ({original_data_type})"
            )
            
            results.append({
                'data_id': data_id,
                'key': key,
                'ioa': current_ioa,
                'type': iec104_data_type,
                'cause': transmission_cause,
                'quality': quality,
                'timestamp': timestamp,
                'original_data_type': original_data_type,
                'units': units,
                'ok': True
            })
            
            # Move to next IOA
            current_ioa += 1
            
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
        'ioa_range': {
            'start': start_ioa,
            'end': current_ioa - 1,
            'total_ioas': current_ioa - start_ioa
        }
    }


def get_iec104_data_types() -> Dict[str, Dict[str, Any]]:
    """
    Get information about supported IEC 104 data types
    
    Returns:
        Dictionary with IEC 104 data type information
    """
    return {
        'M_SP_NA_1': {
            'description': 'Single Point Information',
            'use_cases': ['Status', 'Boolean values', 'On/Off states'],
            'ioa_range': '3000-3999',
            'data_format': 'Boolean'
        },
        'M_ME_NA_1': {
            'description': 'Measured Value, Normalized',
            'use_cases': ['Normalized measurements', 'Scaled values'],
            'ioa_range': '4000-4999',
            'data_format': 'Normalized (-1.0 to 1.0)'
        },
        'M_ME_NB_1': {
            'description': 'Measured Value, Scaled',
            'use_cases': ['Integer measurements', 'Counters', 'Percentages'],
            'ioa_range': '2000-2999',
            'data_format': '16-bit integer'
        },
        'M_ME_NC_1': {
            'description': 'Measured Value, Short Float',
            'use_cases': ['Temperature', 'Pressure', 'Flow rates', 'Vibration'],
            'ioa_range': '1000-1999',
            'data_format': '32-bit float'
        },
        'M_ME_NF_1': {
            'description': 'Measured Value, Float',
            'use_cases': ['High precision measurements', 'Scientific data'],
            'ioa_range': '5000-5999',
            'data_format': '64-bit float'
        },
        'M_IT_NA_1': {
            'description': 'Integrated Totals',
            'use_cases': ['Energy consumption', 'Total flow', 'Counters'],
            'ioa_range': '6000-6999',
            'data_format': '32-bit integer'
        },
        'M_EP_TA_1': {
            'description': 'Event of Protection Equipment',
            'use_cases': ['Protection events', 'Alarms', 'Faults'],
            'ioa_range': '7000-7999',
            'data_format': 'Event data'
        },
        'M_EP_TB_1': {
            'description': 'Packed Start Events of Protection Equipment',
            'use_cases': ['Multiple protection events', 'Batch alarms'],
            'ioa_range': '8000-8999',
            'data_format': 'Packed events'
        }
    }


def get_iec104_causes_of_transmission() -> Dict[str, str]:
    """
    Get information about IEC 104 causes of transmission
    
    Returns:
        Dictionary with cause descriptions
    """
    return {
        'spontaneous': 'Spontaneous transmission (immediate)',
        'periodic': 'Periodic transmission (scheduled)',
        'request': 'Requested transmission (on demand)',
        'interrogation': 'Interrogation command',
        'activation': 'Activation command',
        'deactivation': 'Deactivation command',
        'activation_termination': 'Activation termination',
        'return_info_remote': 'Return information remote',
        'return_info_local': 'Return information local',
        'file_transfer': 'File transfer',
        'authentication': 'Authentication',
        'session_key': 'Session key',
        'user_data': 'User data',
        'unknown_type': 'Unknown type',
        'unknown_reason': 'Unknown reason',
        'unknown_asdu': 'Unknown ASDU',
        'unknown_information_object': 'Unknown information object'
    }
