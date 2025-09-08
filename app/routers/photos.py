import io
import logging
from fastapi.responses import HTMLResponse
from fastapi import APIRouter, UploadFile, File, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from app.db.session import SessionLocal
from app.db.models import Photo
from app.schemas.photos import IngestBySFTP, PhotoMeta, PhotoSearchResponse
from app.services.sftp_client import SFTPClient
from app.services.image_service import ImageService
from app.core.settings import get_settings
from starlette.responses import StreamingResponse
from opentelemetry.trace import get_current_span
from PIL import Image

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/photos", tags=["Photos"])
settings = get_settings()


@router.post("/ingest/sftp", response_model=PhotoMeta)
def ingest_sftp(payload: IngestBySFTP):
    """
    Ingesta una foto desde SFTP:
    - Comprime a ~1 MB preservando EXIF
    - Extrae EXIF (aplanado) para guardar
    - Obtiene lon/lat desde EXIF del archivo original (fallback a comprimida)
      * Si no hay GPS en EXIF y no vinieron lon/lat manuales -> 400
    - (Opcional) Captura 'captured_at' si el modelo lo tiene
    """
    span = get_current_span()
    sftp = SFTPClient()
    logger.debug("Ingest SFTP | cdo=%s path=%s", payload.cdo, payload.path)

    try:
        raw = sftp.fetch_bytes(payload.path)
        logger.debug("Bytes originales leídos: %d", len(raw))
    except Exception as e:
        logger.exception("Error leyendo SFTP")
        raise HTTPException(status_code=400, detail=f"SFTP error: {e}")

    # Comprimir a ~1MB, preservando EXIF si existía
    img_bytes, w, h, mime = ImageService.compress_to_target_jpeg(
        raw, settings.MAX_IMAGE_SIZE_BYTES
    )
    logger.debug("Bytes comprimidos: %d, mime=%s, size=%sx%s", len(img_bytes), mime, w, h)

    # Abrir la imagen comprimida para EXIF legible (para respuesta/guardado)
    pil_img = Image.open(io.BytesIO(img_bytes))

    # EXIF (aplanado) para guardar/retornar
    exif = ImageService.extract_exif(pil_img)
    logger.debug("EXIF extraído (aplanado) | keys=%d", len(exif.keys()) if exif else 0)

    # GPS: primero desde el ORIGINAL (fallback a EXIF de la comprimida)
    gps = ImageService.extract_gps_from_original(original_bytes=raw, compressed_img=pil_img)
    captured_at = ImageService.extract_captured_at(pil_img, original_bytes=raw)
    logger.debug("GPS extraído=%s | captured_at=%s", gps, captured_at)

    # Resolver coordenadas: override manual > EXIF > error
    lon = payload.lon
    lat = payload.lat
    if lon is None or lat is None:
        if gps:
            lon, lat = gps  # (lon, lat)
            logger.info("GPS resuelto desde EXIF | lon=%.6f lat=%.6f", lon, lat)
        else:
            logger.warning("La foto no tiene GPS detectable en EXIF (ni original ni comprimida)")
            raise HTTPException(
                status_code=400,
                detail="La foto no tiene GPS en EXIF. Enviá lon/lat para este caso."
            )

    geom = from_shape(Point(lon, lat), srid=4326)

    with SessionLocal() as db:
        photo = Photo(
            cdo=payload.cdo,
            geom=geom,
            mime_type=mime,
            size_bytes=len(img_bytes),
            width=w,
            height=h,
            exif=exif,
            data=img_bytes,
            # si tu modelo tiene esta columna:
            captured_at=captured_at,
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)

        logger.info(
            "Foto almacenada | id=%s cdo=%s lon=%.6f lat=%.6f size=%sB trace_id=%s",
            photo.id, payload.cdo, lon, lat, len(img_bytes),
            (format(span.get_span_context().trace_id, '032x') if span else None),
        )

        return PhotoMeta(
            id=photo.id,
            cdo=photo.cdo,
            lon=lon,
            lat=lat,
            mime_type=photo.mime_type,
            size_bytes=photo.size_bytes,
            width=photo.width,
            height=photo.height,
            exif=photo.exif,
            # si expusiste estos campos en el schema:
            # captured_at=photo.captured_at,
            # created_at=photo.created_at,
        )


