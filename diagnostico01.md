# Diagnóstico de Procesos de Movimiento de Archivos en CatchEtude

Este documento explica en detalle los módulos y las funciones que intervienen al momento de realizar tres acciones principales sobre un archivo detectado en la aplicación **CatchEtude**:
1. **Mover un archivo al escoger una subcarpeta** de clasificación.
2. **Hacer "Keep"** (guardar el archivo de forma permanente/conflictos).
3. **Hacer "Apply Custom"** (aplicar un destino personalizado seleccionado por el usuario).

---

## Arquitectura General de Movimiento de Archivos
Para garantizar que la interfaz gráfica (UI) no se congele durante operaciones pesadas de lectura/escritura en disco (especialmente en transferencias entre unidades de disco distintas), la aplicación implementa un sistema asíncrono basado en hilos de Qt (`QThread` y `QObject` workers).

El componente central que coordina este flujo es `MainWindow` (en `main_window_mgr.py`), el cual interactúa con el gestor de estados `StateManager` (en `state_manager.py`) y despacha la tarea de entrada/salida (I/O) al hilo de fondo `FileMoveWorker` (en `file_worker_mgr.py`).

---

## 1. Mover un Archivo al Escoger una Subcarpeta

Este flujo se activa cuando el usuario tiene un archivo activo en pantalla y hace clic en uno de los botones de subcarpeta en el panel de clasificación de la izquierda.

### Paso a Paso y Secuencia de Llamadas

1. **Interacción del Usuario y Emisión de Señales (UI):**
   - El usuario hace clic en un botón de subcarpeta en la lista.
   - **Módulo:** `subfolder_list_mgr.py` o `selection_panel_mgr.py` (`SelectionPanel`).
   - **Evento:** Se emite la señal de Qt `subfolder_clicked(subfolder_name)`.

2. **Captura del Evento en la Ventana Principal:**
   - **Módulo:** `main_window_mgr.py` (`MainWindow`).
   - **Función:** Conectado a la función `self._move_to_subfolder(sub_name)`.
   - **Acciones dentro de `_move_to_subfolder`:**
     - Deshabilita temporalmente la UI para evitar clics repetidos: `self.selection_panel.set_subfolders_enabled(False)`.
     - Obtiene la selección actual del panel (tipo de movimiento y año): `sel = self.selection_panel.get_selection()`.
     - Construye el diccionario de decisión:
       ```python
       decision = {
           'action': 'move',
           'movement_type': sel['type'],
           'year': sel['year'],
           'sub': sub_name,
           'new_name': self.action_panel.get_new_name() or self.filepath.stem,
           'post_action': self.action_panel.get_post_action_mode(),
       }
       ```
     - Calcula el destino candidato llamando a la función `compute_destination(decision, self.filepath)` del módulo `fallback_utils.py`.
     - Verifica colisiones de nombres (si el archivo ya existe en el destino) llamando a `self._check_destination_collision(candidate)`.
     - Si no hay colisiones o el usuario decide renombrar/sobreescribir, se obtiene la ruta definitiva (`final_dest`) y se invoca a `self._start_move_task(decision, final_dest)`.

3. **Preparación y Delegación del Trabajo Asíncrono:**
   - **Función:** `MainWindow._start_move_task(decision, final_dest)` en `main_window_mgr.py`.
   - **Acciones:**
     - Pausa el servicio de caché de personajes temporalmente para evitar accesos concurrentes a archivos en tránsito: `send_character_service_command("pause")` del módulo `service_mgr.py`.
     - Lee los metadatos de tiempo originales del archivo de origen (`atime`, `mtime`, `ctime`).
     - Instancia la clase de transferencia asíncrona: `worker = FileMoveWorker(src, final_dest)` de `file_worker_mgr.py`.
     - Crea un hilo de ejecución secundario: `worker_thread = QtCore.QThread(self)`.
     - Mueve el worker al hilo de ejecución: `worker.moveToThread(worker_thread)`.
     - Notifica al motor de estados que se ha iniciado un movimiento en segundo plano llamando a `self.state_manager.start_background_move(src)` (en `state_manager.py`). Esto permite liberar el estado del sistema de colas principal de inmediato y regresar al estado `IDLE` para procesar el siguiente archivo, mientras la escritura en disco continúa de forma asíncrona.
     - Inicia el hilo: `worker_thread.start()`.

4. **Operación de Entrada/Salida en Segundo Plano (I/O Worker):**
   - **Módulo:** `file_worker_mgr.py` (`FileMoveWorker`).
   - **Función:** `run()`.
   - **Acciones:**
     - Asegura que exista el directorio destino: `self.dst.parent.mkdir(parents=True, exist_ok=True)`.
     - **Optimización de transferencia:**
       - Si el origen y destino están en la misma unidad de disco (`is_same_drive`), realiza un movimiento rápido y atómico usando `shutil.move()`.
       - Si están en unidades distintas, copia el archivo en bloques (chunks) de 1MB, actualizando la señal `progress` periódicamente, y finalmente elimina el origen usando `safe_unlink(self.src)`.
     - Restaura las marcas de tiempo originales (`atime`, `mtime`, `ctime`) usando `os.utime()` y `setctime_blocking()`.
     - Emite la señal `finished(success, final_path, status)`.

