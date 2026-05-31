import re
import json
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

def truncate_text(text: str, max_length: int = 500, suffix: str = "...") -> str:
    """Trunca texto a longitud máxima."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix

def clean_html(html_text: str) -> str:
    """Elimina tags HTML básicos."""
    clean = re.sub(r'<[^>]+>', '', html_text)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()

def extract_domain(url: str) -> str:
    """Extrae dominio de una URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")
    except:
        return url

def format_currency(amount: float, currency: str = "USD") -> str:
    """Formatea cantidad monetaria."""
    symbols = {"USD": "$", "EUR": "€", "GBP": "£"}
    symbol = symbols.get(currency, currency)
    return f"{symbol}{amount:,.2f}"

def time_ago(date_string: str) -> str:
    """Convierte fecha a formato 'hace X tiempo'."""
    try:
        from dateutil import parser
        date = parser.parse(date_string)
        now = datetime.now(date.tzinfo) if date.tzinfo else datetime.now()
        diff = now - date
        
        if diff < timedelta(minutes=1):
            return "hace unos segundos"
        elif diff < timedelta(hours=1):
            return f"hace {diff.seconds // 60} minutos"
        elif diff < timedelta(days=1):
            return f"hace {diff.seconds // 3600} horas"
        elif diff < timedelta(days=7):
            return f"hace {diff.days} días"
        else:
            return date.strftime("%d/%m/%Y")
    except:
        return date_string

def safe_json_loads(text: str, default: Any = None) -> Any:
    """Carga JSON de forma segura."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}

def generate_id(*args) -> str:
    """Genera ID hash a partir de argumentos."""
    content = "|".join(str(a) for a in args)
    return hashlib.md5(content.encode()).hexdigest()[:12]

def sanitize_filename(filename: str) -> str:
    """Sanitiza nombre de archivo."""
    return re.sub(r'[^a-zA-Z0-9_-]', '_', filename)[:50]

def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """Divide lista en chunks."""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def deduplicate_dicts(dicts: List[Dict], key: str) -> List[Dict]:
    """Elimina diccionarios duplicados por clave."""
    seen = set()
    unique = []
    for d in dicts:
        val = d.get(key)
        if val and val not in seen:
            seen.add(val)
            unique.append(d)
    return unique

def calculate_reading_time(text: str, wpm: int = 200) -> str:
    """Calcula tiempo de lectura estimado."""
    words = len(text.split())
    minutes = max(1, words // wpm)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60}h {minutes % 60}min"

def mask_sensitive(text: str, visible_chars: int = 4) -> str:
    """Enmascara texto sensible."""
    if len(text) <= visible_chars * 2:
        return "*" * len(text)
    return text[:visible_chars] + "*" * (len(text) - visible_chars * 2) + text[-visible_chars:]

def is_valid_url(url: str) -> bool:
    """Valida formato de URL."""
    pattern = re.compile(
        r'^https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return bool(pattern.match(url))

def parse_date_flexible(date_string: str) -> Optional[datetime]:
    """Parsea fecha de múltiples formatos."""
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_string, fmt)
        except ValueError:
            continue
    return None

class RateLimiter:
    """Limitador de tasa simple."""
    def __init__(self, max_calls: int, period_seconds: int):
        self.max_calls = max_calls
        self.period = timedelta(seconds=period_seconds)
        self.calls = []
    
    def can_call(self) -> bool:
        now = datetime.now()
        self.calls = [c for c in self.calls if now - c < self.period]
        return len(self.calls) < self.max_calls
    
    def record_call(self):
        self.calls.append(datetime.now())
    
    def wait_time(self) -> float:
        if self.can_call():
            return 0
        now = datetime.now()
        oldest = min(self.calls)
        return max(0, (oldest + self.period - now).total_seconds())