import io
import logging
from typing import Tuple, Dict, Optional
from datetime import datetime, timezone
from PIL import Image, ExifTags
import piexif
import exifread
from app.core.settings import get_settings

settings = get_settings()
logger = logging.getLogger("app")

class ImageService:
    @staticmethod
    def extract_exif(img: Image.Image) -> Dict:
        """
        Devuelve un dict 'aplanado' con etiquetas EXIF legibles.
        """
        meta: Dict[str, str] = {}
        # 1) Vía bytes EXIF (piexif)
        try:
            exif = img.info.get("exif")
            if exif:
                exif_dict = piexif.load(exif)
                for ifd in ("0th", "Exif", "GPS", "1st"):
                    for tag, val in exif_dict.get(ifd, {}).items():
                        try:
                            name = piexif.TAGS[ifd][tag]["name"] if tag in piexif.TAGS[ifd] else str(tag)
                        except Exception:
                            name = str(tag)
                        meta[f"{ifd}.{name}"] = str(val)
        except Exception:
            logger.debug("extract_exif: piexif.load falló", exc_info=True)

        # 2) Fallback vía Pillow
        try:
            raw = img.getexif()
            for k, v in raw.items():
                name = ExifTags.TAGS.get(k, str(k))
                meta[name] = str(v)
        except Exception:
            logger.debug("extract_exif: Pillow getexif falló", exc_info=True)

        return meta

    # ---------------------------
    # Utilidades GPS / fecha
    # ---------------------------
    @staticmethod
    def _ratio_to_float(r) -> float:
        try:
            return float(r[0]) / float(r[1])  # (num, den)
        except Exception:
            return float(r)

    @staticmethod
    def _dms_to_dd(d, m, s, ref) -> float:
        dd = d + (m / 60.0) + (s / 3600.0)
        if ref in (b"S", b"W", "S", "W"):
            dd = -dd
        return dd

    @staticmethod
    def _parse_exifread_frac(s: str) -> float:
        s = s.strip()
        if "/" in s:
            a, b = s.split("/", 1)
            return float(a) / float(b or 1)
        return float(s)

    @staticmethod
    def _parse_exifread_dms(value) -> Optional[Tuple[float, float, float]]:
        """
        value suele venir como '[deg, min, sec/den]' desde exifread.
        Devuelve (deg, min, sec) en floats.
        """
        try:
            s = str(value).strip().replace("[", "").replace("]", "")
            parts = [p.strip().strip('"').strip("'") for p in s.split(",")]
            if len(parts) < 2:
                return None
            deg = ImageService._parse_exifread_frac(parts[0])
            minu = ImageService._parse_exifread_frac(parts[1]) if len(parts) > 1 else 0.0
            sec = ImageService._parse_exifread_frac(parts[2]) if len(parts) > 2 else 0.0
            return deg, minu, sec
        except Exception:
            return None

    @staticmethod
    def _extract_gps_from_piexif_bytes(exif_bytes: bytes) -> Optional[Tuple[float, float]]:
        gps = None
        try:
            exif_dict = piexif.load(exif_bytes)
            gps_ifd = exif_dict.get("GPS", {}) or {}
            lat = gps_ifd.get(piexif.GPSIFD.GPSLatitude)
            lat_ref = gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef)
            lon = gps_ifd.get(piexif.GPSIFD.GPSLongitude)
            lon_ref = gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef)

            logger.debug("piexif GPS keys -> lat:%s lat_ref:%s lon:%s lon_ref:%s", lat, lat_ref, lon, lon_ref)

            if not (lat and lat_ref and lon and lon_ref):
                return None

            d = ImageService._ratio_to_float(lat[0])
            m = ImageService._ratio_to_float(lat[1]) if len(lat) > 1 else 0.0
            s = ImageService._ratio_to_float(lat[2]) if len(lat) > 2 else 0.0
            lat_dd = ImageService._dms_to_dd(d, m, s, lat_ref)

            d = ImageService._ratio_to_float(lon[0])
            m = ImageService._ratio_to_float(lon[1]) if len(lon) > 1 else 0.0
            s = ImageService._ratio_to_float(lon[2]) if len(lon) > 2 else 0.0
            lon_dd = ImageService._dms_to_dd(d, m, s, lon_ref)
            gps = (lon_dd, lat_dd)
        except Exception:
            logger.debug("piexif: no pude extraer GPS", exc_info=True)
        return gps

    @staticmethod
    def _extract_gps_with_exifread(data: bytes) -> Optional[Tuple[float, float]]:
        try:
            tags = exifread.process_file(io.BytesIO(data), details=False)
            lat = tags.get("GPS GPSLatitude")
            lat_ref = tags.get("GPS GPSLatitudeRef")
            lon = tags.get("GPS GPSLongitude")
            lon_ref = tags.get("GPS GPSLongitudeRef")

            logger.debug("exifread GPS tags -> lat:%s lat_ref:%s lon:%s lon_ref:%s", lat, lat_ref, lon, lon_ref)

            if not (lat and lat_ref and lon and lon_ref):
                return None

            lat_dms = ImageService._parse_exifread_dms(lat)
            lon_dms = ImageService._parse_exifread_dms(lon)
            if not (lat_dms and lon_dms):
                return None

            lat_dd = ImageService._dms_to_dd(lat_dms[0], lat_dms[1], lat_dms[2], str(lat_ref))
            lon_dd = ImageService._dms_to_dd(lon_dms[0], lon_dms[1], lon_dms[2], str(lon_ref))
            return (lon_dd, lat_dd)
        except Exception:
            logger.debug("exifread: no pude extraer GPS", exc_info=True)
            return None

    @staticmethod
    def extract_gps_from_original(original_bytes: bytes, compressed_img: Optional[Image.Image] = None) -> Optional[Tuple[float, float]]:
        """
        Intenta extraer (lon, lat) en este orden:
        1) EXIF bytes del archivo original (si era JPEG con EXIF)
        2) exifread desde bytes originales (robusto para diferentes formatos)
        3) EXIF bytes de la imagen *comprimida* (último recurso)
        """
        # 1) EXIF bytes del original (si Pillow los expone)
        try:
            im0 = Image.open(io.BytesIO(original_bytes))
            exif0 = im0.info.get("exif")
            if exif0:
                logger.debug("EXIF original presente (bytes=%d)", len(exif0))
                gps = ImageService._extract_gps_from_piexif_bytes(exif0)
                if gps:
                    return gps
            else:
                logger.debug("EXIF original no presente o no expuesto por Pillow")
        except Exception:
            logger.debug("No pude abrir original con Pillow para leer EXIF", exc_info=True)

        # 2) Fallback: exifread directo a bytes
        gps = ImageService._extract_gps_with_exifread(original_bytes)
        if gps:
            logger.debug("GPS obtenido por exifread: %s", gps)
            return gps

        # 3) Último recurso: EXIF de la comprimida (si la pasaron)
        if compressed_img is not None:
            try:
                exif1 = compressed_img.info.get("exif")
                if exif1:
                    logger.debug("EXIF de comprimida presente (bytes=%d)", len(exif1))
                    gps = ImageService._extract_gps_from_piexif_bytes(exif1)
                    if gps:
                        return gps
            except Exception:
                logger.debug("No pude leer EXIF de la imagen comprimida", exc_info=True)

        logger.debug("No se pudo extraer GPS por ningún método")
        return None

    @staticmethod
    def extract_captured_at(img: Image.Image, original_bytes: Optional[bytes] = None) -> Optional[datetime]:
        """
        Devuelve DateTimeOriginal (UTC) si está en EXIF. Fallback con exifread si es posible.
        """
        # 1) piexif desde PIL
        try:
            exif_bytes = img.info.get("exif")
            if exif_bytes:
                exif_dict = piexif.load(exif_bytes)
                exif_ifd = exif_dict.get("Exif", {}) or {}
                raw = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal) or exif_ifd.get(piexif.ExifIFD.DateTimeDigitized)
                if not raw:
                    raw = (exif_dict.get("0th", {}) or {}).get(piexif.ImageIFD.DateTime)
                if raw:
                    if isinstance(raw, bytes):
                        raw = raw.decode(errors="ignore")
                    dt = datetime.strptime(raw[:19], "%Y:%m:%d %H:%M:%S")
                    return dt.replace(tzinfo=timezone.utc)
        except Exception:
            logger.debug("extract_captured_at: piexif falló", exc_info=True)

        # 2) Fallback exifread sobre bytes originales
        if original_bytes:
            try:
                tags = exifread.process_file(io.BytesIO(original_bytes), details=False)
                raw = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
                if raw:
                    raw_str = str(raw)
                    dt = datetime.strptime(raw_str[:19], "%Y:%m:%d %H:%M:%S")
                    return dt.replace(tzinfo=timezone.utc)
            except Exception:
                logger.debug("extract_captured_at: exifread falló", exc_info=True)

        return None

    # ---------------------------
    # Compresión JPEG a ~1 MB
    # ---------------------------
    @staticmethod
    def compress_to_target_jpeg(data: bytes, target_bytes: int) -> Tuple[bytes, int, int, str]:
        """
        Convierte la imagen a JPEG preservando EXIF (si existía) y ajusta calidad hasta <= target_bytes.
        """
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")  # fuerza JPEG

        # EXIF del original, si está disponible (mejor fuente para preservarlo)
        exif_preserve = None
        try:
            exif_preserve = Image.open(io.BytesIO(data)).info.get("exif", None)
            if exif_preserve:
                logger.debug("EXIF a preservar (bytes=%d)", len(exif_preserve))
        except Exception:
            logger.debug("No pude obtener EXIF del original para preservarlo", exc_info=True)

        quality = 92
        step = 6
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True, exif=exif_preserve)
        b = out.getvalue()

        while len(b) > target_bytes and quality > 10:
            quality = max(10, quality - step)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True, exif=exif_preserve)
            b = out.getvalue()

        w, h = img.size
        return b, w, h, "image/jpeg"
