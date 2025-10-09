import threading
import uuid
import time
from typing import Any, Dict, Optional, Tuple, Union, Callable, List
from collections import defaultdict


class DataPoint:
    """Simplified data point for IoT gateway data service"""
    def __init__(self, key: str, value: Any = 0, default: Any = 0, address: Optional[int] = None, 
                 data_type: str = "float", units: str = ""):
        self.key = key
        self.value = value
        self.default = default
        self.address = address
        self.data_type = data_type
        self.units = units
        self.timestamp = time.time()
        self.quality = "GOOD"  # GOOD, BAD, UNCERTAIN
        self.last_change = time.time()

    def set_value(self, new_value: Any):
        """Set value with timestamp and change detection"""
        if self.value != new_value:
            self.last_change = time.time()
        self.value = new_value
        self.timestamp = time.time()
        self.quality = "GOOD"

    def to_dict(self):
        return {
            'key': self.key,
            'value': self.value,
            'default': self.default,
            'address': self.address,
            'data_type': self.data_type,
            'units': self.units,
            'timestamp': self.timestamp,
            'quality': self.quality,
            'last_change': self.last_change
        }


class DataStore:
    """
    Thread-safe in-memory data store for Industrial IoT Gateway Data Service:
    - Real-time data updates
    - Address mapping for protocols
    - Event-driven notifications
    - Basic historical data
    - Quality tracking
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data_points: Dict[str, DataPoint] = {}
        self._key_to_address: Dict[str, int] = {}
        self._address_to_key: Dict[int, str] = {}
        self._key_to_id: Dict[str, str] = {}
        self._id_to_key: Dict[str, str] = {}
        
        # Event system for real-time updates
        self._change_listeners: List[Callable] = []
        
        # Simple historical data (ring buffer)
        self._history: Dict[str, List] = defaultdict(list)
        self._max_history_size = 1000

        # Address space allocation strategy
        self._address_ranges = {
            'float': (40001, 41000),    # Floating point values
            'int': (41001, 42000),      # Integer values  
            'bool': (42001, 43000),     # Boolean values
            'string': (43001, 44000),   # String values
            'raw': (44001, 45000)       # Raw/unprocessed values
        }
        self._next_addresses = {data_type: start for data_type, (start, _) in self._address_ranges.items()}

        # Initialize with default data points
        self._initialize_default_points()

    def _initialize_default_points(self):
        """Initialize default data points for IoT gateway - DISABLED"""
        # Auto-seeding disabled - no default points created
        pass

    # ---------------------- Event System ----------------------
    def add_change_listener(self, callback: Callable):
        """Add listener for data changes"""
        with self._lock:
            self._change_listeners.append(callback)

    def _notify_change(self, key: str, old_value: Any, new_value: Any):
        """Notify listeners of data changes"""
        for callback in self._change_listeners:
            try:
                callback(key, old_value, new_value, time.time())
            except Exception as e:
                print(f"Error in change listener: {e}")

    # ---------------------- Registration & Metadata ----------------------
    def _allocate_address(self, data_type: str) -> int:
        """Allocate next available address for data type"""
        with self._lock:
            if data_type not in self._next_addresses:
                data_type = 'float'  # Default fallback
            
            start, end = self._address_ranges[data_type]
            next_addr = self._next_addresses[data_type]
            
            # Find next available address in range
            while next_addr <= end:
                if next_addr not in self._address_to_key:
                    self._next_addresses[data_type] = next_addr + 1
                    return next_addr
                next_addr += 1
            
            # Range exhausted, wrap to start of range
            self._next_addresses[data_type] = start
            raise ValueError(f"Address range exhausted for data_type '{data_type}' (range: {start}-{end})")

    def register(
        self,
        key: str,
        *,
        address: Optional[int] = None,
        default: Any = 0,
        data_type: str = "float",
        units: str = "",
        allow_address_conflict: bool = False,
        auto_allocate: bool = True,
    ) -> int:
        """
        Register a data point with consistent address allocation
        
        Args:
            key: Data point key
            address: Specific address (if None and auto_allocate=True, will auto-allocate)
            default: Default value
            data_type: Data type (float, int, bool, string, raw)
            units: Units string
            allow_address_conflict: Allow address conflicts
            auto_allocate: Auto-allocate address based on data_type if address is None
            
        Returns:
            Allocated address
        """
        with self._lock:
            # Auto-allocate address if not provided
            if address is None and auto_allocate:
                address = self._allocate_address(data_type)
            
            if address is not None:
                if not allow_address_conflict and address in self._address_to_key:
                    existing_key = self._address_to_key[address]
                    if existing_key != key:
                        raise ValueError(f"Address {address} already used by key '{existing_key}'")
                self._key_to_address[key] = address
                self._address_to_key[address] = key

            # Create or update data point
            if key in self._data_points:
                dp = self._data_points[key]
                dp.default = default
                dp.data_type = data_type
                dp.units = units
                if address is not None:
                    dp.address = address
            else:
                dp = DataPoint(key, default, default, address, data_type, units)
                self._data_points[key] = dp
            
            return address or 0

    def ensure_id(self, key: str) -> str:
        """Ensure a unique ID exists for this key"""
        with self._lock:
            if key not in self._key_to_id:
                data_id = str(uuid.uuid4()).replace('-', '')
                self._key_to_id[key] = data_id
                self._id_to_key[data_id] = key
            return self._key_to_id[key]

    # ---------------------- Data Access ----------------------
    def read(self, key_or_address: Union[str, int]) -> Any:
        with self._lock:
            if isinstance(key_or_address, str):
                key = key_or_address
            else:
                key = self._address_to_key.get(key_or_address)
                if not key:
                    return 0

            dp = self._data_points.get(key)
            if dp:
                return dp.value
            return 0

    def write(self, key_or_address: Union[str, int], value: Any) -> None:
        with self._lock:
            if isinstance(key_or_address, str):
                key = key_or_address
            else:
                key = self._address_to_key.get(key_or_address)
                if not key:
                    return

            # Only update existing data points - do not create new ones
            if key not in self._data_points:
                return
            
            dp = self._data_points[key]
            old_value = dp.value
            
            # Validate and coerce value based on data type
            validated_value = self._coerce_value(dp, value)
            
            # Update value
            dp.set_value(validated_value)
            
            # Add to history
            self._add_to_history(key, validated_value)
            
            # Notify listeners
            if old_value != validated_value:
                self._notify_change(key, old_value, validated_value)

    def _coerce_value(self, dp: DataPoint, value: Any) -> Any:
        """Coerce value based on data type"""
        try:
            if dp.data_type == "int":
                return int(float(value))
            elif dp.data_type == "float":
                return float(value)
            elif dp.data_type == "bool":
                return bool(value)
            elif dp.data_type == "string":
                return str(value)
            else:
                return value
        except (ValueError, TypeError):
            dp.quality = "BAD"
            return dp.default

    def _add_to_history(self, key: str, value: Any):
        """Add value to historical data"""
        history = self._history[key]
        history.append({
            'timestamp': time.time(),
            'value': value
        })
        
        # Trim history if too large
        if len(history) > self._max_history_size:
            history.pop(0)

    # ---------------------- Data Retrieval ----------------------
    def snapshot(self) -> Dict[str, Any]:
        """Get current snapshot of all data"""
        with self._lock:
            return {key: dp.value for key, dp in self._data_points.items()}

    def detailed_snapshot(self) -> Dict[str, Dict]:
        """Get detailed snapshot with metadata"""
        with self._lock:
            return {key: dp.to_dict() for key, dp in self._data_points.items()}

    def get_history(self, key: str, limit: int = 100) -> List[Dict]:
        """Get historical data for a key"""
        with self._lock:
            history = self._history.get(key, [])
            return history[-limit:] if limit > 0 else history

    def address_space(self) -> Dict[int, Any]:
        """Get current address space mapping"""
        with self._lock:
            space = {}
            for addr, key in self._address_to_key.items():
                dp = self._data_points.get(key)
                space[addr] = dp.value if dp else 0
            return space

    def to_modbus_register(self, address: int) -> int:
        """Convert value at address to Modbus register format"""
        key = self._address_to_key.get(address)
        if not key:
            return 0
        
        dp = self._data_points.get(key)
        if not dp:
            return 0
            
        value = dp.value
        if isinstance(value, (int, float)):
            # Scale by 10 and convert to int for Modbus
            return int(float(value) * 10)
        elif isinstance(value, bool):
            return 1 if value else 0
        else:
            return 0

    def get_statistics(self) -> Dict:
        """Get datastore statistics"""
        with self._lock:
            return {
                'total_points': len(self._data_points),
                'total_addresses': len(self._address_to_key),
                'history_points': len(self._history),
                'total_history_entries': sum(len(hist) for hist in self._history.values()),
                'bad_quality_points': sum(1 for dp in self._data_points.values() if dp.quality != 'GOOD')
            }

    def get_address_space_info(self) -> Dict:
        """Get address space allocation information"""
        with self._lock:
            # Count points by data type
            type_counts = {}
            for dp in self._data_points.values():
                data_type = dp.data_type
                type_counts[data_type] = type_counts.get(data_type, 0) + 1
            
            # Get next available addresses
            next_addresses = {}
            for data_type, (start, end) in self._address_ranges.items():
                next_addr = self._next_addresses[data_type]
                next_addresses[data_type] = {
                    'next_available': next_addr,
                    'range_start': start,
                    'range_end': end,
                    'points_count': type_counts.get(data_type, 0),
                    'range_used': f"{next_addr - start}/{end - start + 1}"
                }
            
            return {
                'address_ranges': self._address_ranges,
                'next_addresses': next_addresses,
                'total_allocated': len(self._address_to_key),
                'type_distribution': type_counts
            }

# Global instance
DATA_STORE = DataStore()
