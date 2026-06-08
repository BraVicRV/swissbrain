import logging


def setup_logging():
    """Configura niveles de log para reducir ruido."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    )

    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.ExtBot").setLevel(logging.WARNING)
    logging.getLogger("telegram.Bot").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    swissbrain_logger = logging.getLogger("SwissBrain")
    swissbrain_logger.setLevel(logging.INFO)

    print("Logging configurado (INFO para SwissBrain, WARNING para librerias)")
