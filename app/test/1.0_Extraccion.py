import exifread
import piexif
from PIL import Image
import io
import csv
import os
import json

# Mapeo para renombrar etiquetas EXIF
mapeo = {
    "EXIF ApertureValue": "Abertura (AV)",
    "EXIF BrightnessValue": "Brillo (EV)",
    "EXIF ColorSpace": "Espacio de color",
    "EXIF ComponentsConfiguration": "Componentes de color",
    "EXIF DateTimeDigitized": "Fecha digitalizacion",
    "EXIF DateTimeOriginal": "Fecha",
    "EXIF ExifImageLength": "Alto imagen",
    "EXIF ExifImageWidth": "Ancho imagen",
    "EXIF ExifVersion": "Version EXIF",
    "EXIF ExposureBiasValue": "Compensacion exposicion",
    "EXIF ExposureMode": "Modo de exposicion",
    "EXIF ExposureProgram": "Programa exposicion",
    "EXIF ExposureTime": "Tiempo de exposicion",
    "EXIF FNumber": "Numero F",
    "EXIF Flash": "Flash",
    "EXIF FlashPixVersion": "Version FlashPix",
    "EXIF FocalLength": "Distancia focal (mm)",
    "EXIF FocalLengthIn35mmFilm": "Focal equivalente 35mm",
    "EXIF ISOSpeedRatings": "ISO",
    "EXIF LensMake": "Marca del lente",
    "EXIF LensModel": "Modelo del lente",
    "EXIF LensSpecification": "Especificacion del lente",
    "EXIF MakerNote": "MakerNote (oculto)",
    "EXIF MeteringMode": "Modo de medicion",
    "EXIF OffsetTime": "Zona horaria",
    "EXIF OffsetTimeDigitized": "Zona horaria digitalizacion",
    "EXIF OffsetTimeOriginal": "Zona horaria original",
    "EXIF SceneCaptureType": "Tipo de escena",
    "EXIF SceneType": "Tipo de escena EXIF",
    "EXIF SensingMethod": "Método de sensado",
    "EXIF ShutterSpeedValue": "Velocidad de obturacion (EV)",
    "EXIF SubSecTimeDigitized": "Subsegundos digitalizacion",
    "EXIF SubSecTimeOriginal": "Subsegundos original",
    "EXIF SubjectArea": "Area de sujeto",
    "EXIF Tag 0xA460": "Tag A460",
    "EXIF WhiteBalance": "Balance de blancos",
    "GPS GPSAltitude": "Altitud GPS",
    "GPS GPSAltitudeRef": "Referencia altitud",
    "GPS GPSDate": "Fecha GPS",
    "GPS GPSDestBearing": "Rumbo destino",
    "GPS GPSDestBearingRef": "Ref rumbo",
    "GPS GPSImgDirection": "Direccion imagen",
    "GPS GPSImgDirectionRef": "Ref direccion",
    "GPS GPSLatitude": "Latitud",
    "GPS GPSLatitudeRef": "Ref latitud",
    "GPS GPSLongitude": "Longitud",
    "GPS GPSLongitudeRef": "Ref longitud",
    "GPS GPSSpeed": "Velocidad GPS",
    "GPS GPSSpeedRef": "Ref velocidad GPS",
    "GPS GPSTimeStamp": "Hora GPS",
    "GPS Tag 0x001F": "Tag GPS 0x001F",
    "Image DateTime": "Fecha imagen",
    "Image ExifOffset": "Offset EXIF",
    "Image GPSInfo": "Offset GPSInfo",
    "Image HostComputer": "Computadora",
    "Image Make": "Marca",
    "Image Model": "Modelo",
    "Image Orientation": "Orientacion",
    "Image ResolutionUnit": "Unidad de resolucion",
    "Image Software": "Software",
    "Image XResolution": "Resolucion X",
    "Image YCbCrPositioning": "Posicionamiento YCbCr",
    "Image YResolution": "Resolucion Y",
    "Thumbnail Compression": "Compresion thumbnail",
    "Thumbnail JPEGInterchangeFormat": "Offset thumbnail",
    "Thumbnail JPEGInterchangeFormatLength": "Tamano thumbnail",
    "Thumbnail ResolutionUnit": "Unidad thumbnail",
    "Thumbnail XResolution": "Resolucion X thumbnail",
    "Thumbnail YResolution": "Resolucion Y thumbnail",
    "size total bloque EXIF (bytes)": "Tamano EXIF total (bytes)",
    "size thumbnail JPEG embebido (bytes)": "Tamano thumbnail (bytes)",
    "size aproximado metadatos EXIF sin thumbnail (bytes)": "Tamano EXIF sin thumbnail (bytes)",
    "size MakerNote (bytes)": "Tamano MakerNote (bytes)"
}

