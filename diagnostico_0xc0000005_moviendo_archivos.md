# The Fall `0xc0000005` with applied solutions

Este diagnóstico ahora queda acompañado por mitigaciones aplicadas en el código. `0xc0000005` es una excepción nativa de Windows; por eso las soluciones priorizan reducir carreras entre Qt/PyQt, APIs Win32, miniaturas del Shell y movimientos físicos de archivos.

## Soluciones aplicadas

### 1. Ciclo de vida de señales PyQt y workers

Archivo: `background_move_mgr.py`

- `BackgroundMoveManager` ahora conserva explícitamente tanto el `FileMoveWorker` como su `FileMoveSignals` mientras el trabajo está activo.
- Se agregó `stop_accepting_new_moves()` para impedir trabajos nuevos durante el cierre.
- Se agregó `wait_for_done()` para esperar al `QThreadPool` antes de permitir la destrucción final de la interfaz.

Esto reduce la ventana donde pueden quedar eventos de Qt apuntando a receptores que ya comenzaron a destruirse.

### 2. UI protegida durante cierre y menor presión de eventos

Archivos: `main_window_mgr.py` y `file_worker_mgr.py`

- La ventana mantiene una bandera `_closing` para ignorar eventos tardíos de workers.
- `closeEvent()` bloquea nuevos movimientos, espera el pool y desconecta señales antes de aceptar el cierre.
- Los slots de progreso/finalización están declarados con `@QtCore.pyqtSlot`.
- `FileMoveWorker` limita las emisiones de progreso a cambios relevantes de porcentaje o intervalos temporales, reduciendo eventos acumulados en la cola de Qt.

### 3. Fallo de restauración de timestamps sin pérdida de archivo

Archivos: `file_worker_mgr.py` y `main_window_mgr.py`

- `_restore_timestamps()` ya no oculta errores críticos de timestamp.
- Si falla la restauración de fecha, el worker emite `TIMESTAMP_RESTORE_FAILED` y no borra el destino.
- La UI pregunta si se desea reintentar la restauración de fecha.
- Si el reintento falla o el usuario no quiere reintentar, el archivo movido se conserva y la operación se finaliza para no perder el archivo.

### 4. Eliminación del riesgo de `SHFileOperationW`

Archivo: `utils.py`

- Se eliminó `move_file_shfileop()` y la estructura `SHFILEOPSTRUCTW` basada en `ctypes`.
- También se removió la carga global de `shell32` usada exclusivamente por esa función.

Esto elimina una ruta directa hacia violaciones de acceso por firmas o estructuras Win32 incorrectas en movimientos de archivo.

### 5. Miniaturas/iconos del Shell desacoplados de archivos no accesibles

Archivo: `ui_utils_mgr.py`

- Antes de pedir miniaturas o iconos de un archivo, la UI valida que la ruta exista y sea legible.
- Si el archivo ya no está disponible o está en transición, se usa un icono genérico en lugar de llamar a las APIs de miniatura.

Esto evita invocar Shell/codecs sobre rutas que están siendo movidas o ya desaparecieron.

### 6. Concurrencia configurable y modo conservador por defecto

Archivos: `config.py` y `background_move_mgr.py`

- Se agregó `MAX_CONCURRENT_MOVES` a la configuración.
- `BackgroundMoveManager` usa ese valor para configurar `_max_concurrent` y el `QThreadPool`.
- El valor por defecto es `1`, que es el modo más conservador para aislar condiciones de carrera.

### 7. Finalización lógica en el hilo principal

Archivo: `main_window_mgr.py`

- `_on_background_move_finished()` ya no manda `finalize_move()` a `run_in_threadpool()`.
- La finalización que toca `StateManager`, historial, notifier y UI se ejecuta desde el slot del hilo principal.

Con esto el estado global tiene un único propietario efectivo durante la finalización del movimiento.

## Riesgo todavía pendiente de arquitectura mayor

Los watchers y servicios externos (`watcher_mgr.py`, `character_service.pyw`, `overworld_service.pyw`) todavía dependen de la coordinación por pausa/reanudación existente. Para una segunda fase convendría agregar un estado compartido de "archivo en transición" que todos los servicios consulten antes de escanear o pedir miniaturas.
