# Diagnóstico actualizado: posibles puntos de `0xc0000005` al mover archivos

Este diagnóstico se limita al momento de mover archivos. El escenario de cierre, reinicio o destrucción de
widgets se deja fuera de este documento para analizarlo por separado.

`0xc0000005` es una violación de acceso nativa. En este proyecto, si aparece durante un movimiento, lo más
probable es que no venga de una excepción Python pura, sino de una llamada a código nativo activada por el
flujo de movimiento: Win32 vía `ctypes`, COM/GDI del Shell de Windows, Qt/PyQt o componentes externos como
OneDrive, antivirus, codecs, drivers o shell extensions.

## Flujo real al mover

1. La UI calcula el destino en `MainWindow._on_move`, `_move_to_subfolder` o `_on_apply_custom`.
2. `MainWindow._start_move_task` toma el archivo activo, valida si parece bloqueado, suspende la vista previa
   del archivo actual y encola el movimiento.
3. `BackgroundMoveManager._process_queue` crea un `FileMoveWorker`, conserva referencias vivas al worker y a
   sus señales, conecta progreso/finalización y lo arranca en su `QThreadPool`.
4. `FileMoveWorker.run` hace una de dos rutas:
   - misma unidad: `shutil.move`;
   - distinta unidad: copia por bloques, `flush`, `fsync` y luego elimina el origen con `safe_unlink`.
5. Tras transferir, `_restore_timestamps` restaura `atime`/`mtime` con `os.utime` y restaura `ctime` llamando
   a `setctime_blocking` dentro de un hilo auxiliar dedicado.
6. Al terminar, `finished` se procesa con conexión encolada y salto de evento de Qt antes de limpiar workers,
   emitir `move_finished` y arrancar el siguiente movimiento.

## Puntos donde todavía puede ocurrir `0xc0000005`

### 1. Restauración de `ctime` mediante Win32/`ctypes`

**Riesgo:** alto.

La restauración de fecha de creación sigue siendo el punto nativo más directo del movimiento. Ahora se ejecuta
en un hilo auxiliar dedicado, lo cual reduce el acoplamiento con el `QRunnable`, pero no convierte una access
violation nativa en una excepción Python recuperable si el fallo ocurre dentro de `kernel32` o de una capa del
sistema de archivos.

**Ruta implicada:**

- `FileMoveWorker._restore_timestamps` → `_restore_creation_time_in_helper_thread` → `setctime_blocking`.
- `setctime_blocking` → `CreateFileW` → `SetFileTime` → `CloseHandle`.

**Cuándo sospechar de este punto:**

- El archivo ya fue copiado o movido, pero la app cae justo después de la transferencia.
- El último log visible está cerca de `Same-drive move`, `Cross-drive move`, `Copy finished` o restauración de
  timestamps.
- El problema ocurre más con rutas sincronizadas, unidades externas, red, OneDrive o archivos vigilados por
  antivirus.

**Qué probar para confirmarlo:**

1. Desactivar temporalmente solo la restauración de `ctime` y dejar `os.utime` activo.
2. Comparar movimientos en carpeta local simple contra OneDrive/red/unidad externa.
3. Registrar un log inmediatamente antes y después de `_restore_creation_time_in_helper_thread`.

### 2. Thumbnails del Shell que siguen ejecutándose cuando el usuario inicia el movimiento

**Riesgo:** medio-alto si el archivo es video o formato manejado por extensiones del Shell.

La vista previa se genera al cargar el archivo. Ahora existe una generación de preview y una suspensión cuando
inicia el movimiento, por lo que un resultado obsoleto ya no debería aplicarse a la UI si el archivo desaparece,
cambia la selección o empieza a moverse. Sin embargo, si el Shell/thumbnail provider ya entró en código nativo
antes de la suspensión, una caída dentro del provider puede tumbar el proceso.

**Ruta implicada:**

- `ActionPanel.load_preview` → `get_shell_thumbnail_pixmap` → `get_shell_thumbnail_image`.
- `get_shell_thumbnail_image` usa `SHCreateItemFromParsingName`, `IShellItemImageFactory.GetImage`, `GetDIBits`,
  `DeleteObject`, `Release` y COM/GDI.

**Cuándo sospechar de este punto:**

- La caída ocurre al mover videos o archivos con preview del Shell.
- El usuario mueve el archivo inmediatamente después de que aparece en la UI, mientras la miniatura puede seguir
  generándose.
- Desactivar thumbnails del Shell reduce o elimina el fallo.

**Qué probar para confirmarlo:**

1. Forzar que `should_use_shell_thumbnail` devuelva `False` para videos y repetir el movimiento.
2. Probar los mismos archivos con vista previa ya cargada y esperando unos segundos antes de mover.
3. Probar en una carpeta local sin OneDrive y sin codecs/shell extensions de terceros si es posible.

### 3. Operación física de movimiento/copia y hooks del sistema de archivos

