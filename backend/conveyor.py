"""Owns the USB link to the DXL-IoT conveyor firmware, see firmware/README.md.

Only this thread touches the serial port. It sends PING while the belt runs and
never sends START on its own, including after a reconnect or board reset.
"""
import json
import queue
import threading
import time
from concurrent.futures import Future

import serial

PING_PERIOD = 0.2
STATUS_PERIOD_RUNNING = 0.5
STATUS_PERIOD_IDLE = 2.0
RECONNECT_DELAY = 3.0
BOOT_DELAY = 3.0  # AVR auto-reset on port open plus the startup bus scan.
MAX_SPEED = 300


class Conveyor(threading.Thread):
    def __init__(self, port):
        super().__init__(name="conveyor", daemon=True)
        self.port_name = port
        self._port = None
        self._requests = queue.Queue()
        self._closing = threading.Event()
        self._state_lock = threading.Lock()
        self._info = {"port": port, "enabled": bool(port), "connected": False,
                       "running": False, "busy": False, "error": None, "status": {}}
        self._belt_on = False  # Our own START was confirmed and not yet stopped.

    # Called from HTTP threads.

    def snapshot(self):
        with self._state_lock:
            return json.loads(json.dumps(self._info))

    def start_belt(self, speed, timeout=20):
        if not 1 <= abs(speed) <= MAX_SPEED:
            return {"ok": False, "error": f"Скорость должна быть от 1 до {MAX_SPEED} по модулю"}
        return self._request("start", speed, timeout)

    def stop_belt(self, timeout=10):
        return self._request("stop", None, timeout)

    def close(self):
        self._closing.set()
        if self.is_alive():
            self.join(timeout=5)

    def _request(self, action, arg, timeout):
        if not self.port_name:
            return {"ok": False, "error": "Конвейер отключён параметром --no-conveyor"}
        with self._state_lock:
            if not self._info["connected"]:
                return {"ok": False, "error": "Нет связи с контроллером"}
        future = Future()
        self._requests.put((action, arg, future))
        try:
            return future.result(timeout)
        except TimeoutError:
            return {"ok": False, "error": "Контроллер не ответил вовремя"}

    # Serial thread.

    def _set(self, **changes):
        with self._state_lock:
            self._info.update(changes)

    def run(self):
        if not self.port_name:
            return
        while not self._closing.is_set():
            try:
                self._connect()
                self._serve()
            except (serial.SerialException, OSError, TimeoutError) as exc:
                self._belt_on = False
                self._set(connected=False, running=False, busy=False,
                          error=f"Нет связи с контроллером: {exc}")
            finally:
                self._disconnect()
            self._fail_requests("Нет связи с контроллером")
            self._closing.wait(RECONNECT_DELAY)

    def _connect(self):
        self._port = serial.Serial(self.port_name, 115200, timeout=0.05,
                                   write_timeout=0.5, exclusive=True)
        time.sleep(BOOT_DELAY)
        self._port.reset_input_buffer()
        self._belt_on = False
        self._set(connected=True, running=False, error=None)
        self._command("STATUS")

    def _disconnect(self):
        if self._port is None:
            return
        try:
            if self._port.is_open:
                self._command("STOP")
        except (serial.SerialException, OSError, TimeoutError):
            pass
        finally:
            self._port.close()
            self._port = None
            self._belt_on = False
            self._set(connected=False, running=False)

    def _fail_requests(self, error):
        while True:
            try:
                _, _, future = self._requests.get_nowait()
            except queue.Empty:
                return
            future.set_result({"ok": False, "error": error})

    def _serve(self):
        last_ping = last_status = 0.0
        while not self._closing.is_set():
            try:
                action, arg, future = self._requests.get(timeout=0.02)
            except queue.Empty:
                pass
            else:
                self._set(busy=True)
                try:
                    future.set_result(self._do_start(arg) if action == "start" else self._do_stop())
                finally:
                    self._set(busy=False)
            now = time.monotonic()
            if self._belt_on and now - last_ping >= PING_PERIOD:
                last_ping = now
                self._command("PING", timeout=0.6)
            period = STATUS_PERIOD_RUNNING if self._belt_on else STATUS_PERIOD_IDLE
            if now - last_status >= period:
                last_status = now
                self._command("STATUS", timeout=1)
            self._read_pending()

    def _do_start(self, speed):
        if not self._belt_on:
            # INIT is refused while running; a running belt only changes speed.
            ok, error = self._command("INIT", timeout=10)
            if not ok:
                return {"ok": False, "error": error}
        ok, error = self._command(f"START {speed}", timeout=5)
        if not ok:
            self._belt_on = False
            self._set(running=False, error=error)
            return {"ok": False, "error": error}
        self._belt_on = True
        self._set(running=True, error=None)
        return {"ok": True}

    def _do_stop(self):
        self._belt_on = False
        self._set(running=False)
        ok, error = self._command("STOP", timeout=5)
        self._set(error=None if ok else error)
        return {"ok": ok, "error": error}

    def _command(self, command, timeout=2.0):
        """Returns (ok, error). Unrelated lines read meanwhile are handled too."""
        word = command.split()[0]
        self._port.write((command + "\n").encode("ascii"))
        self._port.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._readline()
            if line is None:
                continue
            if word == "STATUS" and line.startswith("STATUS "):
                return True, None
            if line == "OK " + word:
                return True, None
            if line.startswith(f"ERR {word}"):
                return False, line
        raise TimeoutError(f"нет ответа на {word}")

    def _read_pending(self):
        while self._port.in_waiting:
            self._readline()

    def _readline(self):
        raw = self._port.readline()
        if not raw:
            return None
        line = raw.decode("ascii", errors="replace").strip()
        if not line:
            return None
        if line.startswith("STATUS "):
            try:
                self._on_status(json.loads(line.removeprefix("STATUS ")))
            except ValueError:
                self._set(error=f"Повреждённая строка от контроллера: {line[:60]}")
        elif line.startswith("READY"):
            self._on_fault("Контроллер перезапустился, лента остановлена")
        elif line.startswith("ERR ") and line.split()[1] in ("HOST_TIMEOUT", "MOTOR_LINK_OR_TORQUE"):
            self._on_fault(f"Контроллер остановил ленту: {line}")
        return line

    def _on_status(self, status):
        changes = {"status": status}
        if self._belt_on and not status.get("running"):
            self._belt_on = False
            changes.update(running=False, error="Контроллер сообщил об остановке ленты")
        if status.get("stop_pending"):
            changes["error"] = "Остановка мотора не подтверждена (stop_pending)"
        self._set(**changes)

    def _on_fault(self, message):
        self._belt_on = False
        self._set(running=False, error=message)
