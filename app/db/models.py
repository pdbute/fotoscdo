import uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, JSON, LargeBinary, DateTime
from sqlalchemy.sql import func
from geoalchemy2 import Geography

class Base(DeclarativeBase):
    pass

class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    cdo: Mapped[str] = mapped_column(String, index=True)

    # Coordenadas en WGS84 (lon/lat) como Geography(Point)
    geom: Mapped[object] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)

    mime_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    exif: Mapped[dict] = mapped_column(JSON)

    data: Mapped[bytes] = mapped_column(LargeBinary)

    # NUEVO: fecha/hora de captura extraída del EXIF (puede ser nula)
    captured_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # Fecha de inserción del registro
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
