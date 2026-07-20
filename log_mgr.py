# log_mgr.py
"""
Log Manager module - Captures logs and emits signals for the UI Log Viewer.
Módulo Log Manager: captura registros y emite señales para el Visor de Registros de la UI.
"""

import logging
import traceback
import json
import threading
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalSocket

# Custom logging level for character list activities
CHARS_LEVEL = 25
OVERWORLD_LEVEL = 21
logging.addLevelName(CHARS_LEVEL, "CHARS")
logging.addLevelName(OVERWORLD_LEVEL, "OVERWORLD")


class LogSignals(QObject):
    """Signals for the log viewer."""
    new_log = pyqtSignal(str, str) # level, message

_log_history = []
_last_thread_log = {}

class QtLogHandler(logging.Handler):
    """Custom logging handler that emits Qt signals and sends to watchdog."""
    def __init__(self, signals: LogSignals):
        super().__init__()
        self.signals = signals

    def _send_to_watchdog(self, level, message):
        socket = QLocalSocket()
        socket.connectToServer("CatchEtudeLogServer")
        if socket.waitForConnected(100):
            data = json.dumps({"cmd": "log", "level": level, "message": message})
            socket.write(data.encode('utf-8'))
            socket.waitForBytesWritten(100)
            socket.disconnectFromServer()

    def emit(self, record):
        msg = self.format(record)
        level = "INFO"
        if record.levelno >= logging.ERROR:
            level = "ERROR"
            if record.exc_info:
                msg += "\n" + "".join(traceback.format_exception(*record.exc_info))
        elif record.levelno >= logging.WARNING:
            level = "WARN"
        elif record.levelno == CHARS_LEVEL:
            level = "CHARS"
        elif record.name.startswith("overworld") or record.levelno == OVERWORLD_LEVEL:
            level = "OVERWORLD"
        
        _last_thread_log[record.threadName] = msg
        _log_history.append((level, msg))
        self.signals.new_log.emit(level, msg)
        self._send_to_watchdog(level, msg)

log_signals = LogSignals()

def get_log_history():
    return _log_history

def log_char(message: str):
    """Convenience function to log character-related activities."""
    logging.log(CHARS_LEVEL, message)
    
import functools

def safe_thread_logger(process_name: str):
    """
    Decorator for threads/functions to catch exceptions and log detailed tracebacks safely.
    Ensures background exceptions are sent to the central log server.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                tb = traceback.format_exc()
                logging.error(f"[{process_name}] Critical error in background thread/task: {e}\n{tb}")
        return wrapper
    return decorator

def log_overworld(message: str):
    logging.log(OVERWORLD_LEVEL, message)

def setup_logging(log_path):
    """Sets up global logging with the custom Qt handler."""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # File handler
    fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(fh)

    # Qt handler
    qh = QtLogHandler(log_signals)
    qh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(qh)

    # Stream handler
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(sh)


_thread_reporter_timer = None

def start_thread_reporter(process_name: str, parent_obj=None):
    global _thread_reporter_timer
    from PyQt6.QtCore import QTimer
    from PyQt6.QtNetwork import QLocalSocket

    def send_threads():
        threads_info = []
        try:
            size_bytes = threading.stack_size()
            if size_bytes == 0:
                size_bytes = 1024 * 1024  # 1MB default
            size_mb = size_bytes / (1024 * 1024)

            for t in threading.enumerate():
                t_name = t.name
                last_log = _last_thread_log.get(t_name, "No logs yet")
                threads_info.append({
                    "process": process_name,
                    "ident": t.ident or 0,
                    "name": t_name,
                    "memory": f"{size_mb:.2f} MB",
                    "last_log": last_log
                })
        except Exception as e:
            logging.debug(f"Error enumerating threads in reporter: {e}")
            return

        # Send via QLocalSocket
        socket = QLocalSocket()
        socket.connectToServer("CatchEtudeLogServer")
        if socket.waitForConnected(150):
            payload = {
                "cmd": "threads",
                "process": process_name,
                "threads": threads_info
            }
            socket.write(json.dumps(payload).encode('utf-8'))
            socket.waitForBytesWritten(150)
            socket.disconnectFromServer()

    # Use a QTimer to run periodically in the main event loop
    _thread_reporter_timer = QTimer(parent_obj)
    _thread_reporter_timer.setInterval(2000) # Every 2 seconds
    _thread_reporter_timer.timeout.connect(send_threads)
    _thread_reporter_timer.start()
