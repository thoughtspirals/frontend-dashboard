# Data-Service Sync

Standalone service that syncs IO tag values from the polling service (vista-backend) to Data-Service using IPC (Unix sockets).

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌──────────────┐
│  Polling Service│         │ DataService Sync │         │ Data-Service │
│  (vista-backend)│ ──────> │   (sync_runner)  │ ──────> │  (IPC Socket)│
│                 │  Poll   │                  │  Write  │              │
└─────────────────┘         └──────────────────┘         └──────────────┘
                                                                  │
                                                                  v
                                                          ┌──────────────┐
                                                          │   Protocol   │
                                                          │   Servers    │
                                                          │ Modbus/OPC-UA│
                                                          │  IEC104/SNMP │
                                                          └──────────────┘
```

## Features

- **IPC-based Communication**: Uses Unix domain sockets for fast, reliable communication
- **Continuous Sync**: Polls data at configurable intervals (default: 1 second)
- **Automatic Retry**: Handles connection errors and retries automatically
- **Statistics Tracking**: Monitors successful/failed writes and sync performance
- **Graceful Shutdown**: Properly handles SIGINT/SIGTERM signals
- **Standalone Operation**: Can run independently or as a systemd service

## Installation

The sync service is already installed in the Data-Service directory. No additional dependencies are required beyond the existing `requirements.txt`.

## Usage

### Method 1: Shell Scripts (Recommended for Testing)

Start the sync service:
```bash
cd /home/ach1lles/Projects/IOT-GATEWAY/Data-Service
./start_sync.sh
```

Stop the sync service:
```bash
./stop_sync.sh
```

Check logs:
```bash
tail -f logs/dataservice-sync.log
```

### Method 2: Direct Python Execution

```bash
cd /home/ach1lles/Projects/IOT-GATEWAY/Data-Service
source venv/bin/activate
python sync_runner.py --help
```

Options:
- `--socket-path PATH`: Path to IPC socket (default: `/tmp/dataservice.sock`)
- `--interval SECONDS`: Sync interval in seconds (default: `1.0`)
- `--no-logging`: Disable logging
- `--stats-interval SEC`: Print stats every N seconds (default: `60`)

Example:
```bash
python sync_runner.py --interval 0.5 --stats-interval 30
```

### Method 3: Systemd Service (Recommended for Production)

Install the systemd service:
```bash
sudo cp dataservice-sync.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dataservice-sync.service
```

Start the service:
```bash
sudo systemctl start dataservice-sync.service
```

Check status:
```bash
sudo systemctl status dataservice-sync.service
```

View logs:
```bash
sudo journalctl -u dataservice-sync.service -f
```

Stop the service:
```bash
sudo systemctl stop dataservice-sync.service
```

## Configuration

### Socket Path
The default IPC socket path is `/tmp/dataservice.sock`. This should match the Data-Service configuration.

To change it, set the environment variable:
```bash
export IPC_SOCKET_PATH=/custom/path/to/socket.sock
```

Or use the `--socket-path` command-line option.

### Sync Interval
The default sync interval is 1 second. Adjust based on your requirements:

- **High-frequency updates**: `--interval 0.1` (100ms)
- **Normal updates**: `--interval 1.0` (1 second) - default
- **Low-frequency updates**: `--interval 5.0` (5 seconds)

## Data Flow

1. **Read Phase**: Sync service calls `get_latest_polled_values()` from the polling service
2. **Filter Phase**: Only processes tags with status="SUCCESS" and non-null values
3. **Transform Phase**: Formats keys as `device_name.tag_name` for uniqueness
4. **Write Phase**: Sends data to Data-Service via IPC using `IpcClient.write()`
5. **Validation Phase**: Checks response and logs any errors

## Monitoring

### Statistics
The sync service tracks the following statistics:
- Total sync cycles completed
- Successful writes
- Failed writes
- Last sync timestamp
- Recent errors (last 100)

### Health Checks
To verify the sync service is working:

1. Check if process is running:
```bash
ps aux | grep sync_runner
```

2. Monitor log output:
```bash
tail -f logs/dataservice-sync.log
```

3. Verify data is reaching Data-Service:
```bash
curl http://localhost:8080/data
```

### Common Issues

**Issue**: Sync service can't connect to IPC socket
```
Solution: Ensure Data-Service is running and the socket exists:
ls -l /tmp/dataservice.sock
```

**Issue**: Polling service not found
```
Solution: Verify vista-backend path is correct in dataservice_sync.py
VISTA_BACKEND_PATH should point to frontend-dashboard/vista-backend
```

**Issue**: No data being synced
```
Solution: Check if polling service has data:
- Verify devices are configured
- Check polling service logs
- Ensure tags are being polled successfully
```

## Integration with Existing Code

The sync service can be integrated into other Python applications:

```python
from dataservice.core.dataservice_sync import (
    DataServiceSyncService,
    get_dataservice_sync,
    start_dataservice_sync,
    stop_dataservice_sync
)

# Method 1: Simple start/stop
start_dataservice_sync()
# ... do other work ...
stop_dataservice_sync()

# Method 2: Custom configuration
sync_service = DataServiceSyncService(
    socket_path='/tmp/dataservice.sock',
    sync_interval=0.5,
    enable_logging=True
)
sync_service.start()

# Get statistics
stats = sync_service.get_stats()
print(f"Total syncs: {stats['total_syncs']}")

sync_service.stop()

# Method 3: Singleton pattern
sync = get_dataservice_sync()
sync.start()
```

## Performance Considerations

- **Memory**: Minimal overhead (~10-20 MB)
- **CPU**: Low usage, mostly I/O bound
- **Network**: Uses Unix sockets (very fast, no TCP overhead)
- **Scalability**: Can handle hundreds of tags per second

### Optimization Tips

1. Adjust sync interval based on your data change rate
2. Use bulk writes when available (future enhancement)
3. Monitor failed writes and adjust error handling
4. Consider running on the same machine as Data-Service for best performance

## Troubleshooting

### Debug Mode

Enable verbose logging:
```bash
# In dataservice_sync.py, set log level to DEBUG
# Or run with Python's debug flag
python -u sync_runner.py
```

### Test IPC Connection

Test if Data-Service IPC is responding:
```bash
cd /home/ach1lles/Projects/IOT-GATEWAY/Data-Service
source venv/bin/activate
python -c "
from src.dataservice.core.ipc import IpcClient
client = IpcClient()
result = client.write('test_key', 42.0)
print(result)
"
```

### Verify Polling Service

Check if polling service has data:
```bash
cd /home/ach1lles/Projects/IOT-GATEWAY/frontend-dashboard/vista-backend
python -c "
from app.services.polling_service import get_latest_polled_values
data = get_latest_polled_values()
print(f'Devices: {len(data)}')
for device, tags in data.items():
    print(f'  {device}: {len(tags)} tags')
"
```

## Future Enhancements

- [ ] Bulk IPC writes for better performance
- [ ] Configurable data filtering (e.g., only certain devices/tags)
- [ ] Data transformation/mapping rules
- [ ] Prometheus metrics export
- [ ] Web UI for monitoring
- [ ] Automatic tag registration in Data-Service
- [ ] Data validation and sanitization
- [ ] Historical data buffering on connection loss

## License

Same as Data-Service parent project.

## Support

For issues or questions, check:
1. Log files in `logs/dataservice-sync.log`
2. Data-Service logs in `logs/`
3. Polling service logs in `frontend-dashboard/vista-backend/logs/`
