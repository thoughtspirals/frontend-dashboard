import os
import json
import time
import threading
from queue import Queue, Full, Empty
import paho.mqtt.client as mqtt
from .datastore import DATA_STORE


class MqttForwarder:
    def __init__(self) -> None:
        self._host = os.getenv('MQTT_HOST', 'localhost')
        self._port = int(os.getenv('MQTT_PORT', '1883'))
        self._client_id = os.getenv('MQTT_CLIENT_ID', 'dataservice-gateway')
        self._username = os.getenv('MQTT_USERNAME')
        self._password = os.getenv('MQTT_PASSWORD')
        self._topic_prefix = os.getenv('MQTT_TOPIC_PREFIX', 'dataservice')
        self._qos = int(os.getenv('MQTT_QOS', '1'))
        self._retain = os.getenv('MQTT_RETAIN', 'false').lower() == 'true'
        self._publish_interval = float(os.getenv('MQTT_PUBLISH_INTERVAL_SEC', '1.0'))
        self._max_queue = int(os.getenv('MQTT_MAX_QUEUE', '1000'))

        self._client = mqtt.Client(client_id=self._client_id, clean_session=True)
        if self._username:
            self._client.username_pw_set(self._username, self._password)

        # Buffers outgoing payloads when disconnected
        self._out_queue: Queue[str] = Queue(maxsize=self._max_queue)
        self._connected = threading.Event()
        self._stop = threading.Event()

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc):  # noqa: ARG002
        if rc == 0:
            self._connected.set()
        else:
            self._connected.clear()

    def _on_disconnect(self, client, userdata, rc):  # noqa: ARG002
        self._connected.clear()

    def start(self):
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def stop(self):
        self._stop.set()
        try:
            self._client.disconnect()
        except Exception:
            pass

    def _run(self):
        # Connection loop
        self._client.loop_start()
        while not self._stop.is_set():
            try:
                if not self._connected.is_set():
                    try:
                        self._client.connect(self._host, self._port, keepalive=30)
                    except Exception:
                        time.sleep(2)
                        continue
                # Publish snapshot periodically
                snapshot = DATA_STORE.snapshot()
                payload = json.dumps(snapshot)
                topic = f"{self._topic_prefix}/snapshot"
                self._enqueue(payload, topic)

                # Drain queue if connected
                if self._connected.is_set():
                    while True:
                        try:
                            topic, msg = self._out_queue.get_nowait()
                        except Empty:
                            break
                        try:
                            self._client.publish(topic, msg, qos=self._qos, retain=self._retain)
                        except Exception:
                            # Put back and break to reconnect later
                            try:
                                self._out_queue.put_nowait((topic, msg))
                            except Full:
                                pass
                            break

                time.sleep(self._publish_interval)
            except Exception:
                time.sleep(1)

        self._client.loop_stop()

    def _enqueue(self, msg: str, topic: str):
        try:
            self._out_queue.put_nowait((topic, msg))
        except Full:
            # Drop oldest to keep most recent data (gateway-like behavior)
            try:
                self._out_queue.get_nowait()
            except Empty:
                pass
            try:
                self._out_queue.put_nowait((topic, msg))
            except Full:
                pass


