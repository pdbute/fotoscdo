import io
import paramiko
from app.core.settings import get_settings

settings = get_settings()

class SFTPClient:
    def __init__(self):
        self.host = settings.SFTP_HOST
        self.port = settings.SFTP_PORT
        self.user = settings.SFTP_USER
        self.password = settings.SFTP_PASSWORD

    def fetch_bytes(self, path: str) -> bytes:
        transport = paramiko.Transport((self.host, self.port))
        transport.connect(username=self.user, password=self.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            with sftp.open(path, 'rb') as f:
                return f.read()
        finally:
            sftp.close()
            transport.close()

    def healthy(self) -> bool:
        try:
            transport = paramiko.Transport((self.host, self.port))
            transport.connect(username=self.user, password=self.password)
            sftp = paramiko.SFTPClient.from_transport(transport)
            sftp.listdir(settings.SFTP_BASE_PATH)
            sftp.close(); transport.close()
            return True
        except Exception:
            return False