from sqlalchemy import text
from app.db.session import engine
from app.db.models import Base

def init_db():
    with engine.begin() as conn:
        # Habilitar extensión PostGIS si no existe
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        Base.metadata.create_all(bind=conn)