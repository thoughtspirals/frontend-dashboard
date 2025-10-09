"""
Standalone Data Service Sync Module

Syncs IO tag values from polling service to Data-Service using IPC.
Reads from vista-backend HTTP API and pushes to Data-Service via Unix socket.
"""
import time
import threading
import requests
from typing import Optional, Dict, Any
from .ipc import IpcClient


class DataServiceSyncService:
    """
    Continuously sync polled values to Data-Service via IPC
    """
    
    def __init__(
        self, 
        socket_path: Optional[str] = None,
        polling_api_url: str = "http://localhost:8000/deploy/api/io/polled-values",
        sync_interval: float = 1.0,
        enable_logging: bool = True
    ):
        """
        Initialize the sync service
        
        Args:
            socket_path: Path to Data-Service IPC socket
            polling_api_url: URL to fetch polled values from vista-backend
            sync_interval: Seconds between sync cycles
            enable_logging: Whether to enable logging
        """
        self.ipc_client = IpcClient(socket_path)
        self.polling_api_url = polling_api_url
        self.sync_interval = sync_interval
        self.enable_logging = enable_logging
        
        self._sync_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Track statistics
        self.stats = {
            'total_syncs': 0,
            'successful_writes': 0,
            'failed_writes': 0,
            'last_sync_time': None,
            'errors': []
        }
    
    def _log(self, level: str, message: str):
        """Log message to stdout"""
        if self.enable_logging:
            timestamp = time.strftime('%H:%M:%S')
            print(f"{timestamp} | {level.upper():8} | dataservice.sync | {message}", flush=True)
    
    def _get_polled_values(self) -> Dict[str, Dict[str, Any]]:
        """Get latest polled values from vista-backend HTTP API"""
        try:
            response = requests.get(self.polling_api_url, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self._log('error', f"Failed to fetch polled values from API: {e}")
            return {}
        except Exception as e:
            self._log('error', f"Unexpected error fetching polled values: {e}")
            return {}
    
    def _sync_to_dataservice(self):
        """Main sync loop - continuously sync polled values to Data-Service"""
        self._log('info', "🔄 Data-Service sync service started")
        self._log('info', f"   Polling API: {self.polling_api_url}")
        self._log('info', f"   IPC Socket: {self.ipc_client.socket_path}")
        self._log('info', f"   Sync Interval: {self.sync_interval}s")
        
        while not self._stop_event.is_set():
            try:
                sync_start = time.time()
                
                # Get all current values from polling service via HTTP
                polled_values = self._get_polled_values()
                
                if not polled_values:
                    self._log('debug', "No polled values available from API")
                    time.sleep(self.sync_interval)
                    continue
                
                write_count = 0
                error_count = 0
                
                # Push each tag to Data-Service
                for device_name, tags in polled_values.items():
                    for tag_id, tag_data in tags.items():
                        tag_name = tag_data.get('tag_name') or tag_data.get('name') or tag_id
                        value = tag_data.get('value')
                        status = tag_data.get('status')
                        
                        # Only push successful reads with valid values
                        if status in ["SUCCESS", "success", "ok", "OK"] and value is not None:
                            try:
                                # Use tag_name as the key for Data-Service
                                # Format: device_name.tag_name for uniqueness
                                full_key = f"{device_name}:{tag_name}"
                                
                                # Write via IPC
                                response = self.ipc_client.write(full_key, value)
                                
                                if response.get('ok'):
                                    write_count += 1
                                    self.stats['successful_writes'] += 1
                                else:
                                    error_count += 1
                                    self.stats['failed_writes'] += 1
                                    error_msg = response.get('error', 'Unknown error')
                                    self._log('warning', f"Failed to write {full_key}: {error_msg}")
                                    
                            except Exception as e:
                                error_count += 1
                                self.stats['failed_writes'] += 1
                                error_msg = f"Error writing {tag_name}: {str(e)}"
                                self._log('error', error_msg)
                                if len(self.stats['errors']) < 100:  # Limit error list size
                                    self.stats['errors'].append({
                                        'time': time.time(),
                                        'message': error_msg
                                    })
                
                # Update statistics
                self.stats['total_syncs'] += 1
                self.stats['last_sync_time'] = time.time()
                
                sync_duration = time.time() - sync_start
                
                # Log periodic summary
                if write_count > 0 or error_count > 0:
                    self._log('debug', f"Sync cycle: {write_count} writes, {error_count} errors ({sync_duration:.2f}s)")
                
                if self.stats['total_syncs'] % 60 == 0:  # Every 60 syncs
                    self._log('info', 
                        f"Sync stats - Total: {self.stats['total_syncs']}, "
                        f"Success: {self.stats['successful_writes']}, "
                        f"Failed: {self.stats['failed_writes']}"
                    )
                
                # Sleep for remaining interval time
                sleep_time = max(0, self.sync_interval - sync_duration)
                if sleep_time > 0:
                    self._stop_event.wait(sleep_time)
                
            except Exception as e:
                self._log('error', f"Error in Data-Service sync loop: {e}")
                self._stop_event.wait(5)  # Wait longer on error
        
        self._log('info', "🛑 Data-Service sync service stopped")
    
    def start(self):
        """Start the Data-Service sync thread"""
        if self._sync_thread and self._sync_thread.is_alive():
            self._log('warning', "Data-Service sync already running")
            return False
        
        self._stop_event.clear()
        self._sync_thread = threading.Thread(
            target=self._sync_to_dataservice, 
            daemon=True,
            name="DataServiceSync"
        )
        self._sync_thread.start()
        self._log('info', "✓ Data-Service sync thread started")
        return True
    
    def stop(self):
        """Stop the Data-Service sync thread"""
        self._stop_event.set()
        if self._sync_thread:
            self._sync_thread.join(timeout=5)
        self._log('info', "✓ Data-Service sync thread stopped")
    
    def is_running(self) -> bool:
        """Check if sync service is running"""
        return self._sync_thread is not None and self._sync_thread.is_alive()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get sync service statistics"""
        return {
            **self.stats,
            'running': self.is_running()
        }


# Singleton instance for easy import
_sync_service: Optional[DataServiceSyncService] = None


def get_dataservice_sync() -> DataServiceSyncService:
    """Get or create the singleton sync service instance"""
    global _sync_service
    if _sync_service is None:
        _sync_service = DataServiceSyncService()
    return _sync_service


def start_dataservice_sync():
    """Start the Data-Service sync service"""
    sync_service = get_dataservice_sync()
    return sync_service.start()


def stop_dataservice_sync():
    """Stop the Data-Service sync service"""
    sync_service = get_dataservice_sync()
    sync_service.stop()
