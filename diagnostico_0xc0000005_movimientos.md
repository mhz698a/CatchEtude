# Diagnóstico: posibles puntos de violación de acceso 0xc0000005 al mover archivos

Este diagnóstico identifica los puntos del flujo de movimiento donde una caída nativa de Windows
(`0xc0000005`, access violation) puede ocurrir aunque el código Python esté dentro de `try/except`.
La razón principal es que `0xc0000005` suele originarse en código nativo llamado desde Python
(Win32, COM, GDI, extensiones de PyQt o shell extensions); esas fallas pueden terminar el proceso
sin convertirse en una excepción Python recuperable.

## Flujo principal de movimiento

1. `MainWindow._on_move`, `_move_to_subfolder` y `_on_apply_custom` calculan el destino final y llaman a
   `MainWindow._start_move_task`.
2. `_start_move_task` valida bloqueo, captura metadatos y encola el movimiento en `BackgroundMoveManager`.
3. `BackgroundMoveManager._process_queue` crea un `FileMoveWorker` y lo ejecuta en un `QThreadPool`.
4. `FileMoveWorker.run` mueve el archivo con `shutil.move` si está en la misma unidad, o copia por chunks
   y elimina el origen si está en otra unidad.
5. Después de transferir, `_restore_timestamps` usa `os.utime` y `setctime_blocking` para restaurar marcas
   de tiempo; `setctime_blocking` llama a APIs Win32 mediante `ctypes`.
6. Al finalizar, las señales Qt actualizan la cola visual y `BackgroundMoveManager.finalize_move` registra
   historial, actualiza carpetas y opcionalmente dispara una acción posterior.

## Zonas de mayor riesgo de 0xc0000005

### 1. Restauración de fecha de creación con Win32 vía `ctypes`

**Archivos implicados:** `file_worker_mgr.py`, `wctime.py`.

`FileMoveWorker._restore_timestamps` llama a `setctime_blocking` después de mover/copiar el archivo. Esa
función abre un handle con `CreateFileW`, llama a `SetFileTime` y cierra el handle con `CloseHandle`.
Aunque las firmas están declaradas, este es el punto más directo donde el flujo de movimiento entra en
código nativo Win32 mediante `ctypes`.

**Por qué puede producir 0xc0000005:**

- Si una firma `ctypes` no coincide exactamente con la ABI esperada o un handle inválido se usa en una API
  nativa, el proceso puede caer con access violation.
- Si el archivo está en OneDrive, red, antivirus o shell extension y el handle cambia de estado durante la
  operación, puede aparecer comportamiento nativo no recuperable.
- El movimiento en misma unidad usa `shutil.move` y después toca timestamps; en unidad distinta, la copia
  termina, se hace `fsync`, y también se toca creation time. Por tanto, el riesgo aplica a ambos caminos.

**Indicadores en logs antes de la caída:**

- `[FileMoveWorker] Same-drive detected...`
- `[FileMoveWorker] Cross-drive detected...`
- mensajes inmediatamente antes/después de `Timestamp restore failed` o ausencia de log posterior al move.

**Mitigación sugerida:** aislar temporalmente `setctime_blocking` detrás de un flag de configuración o mover
la restauración de creation time a un proceso auxiliar para que una caída nativa no cierre la UI principal.

### 2. Señales Qt emitidas desde workers del `QThreadPool`

**Archivos implicados:** `file_worker_mgr.py`, `background_move_mgr.py`, `main_window_mgr.py`,
`queue_movings_widget.py`.

`FileMoveWorker` emite `progress` y `finished` desde un `QRunnable`. `BackgroundMoveManager` conserva
referencias a `worker` y `worker.signals`, conecta lambdas, emite señales hacia la UI y limpia referencias
cuando finaliza.

**Por qué puede producir 0xc0000005:**

- PyQt es una capa nativa sobre Qt/C++; si un `QObject` receptor se destruye mientras todavía hay eventos
  encolados desde un worker, puede producirse una caída nativa.
- El cierre de la aplicación intenta esperar al `QThreadPool`, pero si hay eventos Qt pendientes o señales
  emitidas durante cierre, el riesgo existe.
- La cola visual se modifica en `_on_background_move_started`, `_on_background_move_progress` y
  `_on_background_move_finished`; si el widget ya fue destruido o está en proceso de cierre, la caída puede
  no aparecer como excepción Python.

**Indicadores en logs antes de la caída:**

- `Starting prioritized background move...`
- `Finished background move...`
- la caída ocurre al cerrar/reiniciar mientras hay movimientos activos o justo al terminar uno.

