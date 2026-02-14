# YOLO PI LUXONIS CORAL (con fallback a Pi)

Aplicación de visión por computadora para **detectar objetos en tiempo real** y **estimar su distancia/profundidad** usando:
- **Raspberry Pi 4** (host)
- **Coral USB TPU** (aceleración de inferencia)
- **Cámara Luxonis OAK** (RGB + profundidad estéreo)

> Nota importante sobre modelos:
> - En modo Coral, la inferencia principal usa **SSDLite MobileDet EdgeTPU** (`ssdlite_mobiledet_coco_qat_postprocess_edgetpu.tflite`).
> - En fallback CPU, usa **YOLOv4-tiny** (`yolov4-tiny.cfg/.weights`).
> - El nombre del proyecto se conserva como "YOLO PI LUXONIS CORAL" por continuidad del flujo y la UI.

## ¿Qué objetos detecta?
El modelo está entrenado sobre **COCO**, por lo que detecta clases comunes como persona, carro, moto, bicicleta, botella, silla, computador portátil, celular, etc. (dependiendo del modelo activo Coral/CPU).

## Cámara y profundidad: Luxonis OAK (referencia)
Este proyecto usa una cámara **Luxonis OAK** con arquitectura de **estereoscopía**:
- 1 sensor **RGB** (imagen en color para detección de objetos).
- 2 sensores **mono** (izquierdo/derecho) para calcular profundidad por disparidad.

Referencia oficial Luxonis/DepthAI:
- https://docs.luxonis.com/

### ¿Cómo funciona la estereoscopía aquí?
1. La OAK captura simultáneamente las dos imágenes mono (izquierda/derecha).
2. DepthAI calcula la disparidad entre ambas vistas y genera un mapa de profundidad (`depth frame`).
3. En paralelo se obtiene el frame RGB para detección.
4. Para cada bounding box detectada, el sistema toma un punto representativo (centro) y consulta su valor `Z` en el mapa depth.
5. Se superpone en pantalla el objeto + score + distancia aproximada (`Z`).

## Método técnico (detección + profundidad)
1. **Host (Pi) captura RGB/depth** desde Luxonis OAK.
2. **Backend Coral Docker** recibe frame (JPG) por HTTP local.
3. **EdgeTPU** corre inferencia TFLite acelerada en Coral.
4. Host recibe detecciones JSON y dibuja bounding boxes + `Z` usando mapa depth.
5. Si Coral no responde o se degrada, el script cae automáticamente a CPU (sin romper la app).

## Modos de inferencia (automático)
1. `coral-docker` (preferido)
2. `coral-local` (si runtime local compatible existiera)
3. `cpu` (fallback)

En la UI se muestra explícitamente:
- `INFERENCE: CORAL` (verde)
- `INFERENCE: CPU FALLBACK` (rojo)

## Funcionalidades de operación
- Botones: **STOP** / **EXIT**.
- Teclas: `ESC` / `q`.
- Watchdog con reinicio automático de pipeline.
- Arranque del stack completo con script único.

## Hardware requerido
- Raspberry Pi 4.
- Luxonis OAK (RGB + estéreo depth).
- Coral USB TPU.
- USB estable (ideal separar cargas o usar hub alimentado cuando sea necesario).

## Software requerido
- Host:
  - Docker + Docker Compose
  - Python host con `depthai`, `opencv-python`, `numpy`
- Contenedor Coral (Bullseye):
  - `python3-pycoral`
  - `python3-tflite-runtime`
  - `libedgetpu1-std`

## Archivos principales
- `YOLO_PI_LUXONIS_CORAL.py`
- `start_coral_stack.sh`
- `stop_coral_stack.sh`
- `docker-compose.yml`
- `docker/Dockerfile`
- `docker/app.py`
- `models/*` y `docker/models/*`
- `launchers/START.desktop` (doble click)

## Ejecución
### Doble click
- Abrir: `launchers/START.desktop`

### Manual
```bash
./start_coral_stack.sh
```

## Verificación de Coral real
```bash
sudo docker compose ps
curl -s http://127.0.0.1:8765/health
sudo docker exec $(sudo docker compose ps -q coral-infer) python3 - <<'PY'
from pycoral.utils.edgetpu import list_edge_tpus
print(list_edge_tpus())
PY
```

## Troubleshooting rápido
- Si aparece `mode=cpu`: revisar backend Coral (`docker compose ps`, logs, health).
- Si hay `USB disconnect` en OAK/Coral: revisar cableado, energía y topología USB.

## Correcciones de estabilidad (2026-02-14)
Se corrigió un caso real donde la app podía quedar lenta/inestable y no cerrar bien cuando Coral estaba intermitente.

### Síntomas observados
- Arranque lento o inestable en `mode=coral-docker`.
- En algunos intentos no detectaba objetos.
- STOP/EXIT podían tardar o parecer bloqueados.

### Causa técnica
- Respuestas inconsistentes del backend Coral (`/health` con `ready=false` o latencia alta).
- Llamadas HTTP de inferencia Coral bloqueando de más cuando el backend se degradaba.

### Cambios aplicados en código
- Timeout HTTP Coral reducido (`CORAL_HTTP_TIMEOUT=0.6`) para evitar bloqueos largos.
- Inicialización Coral más tolerante: si `/health` responde 200, se permite intentar inferencia aunque `ready=false`.
- Manejo de error runtime: si Coral falla en ejecución, cambio automático a `cpu` (fallback) sin colgar UI.
- Mantiene parada confiable con STOP/EXIT + cierre por script.

### Resultado esperado
- Si Coral está sano: `INFERENCE: CORAL`.
- Si Coral se vuelve inestable: degradación automática a `INFERENCE: CPU FALLBACK` manteniendo fluidez y control de cierre.