5. **Finalización y Registro del Historial:**
   - **Módulo:** `main_window_mgr.py` y `state_manager.py`.
   - **Acción:** La subfunción `on_finished(ok, copied_path, msg)` dentro de `_start_move_task` captura el fin de la transferencia:
     - Reanuda el servicio de personajes: `send_character_service_command("resume")`.
     - Llama a `self.state_manager.finalize_background_move(...)` en un hilo daemon.
     - **Dentro de `finalize_background_move`:**
       - Actualiza los tiempos de modificación de los directorios padre involucrados (`update_folder_mtime` de `utils.py`).
       - Registra el movimiento en el historial persistente a través del `HistoryManager` (`self._history.record_move(src, dst, src_meta)`).
       - Despacha las acciones posteriores configuradas (por ejemplo, abrir el archivo o la carpeta de destino).
       - Remueve el archivo de la lista de pendientes (`_pending` y `_queue_list`) y emite `queue_updated`.

---

## 2. Al Hacer "Keep"

La acción "Keep" se utiliza cuando el usuario decide mantener el archivo en una ubicación neutral de conflictos o seguimiento dentro del sistema (usualmente la carpeta configurada `CONFLICTS`).

### Paso a Paso y Secuencia de Llamadas

1. **Activación de la Acción:**
   - El usuario hace clic en el botón de aplicar acción en el panel derecho (`ActionPanel`) teniendo activada la casilla "Keep in Downloads" (Mantener en Descargas).
   - **Módulo:** `main_window_mgr.py` (`MainWindow`).
   - **Función:** `_on_move()`.

2. **Detección de la casilla "Keep" y Configuración de Decisión:**
   - En `_on_move()`, se evalúa `self.action_panel.is_keep_downloads()`. Al ser `True`:
     - Se verifica que el gestor de estados esté listo: `self.state_manager.current_state() == State.USER_DECIDING`.
     - Se define el diccionario de decisión:
       ```python
       decision = {
           "action": "keep",
           "new_name": self.action_panel.get_new_name() or self.filepath.stem,
           "post_action": self.action_panel.get_post_action_mode(),
       }
       ```
     - Se sanitiza el nombre de destino usando `sanitize_windows_filename(new_name)`.
     - Se resuelve la ruta destino resolviendo duplicados en la carpeta de conflictos:
       ```python
       dest = resolve_duplicate(config.CONFLICTS / (keep_name + self.filepath.suffix))
       ```

3. **Ejecución y Transferencia del Archivo:**
   - Al igual que en el flujo de subcarpetas, se llama a `self._start_move_task(decision, dest)`.
   - Esto delega de forma asíncrona la transferencia del archivo a un `FileMoveWorker` en un hilo separado de Qt.
   - Tras culminar satisfactoriamente, se restaura la fecha/hora original del archivo y se llama a `finalize_background_move(...)` en `state_manager.py` para registrar el movimiento en el historial y liberar la cola.

---

## 3. Al Hacer "Apply Custom"

Esta opción permite al usuario mover el archivo a una ubicación de destino completamente arbitraria elegida al vuelo a través de un diálogo nativo de selección de carpetas del sistema operativo.

### Paso a Paso y Secuencia de Llamadas

1. **Interacción del Usuario:**
   - El usuario hace clic en el botón "Aplicar Personalizado" (`btn_custom`) en el panel derecho.
   - **Módulo:** `action_panel_mgr.py` (`ActionPanel`).
   - **Evento:** Emite la señal `apply_custom_clicked`.

2. **Apertura del Diálogo y Elección del Directorio:**
   - **Módulo:** `main_window_mgr.py` (`MainWindow`).
   - **Función:** Conectado a la función `self._on_apply_custom()`.
   - **Acciones:**
     - Abre un selector de directorios del sistema operativo: `QFileDialog.getExistingDirectory(self, "Select Destination Folder", ...)`
     - Si el usuario cancela, el flujo termina de inmediato sin alterar el estado.
     - Si selecciona una ruta, se define el diccionario de decisión de tipo personalizado:
       ```python
       decision = {
           'action': 'move_custom',
           'custom_dir': folder,
           'new_name': self.action_panel.get_new_name() or self.filepath.stem,
           'post_action': self.action_panel.get_post_action_mode(),
       }
       ```

3. **Resolución de Conflictos en Destino Personalizado:**
   - Se limpia el nombre de archivo ingresado.
   - Se entra en un bucle que calcula el destino candidato:
     ```python
     candidate = Path(folder) / (newname + self.filepath.suffix)
     ```
   - Llama a `self._check_destination_collision(candidate, allow_retry=True)`.
   - Al tener `allow_retry=True`, si se detecta que el archivo ya existe, la aplicación presenta opciones adicionales al usuario, incluyendo la opción de **"Elegir otra carpeta"** (retorna `"retry"`).
   - Si retorna `"retry"`, el bucle se repite volviendo a presentar el selector de directorios `QFileDialog`.
   - Si el usuario acepta renombrar (`resolve_duplicate`) o el destino está libre, se rompe el bucle con la ruta de destino resuelta (`final_dest`).

4. **Despacho del Movimiento Asíncrono:**
   - Se invoca a `self._start_move_task(decision, final_dest)`.
   - Se ejecuta el `FileMoveWorker` asíncronamente en segundo plano.
   - Se reanuda la cola de la aplicación y se asienta el historial de forma asíncrona una vez terminada la transferencia a través de `finalize_background_move(...)`.
