import logging
from fastapi import APIRouter
from sqlalchemy import text
from app.db.session import engine
from app.services.sftp_client import SFTPClient

router = APIRouter(prefix="/health", tags=["Health"])
logger = logging.getLogger(__name__)

@router.get("")
async def health():
    status = {"database": False, "sftp": False, "status": "fail"}

    # DB
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["database"] = True
    except Exception as e:
        logger.error("DB error: %s", e)

    # SFTP
    try:
        ok = SFTPClient().healthy()
        status["sftp"] = ok
    except Exception as e:
        logger.error("SFTP error: %s", e)

    status["status"] = "ok" if status["database"] and status["sftp"] else "fail"
    return status