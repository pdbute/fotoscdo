from pydantic import BaseModel, Field
from typing import Optional, List

class IngestBySFTP(BaseModel):
    cdo: str = Field(..., description="Nombre del elemento de red CDO")
    path: str = Field(..., description="Ruta absoluta dentro del SFTP, ej: /upload/foto1.jpg")
    lon: Optional[float] = Field(None, description="Override de longitud (WGS84)")
    lat: Optional[float] = Field(None, description="Override de latitud (WGS84)")

class IngestByUpload(BaseModel):
    cdo: str
    lon: float
    lat: float

class PhotoMeta(BaseModel):
    id: str
    cdo: str
    lon: float
    lat: float
    mime_type: str
    size_bytes: int
    width: int
    height: int
    exif: dict

class SearchByCDO(BaseModel):
    cdo: str

class SearchByGeo(BaseModel):
    lon: float
    lat: float
    radius_m: int = 200

class PhotoSearchResponse(BaseModel):
    items: List[PhotoMeta]