def fraccion_a_float(frac_str):
    """Convierte una fracción tipo 'numerador/denominador' a float."""
    try:
        num, den = frac_str.split('/')
        return float(num) / float(den)
    except Exception:
        try:
            return float(frac_str)
        except:
            return None

def convertir_coord(coord_str, ref):
    try:
        # Limpio la cadena: quito comillas y espacios
        coord_str = coord_str.strip().replace('"', '').replace("'", "").replace("[", "").replace("]", "")
        partes = coord_str.split(',')
        if len(partes) != 3:
            return None
        grados = float(partes[0].strip())
        minutos = float(partes[1].strip())
        segundos = fraccion_a_float(partes[2].strip())
        if segundos is None:
            segundos = 0.0
        decimal = grados + minutos / 60 + segundos / 3600
        if ref in ['S', 'W']:
            decimal = -decimal
        return decimal
    except Exception as e:
        print(f"Error al convertir coordenada: '{coord_str}' -> {e}")
        return None


def convertir_altitud(altitud_str):
    """Convierte altitud en formato fracción a float."""
    return fraccion_a_float(altitud_str)

def obtener_tamanos_exif_y_thumbnail(ruta_imagen):
    with open(ruta_imagen, 'rb') as f:
        data = f.read()

    pos_exif = data.find(b'\xff\xe1')  # Marca inicio EXIF (APP1)
    if pos_exif == -1:
        return 0, 0, 0, None

    tamano_exif = int.from_bytes(data[pos_exif+2:pos_exif+4], 'big')
    bloque_exif = data[pos_exif+4:pos_exif+2+tamano_exif]

    pos_thumb_start = bloque_exif.find(b'\xff\xd8')
    pos_thumb_end = bloque_exif.find(b'\xff\xd9', pos_thumb_start)
    if pos_thumb_start != -1 and pos_thumb_end != -1:
        tamano_thumbnail = pos_thumb_end - pos_thumb_start + 2
        thumbnail_bytes = bloque_exif[pos_thumb_start:pos_thumb_end+2]
    else:
        tamano_thumbnail = 0
        thumbnail_bytes = None

    tamano_sin_thumbnail = tamano_exif - tamano_thumbnail
    return tamano_exif, tamano_thumbnail, tamano_sin_thumbnail, thumbnail_bytes

def extraer_datos_makernote(path):
    exif_dict = piexif.load(path)
    maker_note = exif_dict['Exif'].get(piexif.ExifIFD.MakerNote)
    return len(maker_note) if maker_note else 0

def extraer_etiquetas_exif(ruta_imagen, etiquetas_deseadas):
    with open(ruta_imagen, 'rb') as f:
        tags = exifread.process_file(f, details=False)
    resultados = {}
    for etiqueta in etiquetas_deseadas:
        valor = tags.get(etiqueta)
        resultados[etiqueta] = str(valor) if valor else ""
    return resultados

def fraccion_a_decimal(valor):
    if isinstance(valor, str) and '/' in valor:
        try:
            num, den = valor.split('/')
            return float(num) / float(den)
        except Exception:
            return valor  # si no puede convertir, devolver original
    try:
        return float(valor)
    except:
        return valor

def guardar_csv(datos_dict, ruta_csv):
    with open(ruta_csv, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Etiqueta', 'Valor'])
        for k, v in datos_dict.items():
            writer.writerow([k, v])

def guardar_jpeg_sin_metadatos(ruta_imagen, ruta_salida_jpeg, tamano_max_bytes=2_097_152):
    with Image.open(ruta_imagen) as img:
        calidad = 100
        paso = 5

        # Comprimir iterativamente hasta que el tamaño cumpla el límite
        while calidad > 5:
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=calidad)
            if buffer.tell() <= tamano_max_bytes:
                with open(ruta_salida_jpeg, 'wb') as f_out:
                    f_out.write(buffer.getvalue())
                return
            calidad -= paso

        # Si no se pudo cumplir el tamaño, guardar con la calidad mínima alcanzada
        img.save(ruta_salida_jpeg, format='JPEG', quality=calidad)


def guardar_thumbnail_jpeg(thumbnail_bytes, ruta_salida_thumbnail):
    if thumbnail_bytes:
        thumbnail_image = Image.open(io.BytesIO(thumbnail_bytes))
        thumbnail_image.save(ruta_salida_thumbnail, format='JPEG', quality=95)

