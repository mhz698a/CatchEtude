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
plugins/                 directorio contiguo para plugins locales (.py / .pyw)
plugin_templates/        plantillas de plugins y guía para desarrolladores
```

## Sistema de Plugins
CatchEtude incluye un sistema de extensiones locales explícitamente confiables:
- **Ubicación de plugins**: Los plugins son archivos individuales `.py` o `.pyw` situados directamente en `<APP_DIR>/plugins/`.
- **Instalación**: Copiar o arrastrar un archivo `.py`/`.pyw` a la carpeta de plugins.
- **Manifiesto**: Cada plugin contiene un bloque manifiesto TOML embebido en comentarios al inicio del archivo.
- **Persistencia y Configuración**: El estado de activación y las configuraciones de los plugins se guardan aisladamente en `%APPDATA%\CatchEtude\plugins-state.json` y `%APPDATA%\CatchEtude\plugins-config\<id>.json`.
- **Aislamiento y Seguridad**: Cada plugin y servicio paralelo se ejecuta como un proceso hijo independiente (`QProcess`). Los plugins de terceros ejecutan código Python con los permisos del usuario de Windows. Se requiere confirmación explícita de confianza antes de habilitar un plugin.

Cómo encaja: al arrancar catchetude.pyw se inicializan logging y servicios (service_mgr.start_*), se crea StateManager y AppSignals, se lanza WatcherThread que usa watchdog.observers para detectar nuevos ficheros en Downloads. Las utilidades de utils.py realizan flattening, comprobación de locks y configuración DWM; los movimientos de archivos se ejecutan con workers de fondo. service_mgr gestiona IPC por QLocalSocket y mutex Win32 para coordinar servicios auxiliares.

## Cómo ejecutarlo (mínimo)
Requiere python 3.12+
Requisitos detectados: Python en Windows, PyQt6, watchdog, pywin32, send2trash. No hay requirements.txt; conviene crear uno con versiones pinneadas.
Comandos mínimos (desde PowerShell/CMD en Windows):
```bash
# intala dependencias primero
pip install -r requirements.txt

# ejecutar la app
python catchetude.pyw
```
Notas: tomllib se usa en config.py (disponible en Python 3.11); para Python <3.11 debe añadirse dependencia tomli o ajustar load_settings.

**NOTA CRITICA**: Este es un proyecto personal de automatización diseñado específicamente para ejecutarse en entornos locales parametrizados.