**Mitigación sugerida:** mantener la barrera de cierre estricta, desconectar señales solo después de drenar
la cola de eventos, y considerar que `finished` haga `QTimer.singleShot(0, ...)` hacia el hilo principal antes
de limpiar referencias o arrancar el siguiente movimiento.

### 3. Generación de thumbnails del Shell mientras el archivo se mueve

**Archivos implicados:** `shell_video_thumbnail_pyqt6.py`, `action_panel_mgr.py`.

La vista previa puede pedir thumbnails de video al Shell de Windows. Este módulo usa COM/GDI mediante
`ctypes`: `SHCreateItemFromParsingName`, `IShellItemImageFactory.GetImage`, `GetObjectW`, `GetDIBits`,
`DeleteObject`, `Release` y `CoUninitialize`.

**Por qué puede producir 0xc0000005:**

- Los thumbnail providers son shell extensions nativas de terceros o del sistema; una caída dentro de ese
  proveedor puede cerrar el proceso Python.
- El archivo puede desaparecer o cambiar de ubicación mientras se genera la vista previa.
- Hay punteros COM y `HBITMAP` administrados manualmente; si el proveedor devuelve un objeto inconsistente,
  el fallo puede ser nativo.

**Indicadores en logs antes de la caída:**

- La caída ocurre al cargar preview de video, al seleccionar rápidamente otro archivo, o inmediatamente antes
  de mover un video.

**Mitigación sugerida:** desactivar thumbnails del Shell durante movimientos activos, o generar thumbnails en
un proceso separado. Si al desactivar thumbnails desaparece el 0xc0000005, esta zona queda confirmada.

### 4. Movimiento físico con `shutil.move` sobre rutas sincronizadas o con extensiones de shell

**Archivos implicados:** `file_worker_mgr.py`, `utils.py`.

`shutil.move` delega en operaciones del sistema de archivos. En unidad distinta, el código hace lectura y
escritura manual, luego borra el origen con `safe_unlink`.

**Por qué puede producir 0xc0000005:**

- El código Python debería lanzar `OSError` o `PermissionError`, no access violation. Si aparece 0xc0000005
  durante esta etapa, normalmente apunta a drivers, antivirus, OneDrive, codecs/handlers o extensiones nativas
  que interceptan operaciones de archivo.
- `is_file_locked` solo prueba apertura `r+b`; no garantiza que otro proceso no bloquee el archivo entre la
  validación y el movimiento.

**Indicadores en logs antes de la caída:**

- El último log es `Transfer started`, `Same-drive detected`, `Cross-drive detected`, o progreso parcial.

**Mitigación sugerida:** registrar tamaño, unidad, destino y timestamps antes/después de cada llamada crítica;
probar con antivirus/OneDrive pausados; y comparar movimientos en carpetas locales simples.

### 5. Acciones posteriores al movimiento y servicios auxiliares

**Archivos implicados:** `main_window_mgr.py`, `background_move_mgr.py`, `send_command.py`.

Antes de mover se pausa el servicio de personajes y al terminar se reanuda. Además, `finalize_move` puede
emitir una acción posterior para abrir archivo o carpeta.

**Por qué puede producir 0xc0000005:**

- Abrir un archivo recién movido puede activar shell, codecs, reproductores o handlers nativos.
- La emisión de señales hacia objetos Qt durante cierre o mientras se procesan servicios auxiliares también
  puede generar fallos nativos.

**Mitigación sugerida:** reproducir con `post_action = none`; si desaparece, investigar apertura posterior y
servicios auxiliares antes que el movimiento físico.

## Orden recomendado para aislar la causa

1. Reproducir con thumbnails del Shell desactivados para videos.
2. Reproducir con restauración de creation time desactivada o diferida.
3. Reproducir con `post_action = none`.
4. Reproducir moviendo entre carpetas locales no sincronizadas por OneDrive y sin antivirus escaneando.
5. Si solo falla en cierre/reinicio, enfocar la investigación en señales Qt y vida útil de widgets/receivers.
6. Si solo falla con ciertos formatos de video, enfocar en thumbnails, codecs y shell extensions.

## Conclusión

Los puntos más sospechosos no son las llamadas Python puras de mover/copiar, sino las transiciones a código
nativo: `setctime_blocking` en `wctime.py`, thumbnails COM/GDI en `shell_video_thumbnail_pyqt6.py`, y señales
PyQt cruzando desde `QThreadPool` hacia widgets durante finalización o cierre.
