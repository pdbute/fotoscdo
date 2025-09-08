#!/usr/bin/env python3
import io, sys
from PIL import Image
import logging
import re
from typing import Tuple, Dict, Optional
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from PIL import Image, ExifTags
import piexif
import exifread

# HEIC opcional: si lo tenés instalado, ayuda a abrir .HEIC
try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception:
    pass


logger = logging.getLogger("app")


class ImageService:
    # ---------------------------
    # EXIF (aplanado)
    # ---------------------------
    @staticmethod
    def extract_exif(img: Image.Image) -> Dict:
        """
        Devuelve un dict 'aplanado' con etiquetas EXIF legibles.
        """
        meta: Dict[str, str] = {}

        # 1) Vía bytes EXIF (piexif)
        try:
            exif_bytes = img.info.get("exif")
            if exif_bytes:
                exif_dict = piexif.load(exif_bytes)
                for ifd in ("0th", "Exif", "GPS", "1st"):
                    for tag, val in (exif_dict.get(ifd, {}) or {}).items():
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
    # Utilidades de parseo (tu lógica adaptada)
    # ---------------------------
    @staticmethod
    def _frac_to_float(frac_str: str) -> Optional[float]:
        """Convierte 'num/den' o número a float."""
        try:
            if isinstance(frac_str, (int, float)):
                return float(frac_str)
            s = str(frac_str).strip()
            if "/" in s:
                num, den = s.split("/", 1)
                return float(num) / float(den or 1)
            return float(s)
        except Exception:
            return None

    @staticmethod
    def _coord_str_to_decimal(coord_str: str, ref: str) -> Optional[float]:
        """
        Convierte strings estilo exifread '[deg, min, sec/den]' a decimal.
        Copiado de tu enfoque, con tolerancias extra.
        """
        try:
            s = str(coord_str).strip().replace('"', '').replace("'", "").replace("[", "").replace("]", "")
            partes = [p.strip() for p in s.split(",")]
            if len(partes) < 2:
                return None
            deg = float(partes[0])
            minu = float(partes[1])
            sec = ImageService._frac_to_float(partes[2]) if len(partes) > 2 else 0.0
            if sec is None:
                sec = 0.0
            decimal = deg + minu / 60.0 + sec / 3600.0
            if str(ref).upper().startswith(("S", "W")):
                decimal = -abs(decimal)
            return decimal
        except Exception as e:
            logger.debug("coord_str_to_decimal fallo: '%s' ref=%s err=%s", coord_str, ref, e)
            return None

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

    # ---------------------------
    # XMP / ISO6709 (para HEIC/QuickTime o exportados)
    # ---------------------------
    @staticmethod
    def _extract_xmp_packet(data: bytes) -> Optional[str]:
        try:
            m1 = re.search(br"<x:xmpmeta[^>]*>", data, re.IGNORECASE | re.DOTALL)
            if not m1:
                return None
            start = m1.start()
            m2 = re.search(br"</x:xmpmeta>", data[start:], re.IGNORECASE)
            if not m2:
                return None
            end = start + m2.end()
            return data[start:end].decode("utf-8", errors="ignore")
        except Exception:
            return None

    @staticmethod
    def _parse_xmp_gps(xmp_xml: str) -> Optional[Tuple[float, float]]:
        try:
            ns = {
                "x": "adobe:ns:meta/",
                "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                "exif": "http://ns.adobe.com/exif/1.0/",
            }
            root = ET.fromstring(xmp_xml)

            def get_text(path_list):
                for p in path_list:
                    n = root.find(p, ns)
                    if n is not None and (getattr(n, "text", None)):
                        return n.text.strip()
                return None

            lat_txt = get_text([".//exif:GPSLatitude"])
            lon_txt = get_text([".//exif:GPSLongitude"])
            lat_ref = get_text([".//exif:GPSLatitudeRef"]) or ""
            lon_ref = get_text([".//exif:GPSLongitudeRef"]) or ""

            def to_float(s: Optional[str]) -> Optional[float]:
                if not s:
                    return None
                try:
                    return float(s.replace(",", "."))
                except Exception:
                    return None

            lat = to_float(lat_txt)
            lon = to_float(lon_txt)
            if lat is None or lon is None:
                return None
            if lat_ref.upper().startswith("S"):
                lat = -abs(lat)
            if lon_ref.upper().startswith("W"):
                lon = -abs(lon)
            return (lon, lat)
        except Exception:
            return None

    @staticmethod
    def _find_iso6709(data: bytes) -> Optional[Tuple[float, float]]:
        key = b"com.apple.quicktime.location.ISO6709"
        pos = data.find(key)
        if pos == -1:
            return None
        blob = data[pos: pos + 512]
        m = re.search(br"([+\-]\d+(?:\.\d+)?)([+\-]\d+(?:\.\d+)?)(?:[+\-]\d+(?:\.\d+)?)?/?", blob)
        if not m:
            return None
        try:
            lat = float(m.group(1))
            lon = float(m.group(2))
            return (lon, lat)
        except Exception:
            return None

    # ---------------------------
    # GPS (rutas de extracción)
    # ---------------------------
    @staticmethod
    def _gps_from_exifread_bytes(original_bytes: bytes) -> Optional[Tuple[float, float]]:
        """
        Tu ruta preferida: exifread -> 'GPS GPSLatitude'/'GPS GPSLongitude' + convertir_coord().
        """
        try:
            tags = exifread.process_file(io.BytesIO(original_bytes), details=False)
            lat = tags.get("GPS GPSLatitude")
            lon = tags.get("GPS GPSLongitude")
            lat_ref = tags.get("GPS GPSLatitudeRef")
            lon_ref = tags.get("GPS GPSLongitudeRef")

            logger.debug("exifread tags -> lat=%s lat_ref=%s lon=%s lon_ref=%s", lat, lat_ref, lon, lon_ref)

            if not (lat and lon and lat_ref and lon_ref):
                return None

            lat_dd = ImageService._coord_str_to_decimal(str(lat), str(lat_ref))
            lon_dd = ImageService._coord_str_to_decimal(str(lon), str(lon_ref))
            if lat_dd is None or lon_dd is None:
                return None
            return (lon_dd, lat_dd)
        except Exception:
            logger.debug("_gps_from_exifread_bytes falló", exc_info=True)
            return None

    @staticmethod
    def _gps_from_piexif_bytes(exif_bytes: bytes) -> Optional[Tuple[float, float]]:
        try:
            exif_dict = piexif.load(exif_bytes)
            gps_ifd = exif_dict.get("GPS", {}) or {}
            lat = gps_ifd.get(piexif.GPSIFD.GPSLatitude)
            lat_ref = gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef)
            lon = gps_ifd.get(piexif.GPSIFD.GPSLongitude)
            lon_ref = gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef)
            logger.debug("piexif GPS -> lat=%s lat_ref=%s lon=%s lon_ref=%s", lat, lat_ref, lon, lon_ref)
            if not (lat and lat_ref and lon and lon_ref):
                return None
            d = ImageService._ratio_to_float(lat[0]); m = ImageService._ratio_to_float(lat[1]) if len(lat) > 1 else 0.0; s = ImageService._ratio_to_float(lat[2]) if len(lat) > 2 else 0.0
            lat_dd = ImageService._dms_to_dd(d, m, s, lat_ref)
            d = ImageService._ratio_to_float(lon[0]); m = ImageService._ratio_to_float(lon[1]) if len(lon) > 1 else 0.0; s = ImageService._ratio_to_float(lon[2]) if len(lon) > 2 else 0.0
            lon_dd = ImageService._dms_to_dd(d, m, s, lon_ref)
            return (lon_dd, lat_dd)
        except Exception:
            logger.debug("_gps_from_piexif_bytes falló", exc_info=True)
            return None

    @staticmethod
    def extract_gps_from_original(original_bytes: bytes, compressed_img: Optional[Image.Image] = None) -> Optional[Tuple[float, float]]:
        """
        Intenta extraer (lon, lat) en este orden:
        1) exifread (como en tu script)
        2) piexif sobre EXIF de los bytes originales
        3) XMP embebido
        4) QuickTime ISO6709 (HEIC/Apple)
        5) EXIF de la imagen comprimida (último recurso)
        """
        # 1) exifread
        gps = ImageService._gps_from_exifread_bytes(original_bytes)
        if gps:
            logger.debug("GPS desde exifread: %s", gps)
            return gps

        # 2) piexif: leer EXIF de los bytes originales si Pillow lo expone
        try:
            im0 = Image.open(io.BytesIO(original_bytes))
            exif0 = im0.info.get("exif")
        except Exception:
            exif0 = None
        if exif0:
            gps = ImageService._gps_from_piexif_bytes(exif0)
            if gps:
                logger.debug("GPS desde piexif (original): %s", gps)
                return gps

        # 3) XMP
        xmp_xml = ImageService._extract_xmp_packet(original_bytes)
        if xmp_xml:
            gps = ImageService._parse_xmp_gps(xmp_xml)
            if gps:
                logger.debug("GPS desde XMP: %s", gps)
                return gps

        # 4) QuickTime ISO6709 (HEIC/Apple)
        gps = ImageService._find_iso6709(original_bytes)
        if gps:
            logger.debug("GPS desde ISO6709: %s", gps)
            return gps

        # 5) EXIF de la comprimida
        if compressed_img is not None:
            try:
                exif1 = compressed_img.info.get("exif")
                if exif1:
                    gps = ImageService._gps_from_piexif_bytes(exif1)
                    if gps:
                        logger.debug("GPS desde piexif (comprimida): %s", gps)
                        return gps
            except Exception:
                logger.debug("No pude leer EXIF de la comprimida", exc_info=True)

        logger.debug("No se pudo extraer GPS por ningún método")
        return None

    # ---------------------------
    # Fecha de captura
    # ---------------------------
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
                    dt = datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S")
                    return dt.replace(tzinfo=timezone.utc)
        except Exception:
            logger.debug("extract_captured_at: piexif falló", exc_info=True)

        # 2) Fallback exifread sobre bytes originales
        if original_bytes:
            try:
                tags = exifread.process_file(io.BytesIO(original_bytes), details=False)
                raw = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
                if raw:
                    dt = datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S")
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
        Convierte a JPEG preservando EXIF (si existía) y ajusta calidad hasta <= target_bytes.
        """
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")  # fuerza JPEG

        # EXIF del original para preservarlo
        exif_preserve = None
        try:
            exif_preserve = Image.open(io.BytesIO(data)).info.get("exif", None)
            if exif_preserve:
                logger.debug("Preservando EXIF original (bytes=%d)", len(exif_preserve))
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



def main():
    if len(sys.argv) != 2:
        print("Uso: python scripts/diagnose_gps.py /ruta/imagen.jpg")
        sys.exit(1)
    path = sys.argv[1]
    data = open(path, "rb").read()
    img = Image.open(io.BytesIO(data))
    gps = ImageService.extract_gps_from_original(data, img)
    print("GPS detectado:", gps)

if __name__ == "__main__":
    main()
