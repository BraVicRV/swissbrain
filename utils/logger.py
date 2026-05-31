import logging
import sys
from datetime import datetime
from pathlib import Path

# Crear carpeta de logs
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Nombre de archivo con fecha
log_file = log_dir / f"swissbrain_{datetime.now().strftime('%Y%m%d')}.log"

# Configurar logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("SwissBrain")

def log_error(context: str, exception: Exception):
    """Log detallado de errores."""
    import traceback
    logger.error(f"{'='*50}")
    logger.error(f"ERROR EN: {context}")
    logger.error(f"Tipo: {type(exception).__name__}")
    logger.error(f"Mensaje: {str(exception)}")
    logger.error("Traceback:")
    logger.error(traceback.format_exc())
    logger.error(f"{'='*50}")

def log_api_call(service: str, endpoint: str, status: str, details: str = ""):
    """Log de llamadas a APIs."""
    logger.info(f"API [{service}] {endpoint} -> {status} {details}")