"""
App Signals module - Centralized Qt signals for communication between components.
Módulo App Signals: señales de Qt centralizadas para la comunicación entre componentes.
"""

from PyQt6 import QtCore

class AppSignals(QtCore.QObject):
    """
    Container for application-wide signals.
    Contenedor para señales de toda la aplicación.
    """
    # Signal emitted when a new file is ready to be presented in the UI
    file_detected = QtCore.pyqtSignal(str)  # Señal emitida cuando un nuevo archivo está listo para ser presentado en la interfaz
    request_decision = QtCore.pyqtSignal() # Placeholder for future expansion
    queue_empty = QtCore.pyqtSignal() # state manager -> UI
    queue_updated = QtCore.pyqtSignal(list, str) # Emitted when the queue changes. Params: (list of Path, active_file_path or "")
    warning_message = QtCore.pyqtSignal(str)