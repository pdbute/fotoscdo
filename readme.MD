# FotosCDO — Ecosistema de Fotos con CDO (MVP)

Arquitectura mínima y modular para:
- **Cliente** (futuro) que invoca APIs
- **Servidor de archivos** (SFTP) para alojar fotos
- **Aplicación Server** (FastAPI) para ingestión, compresión, metadata EXIF y consultas espaciales (PostGIS)
- **Health Check** (DB + SFTP)
- **Observabilidad** (OpenTelemetry opcional) y **logging** completo

---

## 1) Estructura de proyecto

```
fotoscdo/
├─ docker-compose.yml
├─ README.md
├─ .env.example
└─ app/
   ├─ pyproject.toml
   ├─ .env  # (opcional, local)
   └─ app/
      ├─ main.py
      ├─ core/
      │  └─ settings.py
      ├─ db/
      │  ├─ session.py
      │  ├─ models.py
      │  └─ init_db.py
      ├─ middleware/
      │  └─ request_context.py
      ├─ routers/
      │  ├─ photos.py
      │  └─ health.py
      ├─ schemas/
      │  └─ photos.py
      └─ services/
         ├─ sftp_client.py
         └─ image_service.py
```


# FotosCDO — API de Fotos con PostGIS y SFTP (MVP)

## Objetivo
- Ingerir fotos desde un **SFTP**, extraer **metadata EXIF**, **comprimir a 1 MB** y persistir en **PostgreSQL + PostGIS** (binario + metadata + punto lon/lat)
- Consultar por **CDO** o por **coordenadas** dentro de un **radio (m)**
- **Health**: verifica DB y SFTP
- **OpenTelemetry** opcional (toggle) y **logging** completo


---

## Arranque de infraestructura

```bash
cp .env.example .env
# Editá si querés credenciales

docker compose up -d
```

- DB: `localhost:5432` (postgis)
- SFTP: `localhost:2222` (user `pablo`, pass `${SFTP_PASSWORD}`, dir `/upload`)

Subir una foto de ejemplo:
```bash
sftp -P 2222 pablo@localhost
# password: pablo (por defecto)
put ./mi_foto.jpg /upload/mi_foto.jpg
```

---

## Correr la aplicación (local)

```bash
cd app
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --port 8000
```

La app lee variables desde `app/.env` si existe (o desde el entorno del shell).

---

## Endpoints

### Ingesta por SFTP
```bash
curl -X POST "http://localhost:8000/photos/ingest/sftp" \
  -H "Content-Type: application/json" \
  -d '{
    "cdo": "VLUCA11B2",
    "lon": -65.217138,
    "lat": -26.818338,
    "path": "/upload/mi_foto.jpg"
  }'
```

**Respuesta (ejemplo)**
```json
{
  "id": "e9d6...",
  "cdo": "VLUCA11B2",
  "lon": -65.217138,
  "lat": -26.818338,
  "mime_type": "image/jpeg",
  "size_bytes": 1023456,
  "width": 1920,
  "height": 1080,
  "exif": {"Exif.DateTimeOriginal": "..."}
}
```

### Buscar por CDO
```bash
curl "http://localhost:8000/photos/search?cdo=VLUCA11B2"
```

### Buscar por coordenadas (radio en metros)
```bash
curl "http://localhost:8000/photos/search?lon=-65.2171&lat=-26.8183&radius_m=300"
```

### Obtener binario de la imagen
```bash
curl -OJ "http://localhost:8000/photos/<ID>/image"
```

### Health Check
```bash
curl "http://localhost:8000/health"
```

---

## Observabilidad (OpenTelemetry)
- Activar por `.env` con `ENABLE_OTEL=true` y seteá `OTEL_EXPORTER_OTLP_ENDPOINT`.
- Si está habilitado, se agrega `x-trace-id` en las respuestas.
- Si no hay collector disponible, dejá `ENABLE_OTEL=false` para evitar errores de exportación.

---

## Escalabilidad / Modularidad
- API stateless; base binaria en DB. Alternativa: almacenar binario en un **objeto** (MinIO/S3) y persistir solo metadatos + URL (fácil de intercambiar en `Photo` y en `photos.py`).
- Separación de capas: `services/` (SFTP, imágenes), `routers/`, `db/`.
- Podés agregar **workers** para ingestión asíncrona (Celery/RQ) sin modificar contratos.

---

## Mejoras sugeridas (siguientes fases)
1. **Almacenamiento en S3/MinIO** y guardar solo URL en DB (reduce tamaño de DB, mejora backups).
2. **Firma de contenido** y checksum SHA-256.
3. **Control de versiones** de fotos por CDO (histórico).
4. **Indices espaciales** adicionales y clustering por zona.
5. **Rate limiting** y **auth** (JWT o API keys, Kong/Keycloak si ya tenés stack).
6. **Tests** (pytest) y **CI** (GitHub Actions).
7. **Metrics** Prometheus (Starlette Exporter) + **Grafana**.

---

## Notas de implementación
    - La compresión a ~1MB ajusta `quality` en pasos; si la imagen es muy grande, se podría **redimensionar** (downscale) adicionalmente. Se puede agregar parámetro opcional.
    - `Photo.data` guarda el binario. Si vamos a S3, remover `data` y agregar `object_url`.
    - PostGIS usa `Geography(Point,4326)` para habilitar `ST_DWithin` en **metros**.
    - Logs agregan `x-operation-id` por middleware; podés pasarlo vos en el header.
    - Health valida `SELECT 1` y `sftp.listdir()`.



**Verla directo en el navegador (más simple)**

Obtené el ID (ya lo hiciste):

curl -s "http://localhost:8000/photos/search?cdo=VLUCA11B2" | jq -r '.items[0].id'


Abrí la imagen en tu navegador:

open "http://localhost:8000/photos/<ID>/image"


Safari/Chrome te la muestra al toque.

B) Bajarla y abrirla con Preview (macOS)
ID="<ID>"
curl -L "http://localhost:8000/photos/$ID/image" -o "/tmp/${ID}.jpg"
open -a Preview "/tmp/${ID}.jpg"
# Quick Look también sirve:
# qlmanage -p "/tmp/${ID}.jpg" >/dev/null 2>&1 &

C) Abrir varias de una (loop)
curl -s "http://localhost:8000/photos/search?cdo=VLUCA11B2" \
| jq -r '.items[].id' \
| while read id; do
    curl -sL "http://localhost:8000/photos/$id/image" -o "/tmp/${id}.jpg"
    open -a Preview "/tmp/${id}.jpg"
  done