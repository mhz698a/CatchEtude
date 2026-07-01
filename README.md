# 👁️ CatchEtude

## What this is
CatchEtude es una aplicación de escritorio exclusivo para Windows (PyQt6) que actúa como watchdog/organizador para la carpeta Downloads, arrancando servicios auxiliares (watchdog, character, overworld) y una UI principal para gestionar pendientes y colas.

### Stack
- Language(s): Python (100%)
- Framework / runtime: PyQt6 GUI app (cliente de escritorio Windows)
- Notable libraries (detectadas por imports): watchdog, PyQt6, pywin32 (win32event/win32api), send2trash, tomllib (o tomli si se necesita compatibilidad), plus uso de ctypes para llamadas Win32 nativas.

## How it's organized
Raíz (archivos y carpetas relevantes):
```text
assets/                  recursos (iconos, audio: catchetude-icon.png, alarm.mp3, etc.)
README.md                descripción mínima
catchetude.pyw           punto de entrada principal (init, timers, UI)
service_mgr.py           gestión de servicios paralelos, mutexes y sockets locales
watcher_mgr.py           observador de Downloads (watchdog) y lógica de estabilidad de archivos
utils.py                 utilidades para mover/borra/flatten, comprobación de locks, DWM
config.py                rutas, settings, carga/propagación de settings
+ muchos módulos manager: main_window_mgr.py, watcher_mgr.py, log_mgr.py, character_mgr.py, etc.
```

Cómo encaja: al arrancar catchetude.pyw se inicializan logging y servicios (service_mgr.start_*), se crea StateManager y AppSignals, se lanza WatcherThread que usa watchdog.observers para detectar nuevos ficheros en Downloads. Las utilidades de utils.py realizan flattening y movimientos (uso de SHFileOperation/ctypes). service_mgr gestiona IPC por QLocalSocket y mutex Win32 para coordinar servicios auxiliares.

## Cómo ejecutarlo (mínimo)
Requisitos detectados: Python en Windows, PyQt6, watchdog, pywin32, send2trash. No hay requirements.txt; conviene crear uno con versiones pinneadas.
Comandos mínimos (desde PowerShell/CMD en Windows):
```bash
# intala dependencias primero
pip install -r requirements.txt

# ejecutar la app
python catchetude.pyw
```
Notas: tomllib se usa en config.py (disponible en Python 3.11); para Python <3.11 debe añadirse dependencia tomli o ajustar load_settings.
