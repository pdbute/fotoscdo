import os
import json

def generar_geojson_thumbnails(carpeta_dato="Salida/Dato", carpeta_icon="Salida/Icon", salida_geojson="Salida/thumbnails.geojson"):
    features = []

    for archivo in os.listdir(carpeta_dato):
        if not archivo.endswith("_DATO.json"):
            continue

        nombre_base = archivo.replace("_DATO.json", "")
        ruta_json = os.path.join(carpeta_dato, archivo)
        ruta_icon_relativa = os.path.join("Salida", "Icon", f"{nombre_base}_ICON.jpg").replace("\\", "/")
        print(ruta_icon_relativa)
        with open(ruta_json, 'r', encoding='utf-8') as f:
            datos = json.load(f)

        try:
            lat = datos.get("Lat")
            lon = datos.get("Lon")
            fecha = datos.get("Fecha", "")

            if not lat or not lon:
                continue  # saltar si no hay coordenadas

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(lon), float(lat)]
                },
                "properties": {
                    "archivo": nombre_base,
                    "thumbnail": os.path.abspath(os.path.join(ruta_icon_relativa)).replace("\\", "/")
,
                    "fecha": fecha
                }
            })
        except Exception as e:
            print(f"⚠️ Error con {archivo}: {e}")
            continue

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    os.makedirs(os.path.dirname(salida_geojson), exist_ok=True)
    with open(salida_geojson, 'w', encoding='utf-8') as f_out:
        json.dump(geojson, f_out, indent=2, ensure_ascii=False)

    print(f"✅ GeoJSON generado: {salida_geojson} (Total: {len(features)} puntos)")

# Ejecutar si se llama como script
if __name__ == "__main__":
    generar_geojson_thumbnails()