**Riesgo:** medio.

`shutil.move`, lectura/escritura por bloques, `fsync` y `unlink` deberían producir excepciones Python como
`OSError` o `PermissionError`. Si aparece `0xc0000005` exactamente durante esa etapa, lo más probable es que
la caída venga de código nativo externo que intercepta operaciones de archivo.

**Posibles actores externos:**

- OneDrive o proveedores de sincronización.
- Antivirus/EDR.
- Drivers de unidades externas o red.
- Shell extensions que inspeccionan el archivo al crearse o moverse.
- Codecs/handlers que reaccionan a metadatos o thumbnails.

**Cuándo sospechar de este punto:**

- El último log visible es `Transfer started`, `Same-drive detected`, `Cross-drive detected` o progreso parcial.
- El fallo depende del destino o de la unidad, no del tipo de archivo.
- El archivo de destino queda parcial o el origen queda sin borrar en movimientos entre unidades.

**Qué probar para confirmarlo:**

1. Mover el mismo archivo entre dos carpetas locales del mismo disco.
2. Repetir hacia OneDrive/red/unidad externa.
3. Pausar antivirus/OneDrive solo para la prueba controlada.
4. Registrar logs antes/después de `shutil.move`, apertura de origen/destino, `fsync` y `safe_unlink`.

### 4. Señales de progreso y `finished` durante la finalización del movimiento

**Riesgo:** medio-bajo tras la mitigación, pero todavía relevante.

La finalización ya se reforzó: `finished` usa conexión encolada y luego `QTimer.singleShot(0, ...)` para que la
limpieza y emisión de `move_finished` ocurran en el event loop del manager/UI. Esto reduce el riesgo de tocar
estado compartido desde el stack del `QRunnable`.

Aun así, el flujo sigue entrando en Qt/PyQt nativo: se emiten señales, se actualiza la cola visual y se llama a
`finalize_move`. Si una señal llega en un momento inesperado o hay un bug nativo en la capa Qt/PyQt, la caída
puede manifestarse como `0xc0000005`.

**Cuándo sospechar de este punto:**

- La transferencia termina correctamente, pero la caída ocurre justo al retirar el elemento de la cola visual o
  al comenzar el siguiente movimiento.
- Con un solo movimiento funciona, pero falla con varios movimientos concurrentes o encadenados.
- El último log visible es `Finished background move`.

**Qué probar para confirmarlo:**

1. Forzar `MAX_CONCURRENT_MOVES = 1` y repetir.
2. Repetir con varios archivos grandes para aumentar eventos de progreso.
3. Agregar logs al inicio y fin de `_handle_worker_finished`, `_on_background_move_finished` y `finalize_move`.

### 5. Acciones posteriores al movimiento (`post_action`)

**Riesgo:** medio si se abre archivo/carpeta automáticamente.

Si `post_action` es `open_file` u `open_folder`, el sistema puede invocar Explorer, handlers del Shell,
reproductores, codecs o extensiones nativas inmediatamente después del movimiento. Eso ya no es la copia en sí,
pero sí ocurre dentro de la ventana temporal del movimiento/finalización.

**Cuándo sospechar de este punto:**

- Con `post_action = none` no falla.
- Falla solo al abrir carpetas con ciertos archivos o al abrir ciertos formatos.
- La caída ocurre después de registrar el movimiento en historial.

**Qué probar para confirmarlo:**

1. Reproducir siempre con `post_action = none`.
2. Si desaparece, probar `open_folder` y `open_file` por separado.
3. Revisar asociaciones de archivo, codecs y extensiones de Explorer.

## Prioridad de investigación recomendada

1. **Desactivar `ctime` temporalmente**: es la llamada Win32 más directa del flujo de movimiento.
2. **Desactivar thumbnails del Shell**: especialmente si falla con videos o al mover rápido tras cargar el archivo.
3. **Probar con `post_action = none`**: separa movimiento físico de apertura posterior.
4. **Comparar local vs OneDrive/red/unidad externa**: separa bug de la app de hooks del sistema de archivos.
5. **Bajar concurrencia a 1**: reduce presión sobre señales/progreso/finalización.
6. **Agregar logs de frontera** alrededor de llamadas nativas y de la finalización para ubicar el último punto
   ejecutado antes de la caída.

## Conclusión

Después de las mitigaciones, los puntos más probables para un `0xc0000005` durante el movimiento quedan así:

1. `setctime_blocking`/Win32 para restaurar `ctime`.
2. Thumbnail provider del Shell si la generación ya estaba en curso cuando empieza el movimiento.
3. Hooks externos del sistema de archivos durante `shutil.move`, copia por bloques, `fsync` o `unlink`.
4. Señales Qt/PyQt de finalización/progreso, sobre todo con múltiples movimientos.
5. Acciones posteriores que abren archivo o carpeta y activan Shell/codecs/handlers.
