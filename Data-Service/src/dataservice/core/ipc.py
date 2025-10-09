import os
import json
import socket
import threading
from typing import Optional
from .datastore import DATA_STORE


class IpcServer:
    """
    Minimal newline-delimited JSON (NDJSON) IPC over Unix domain socket.

    Requests:
      {"action":"write","key":"temperature","value":28.7}
      {"action":"write_by_id","id":"<uuid_no_dashes>","value":28.7}

    Responses:
      {"ok":true}
      {"ok":false,"error":"..."}
    """

    def __init__(self, socket_path: Optional[str] = None) -> None:
        self.socket_path = socket_path or os.getenv("IPC_SOCKET_PATH", "/tmp/dataservice.sock")
        self._server: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        # Ensure old socket file is removed
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except OSError:
            pass

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # Restrict permissions to owner only
        old_umask = os.umask(0o177)
        try:
            srv.bind(self.socket_path)
        finally:
            os.umask(old_umask)
        srv.listen(5)
        self._server = srv
        self._stop.clear()

        def run():
            while not self._stop.is_set():
                try:
                    srv.settimeout(1.0)
                    try:
                        conn, _ = srv.accept()
                    except socket.timeout:
                        continue
                    threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()
                except Exception as e:
                    # Keep server alive; print error for visibility
                    print(f"IPC accept error: {e}")

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._server:
                self._server.close()
        except Exception:
            pass
        finally:
            self._server = None
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except Exception:
            pass

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            f = conn.makefile(mode="rwb")
            line = f.readline()
            if not line:
                return
            try:
                req = json.loads(line.decode().strip())
            except Exception as e:
                self._send(f, ok=False, error=f"invalid json: {e}")
                return

            action = req.get("action")
            if action == "write":
                key = req.get("key")
                if not isinstance(key, str) or key == "":
                    self._send(f, ok=False, error="key required")
                    return
                DATA_STORE.write(key, req.get("value"))
                self._send(f, ok=True)
                return

            if action == "write_by_id":
                data_id = req.get("id")
                if not isinstance(data_id, str) or data_id == "":
                    self._send(f, ok=False, error="id required")
                    return
                key = DATA_STORE._id_to_key.get(data_id)  # Internal map already present
                if not key:
                    self._send(f, ok=False, error="id not found")
                    return
                DATA_STORE.write(key, req.get("value"))
                self._send(f, ok=True, key=key)
                return

            if action == "bulk_write_by_id":
                updates = req.get("updates")
                if not isinstance(updates, list):
                    self._send(f, ok=False, error="updates must be a list")
                    return
                
                results = []
                for update in updates:
                    data_id = update.get("id")
                    value = update.get("value")
                    if not isinstance(data_id, str) or data_id == "":
                        results.append({"id": data_id, "ok": False, "error": "id required"})
                        continue
                    
                    key = DATA_STORE._id_to_key.get(data_id)
                    if not key:
                        results.append({"id": data_id, "ok": False, "error": "id not found"})
                        continue
                    
                    try:
                        DATA_STORE.write(key, value)
                        results.append({"id": data_id, "ok": True, "key": key})
                    except Exception as e:
                        results.append({"id": data_id, "ok": False, "error": str(e)})
                
                self._send(f, ok=True, results=results)
                return

            self._send(f, ok=False, error="unknown action")
        except Exception as e:
            try:
                self._send(conn, ok=False, error=str(e))
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _send(self, f, **payload) -> None:
        try:
            data = (json.dumps(payload) + "\n").encode()
            if hasattr(f, "write"):
                f.write(data)
                f.flush()
            else:
                f.sendall(data)
        except Exception as e:
            print(f"IPC send error: {e}")


class IpcClient:
    def __init__(self, socket_path: Optional[str] = None) -> None:
        self.socket_path = socket_path or os.getenv("IPC_SOCKET_PATH", "/tmp/dataservice.sock")

    def _rpc(self, request: dict) -> dict:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self.socket_path)
        try:
            s.sendall((json.dumps(request) + "\n").encode())
            f = s.makefile("rb")
            line = f.readline()
            if not line:
                raise RuntimeError("empty response")
            return json.loads(line.decode())
        finally:
            s.close()

    def write(self, key: str, value) -> dict:
        return self._rpc({"action": "write", "key": key, "value": value})

    def write_by_id(self, data_id: str, value) -> dict:
        return self._rpc({"action": "write_by_id", "id": data_id, "value": value})

    def bulk_write_by_id(self, updates: list) -> dict:
        """
        Bulk update multiple data points by their UIDs
        
        Args:
            updates: List of dicts with 'id' and 'value' keys
            Example: [{"id": "abc123", "value": 42.5}, {"id": "def456", "value": 100}]
        
        Returns:
            dict with 'ok' and 'results' containing individual update results
        """
        return self._rpc({"action": "bulk_write_by_id", "updates": updates})