@router.get("/search", response_model=PhotoSearchResponse)
def search(cdo: str | None = None, lon: float | None = None, lat: float | None = None, radius_m: int | None = None):
    if not cdo and (lon is None or lat is None):
        raise HTTPException(status_code=400, detail="Debe enviar cdo o lon/lat")

    r = radius_m or settings.DEFAULT_SEARCH_RADIUS_M
    logger.debug("Search | cdo=%s lon=%s lat=%s r=%s", cdo, lon, lat, r)

    items = []
    with SessionLocal() as db:
        if cdo:
            rows = db.query(Photo).filter(Photo.cdo == cdo).all()
        else:
            # Consulta espacial (ST_DWithin con Geography, metros)
            q = db.query(Photo).filter(
                text("ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r)")
            ).params(lon=lon, lat=lat, r=r)
            rows = q.all()

        for p in rows:
            pt = to_shape(p.geom)
            items.append(
                PhotoMeta(
                    id=p.id,
                    cdo=p.cdo,
                    lon=pt.x,
                    lat=pt.y,
                    mime_type=p.mime_type,
                    size_bytes=p.size_bytes,
                    width=p.width,
                    height=p.height,
                    exif=p.exif,
                    # captured_at=p.captured_at,
                    # created_at=p.created_at,
                )
            )
    return PhotoSearchResponse(items=items)


@router.get("/{photo_id}/image")
def get_image(photo_id: str):
    with SessionLocal() as db:
        p = db.get(Photo, photo_id)
        if not p:
            raise HTTPException(status_code=404, detail="No existe")
        filename = f"{p.cdo}_{photo_id}.jpg"
        return StreamingResponse(
            io.BytesIO(p.data),
            media_type=p.mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}',
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )


@router.get("/{photo_id}", response_model=PhotoMeta)
def get_meta(photo_id: str):
    with SessionLocal() as db:
        p = db.get(Photo, photo_id)
        if not p:
            raise HTTPException(status_code=404, detail="No existe")
        pt = to_shape(p.geom)
        return PhotoMeta(
            id=p.id, cdo=p.cdo, lon=pt.x, lat=pt.y,
            mime_type=p.mime_type, size_bytes=p.size_bytes,
            width=p.width, height=p.height, exif=p.exif
            # captured_at=p.captured_at,
            # created_at=p.created_at,
        )


@router.get("/viewer", response_class=HTMLResponse)
def viewer(cdo: str | None = None, lon: float | None = None, lat: float | None = None, radius_m: int = 200):
    if not cdo and (lon is None or lat is None):
        return HTMLResponse("<h3>Pasá ?cdo=... o ?lon=...&lat=...&radius_m=...</h3>", status_code=400)

    with SessionLocal() as db:
        if cdo:
            rows = db.query(Photo).filter(Photo.cdo == cdo).all()
        else:
            rows = db.query(Photo).filter(
                text("ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r)")
            ).params(lon=lon, lat=lat, r=radius_m).all()

    cards = []
    for p in rows:
        cards.append(
            f'<div style="display:inline-block;margin:8px;text-align:center">'
            f'<img src="/photos/{p.id}/image" style="max-width:320px;display:block;border-radius:8px"/>'
            f'<small>{p.cdo}<br/>{p.id}</small></div>'
        )

    html = f"""
    <html><head><meta charset="utf-8"><title>Viewer</title></head>
    <body style="font-family:sans-serif">
      <h2>Fotos ({'CDO '+cdo if cdo else f'lon={lon}, lat={lat}, r={radius_m}m'})</h2>
      {''.join(cards) if cards else '<p>No hay resultados.</p>'}
    </body></html>
    """
    return HTMLResponse(html)