def procesar_imagen(ruta_imagen):
    nombre_base = os.path.splitext(os.path.basename(ruta_imagen))[0]
    carpeta_salida_foto = "Salida/Foto"
    carpeta_salida_dato = "Salida/Dato"
    carpeta_salida_icon = "Salida/Icon"
    carpeta_salida_full = "Salida/full"
    os.makedirs(carpeta_salida_foto, exist_ok=True)
    os.makedirs(carpeta_salida_dato, exist_ok=True)
    os.makedirs(carpeta_salida_icon, exist_ok=True)
    os.makedirs(carpeta_salida_full, exist_ok=True)

    etiquetas = list(mapeo.keys())
    datos_exif = extraer_etiquetas_exif(ruta_imagen, etiquetas)

    tamano_exif, tamano_thumbnail, tamano_sin_thumbnail, thumbnail_bytes = obtener_tamanos_exif_y_thumbnail(ruta_imagen)
    tamano_makernote = extraer_datos_makernote(ruta_imagen)

    datos_exif["size total bloque EXIF (bytes)"] = tamano_exif
    datos_exif["size thumbnail JPEG embebido (bytes)"] = tamano_thumbnail
    datos_exif["size aproximado metadatos EXIF sin thumbnail (bytes)"] = tamano_sin_thumbnail
    datos_exif["size MakerNote (bytes)"] = tamano_makernote

    # Renombrar claves
    datos_exif_renombrado = {mapeo.get(k, k): v for k, v in datos_exif.items()}

    # Convertir lat, lon, alt a decimal y agregar a dict
    lat_dec = convertir_coord(datos_exif_renombrado.get("Latitud", ""), datos_exif_renombrado.get("Ref latitud", "N"))
    lon_dec = convertir_coord(datos_exif_renombrado.get("Longitud", ""), datos_exif_renombrado.get("Ref longitud", "E"))
    alt_m = convertir_altitud(datos_exif_renombrado.get("Altitud GPS", ""))

    datos_exif_renombrado["Lat"] = lat_dec if lat_dec is not None else ""
    datos_exif_renombrado["Lon"] = lon_dec if lon_dec is not None else ""
    datos_exif_renombrado["Altitud (m)"] = alt_m if alt_m is not None else ""

    valor_fnumber = datos_exif_renombrado.get("Numero F", "")
    valor_fnumber_dec = fraccion_a_decimal(valor_fnumber)
    datos_exif_renombrado["Numero F"] = valor_fnumber_dec if valor_fnumber_dec is not None else ""

    valor_ev = datos_exif_renombrado.get("Velocidad de obturacion (EV)", "")
    valor_ev_dec = fraccion_a_decimal(valor_ev)
    datos_exif_renombrado["Velocidad de obturacion (EV)"] = valor_ev_dec if valor_ev_dec is not None else ""

    # Obtener alto y ancho como enteros (por si vienen como strings)
    try:
        alto = int(datos_exif_renombrado.get("Alto imagen", 0))
        ancho = int(datos_exif_renombrado.get("Ancho imagen", 0))
        tamano_mp = (alto * ancho) / 1_000_000
    except Exception:
        tamano_mp = None

    if tamano_mp:
        datos_exif_renombrado["Tamano (MP)"] = tamano_mp
    else:
        datos_exif_renombrado["Tamano (MP)"] = "N/A"

    # Guardar JSON completo
    ruta_json_full = os.path.join(carpeta_salida_full, f"{nombre_base}_FULL.json")
    with open(ruta_json_full, 'w', encoding='utf-8') as jsonfile:
        json.dump(datos_exif_renombrado, jsonfile, ensure_ascii=False, indent=4)

    # Filtrado para _DATO.json
    claves_dato = [
        "Fecha",
        "Lat",
        "Lon",
        "Altitud (m)",
        "Tamano (MP)",
        "Marca del lente",
        "Modelo del lente",
        "Version EXIF",
        "Velocidad de obturacion (EV)",
        "Numero F",
        "Focal equivalente 35mm",
        "ISO",
    ]
    datos_dato = {k: datos_exif_renombrado[k] for k in claves_dato if k in datos_exif_renombrado}

    for clave, valor in datos_dato.items():
        print(f"{clave}: {valor}")

    # Guardar como JSON
    ruta_json_dato = os.path.join(carpeta_salida_dato, f"{nombre_base}_DATO.json")
    with open(ruta_json_dato, 'w', encoding='utf-8') as jsonfile:
        json.dump(datos_dato, jsonfile, ensure_ascii=False, indent=4)

    ruta_jpeg = os.path.join(carpeta_salida_foto, f"{nombre_base}_FOTO.jpg")
    guardar_jpeg_sin_metadatos(ruta_imagen, ruta_jpeg)

    guardar_thumbnail_jpeg(thumbnail_bytes, os.path.join(carpeta_salida_icon, f"{nombre_base}_ICON.jpg"))

def main():
    carpeta_entrada = "Entrada"
    for archivo in os.listdir(carpeta_entrada):
        if archivo.lower().endswith(('.jpg', '.jpeg')):
            ruta = os.path.join(carpeta_entrada, archivo)
            print(f"Procesando: {ruta}")
            procesar_imagen(ruta)

if __name__ == "__main__":
    main()

