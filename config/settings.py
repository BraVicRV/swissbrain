import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class Settings:
    # Groq
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # APIs externas
    SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")
    JINA_API_KEY: str = os.getenv("JINA_API_KEY", "")
    NEWS_API_KEY: str = os.getenv("NEWS_API_KEY", "")
    
    # Configuración del agente
    CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL", "5"))
    DAILY_BRIEF_HOUR: int = int(os.getenv("DAILY_BRIEF_HOUR", "8"))
    NIGHT_MODE_START: int = 23  # 23:00
    NIGHT_MODE_END: int = 8     # 08:00
    
    # Umbrales de prioridad
    CRITICAL_KEYWORDS: list = None
    
    def __post_init__(self):
        self.CRITICAL_KEYWORDS = [
            "filtración", "breach", "hackeo", "vulnerabilidad crítica",
            "cve-202", "estafa", "phishing", "urgente", "crítico",
            "precio mínimo", "oportunidad", "deadline", "plazo",
            "retiro", "recall", "alerta sanitaria"
        ]
        
        # Log de diagnóstico
        import logging
        logger = logging.getLogger("SwissBrain")
        logger.info(f"SETTINGS CARGADAS:")
        logger.info(f"  GROQ_MODEL: {self.GROQ_MODEL}")
        logger.info(f"  TELEGRAM_CHAT_ID: {self.TELEGRAM_CHAT_ID[:5]}..." if self.TELEGRAM_CHAT_ID else "  TELEGRAM_CHAT_ID: VACÍO")
        logger.info(f"  CHECK_INTERVAL: {self.CHECK_INTERVAL_MINUTES} min")
        logger.info(f"  DAILY_BRIEF_HOUR: {self.DAILY_BRIEF_HOUR}")

SETTINGS = Settings()