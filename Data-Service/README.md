## DataService

Runs four industrial protocol servers backed by a shared Python `DATA` store:

- Modbus TCP on port 502
- OPC UA on port 4840
- IEC 60870-5-104 on port 2404
- SNMP v2c agent on port 161
 - MQTT forwarder (optional) publishes snapshots to a broker

### Requirements

- Python 3.12
- See `requirements.txt`

### Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running

Ports 161, 2404, and 502 are privileged (<1024). On Linux, either:

1) Run as root (simple but not recommended):

```bash
sudo venv/bin/python server.py
```

2) Prefer setting `cap_net_bind_service` to allow binding low ports without root:

```bash
sudo setcap 'cap_net_bind_service=+ep' venv/bin/python3.12
sudo setcap 'cap_net_bind_service=+ep' venv/bin/python
# now run unprivileged
venv/bin/python server.py
```

3) Or remap ports via NAT/firewall to high ports and keep app unprivileged.

### HTTP API (in-memory virtual map)

Server exposes a simple HTTP API on port 8080 for reading/writing and registering keys/addresses in the in-memory map.

- GET `/health` → `{ "status": "ok" }`
- GET `/data` → returns current key→value snapshot
- GET `/addr?start=0&count=4` → returns address window as JSON
- POST `/register` with JSON `{ "key": "vibration", "address": 10, "default": 0, "allow_address_conflict": false }`
- POST `/write` with JSON `{ "key": "temperature", "value": 26.2 }` or `{ "address": 0, "value": 262 }`

Notes:
- Address conflict is rejected by default. Set `allow_address_conflict=true` to override.
- Missing keys/addresses default to 0 for robustness.
- Writes sanitize NaN/inf and coerce types; booleans map to 1/0.

### Data model

`datastore.py` exposes a global dict-like `DATA` and a `DATA_STORE` singleton:

- `temperature: float`
- `humidity: float`
- `pressure: float`
- `status: int`

All protocol servers read from the single `DataStore` (`DATA_STORE`). You can still use the `DATA` dict-like interface for backward compatibility; writes to it update the store. The HTTP API also updates the same store.

### MQTT Forwarding (optional)

Set environment variables and start `server.py`. The forwarder publishes JSON snapshots to `{MQTT_TOPIC_PREFIX}/snapshot` at a fixed interval.

Env vars:

- `MQTT_HOST` (default `localhost`)
- `MQTT_PORT` (default `1883`)
- `MQTT_CLIENT_ID` (default `dataservice-gateway`)
- `MQTT_USERNAME`, `MQTT_PASSWORD` (optional)
- `MQTT_TOPIC_PREFIX` (default `dataservice`)
- `MQTT_QOS` (default `1`)
- `MQTT_RETAIN` (default `false`)
- `MQTT_PUBLISH_INTERVAL_SEC` (default `1.0`)
- `MQTT_MAX_QUEUE` (default `1000`)

Example:

```bash
export MQTT_HOST=broker.example
export MQTT_TOPIC_PREFIX=plant1/gateway1
venv/bin/python server.py
```

### Notes per protocol

- Modbus: Holding registers at address 0..3 map to temperature, humidity, pressure (scaled x10) and status.
- OPC UA: Variables under `MyObject` are writable and updated every second.
- IEC104: Points 100..103 published spontaneously every 5s.
- SNMP: Simple scalars under enterprise OID `1.3.6.1.4.1.53864` indices 1..4.

### Graceful shutdown

Press Ctrl+C. The main thread traps SIGINT/SIGTERM and exits threads.


