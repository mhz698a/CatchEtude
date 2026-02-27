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
    # Señal emitida cuando un nuevo archivo está listo para ser presentado en la interfaz
    file_detected = QtCore.pyqtSignal(str) 
    
    # Placeholder for future expansion
    request_decision = QtCore.pyqtSignal()

    queue_empty = QtCore.pyqtSignal()       # state manager -> UI
    
    # Emitted when the queue changes. Params: (list of Path, active_file_path or "")
    queue_updated = QtCore.pyqtSignal(list, str)