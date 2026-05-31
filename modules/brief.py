import requests
import feedparser
from typing import Dict, Any, List
from datetime import datetime, timedelta
from modules.base import BaseModule
from config.settings import SETTINGS


class BriefModule(BaseModule):
    def __init__(self):
        super().__init__(
            name="brief",
            description="Genera resumen diario de noticias relevantes"
        )
        self.rss_sources = [
            # Tecnología
            "https://feeds.bbci.co.uk/news/technology/rss.xml",
            "https://www.xataka.com/feedburner.xml",
            "https://www.genbeta.com/feedburner.xml",
            "https://hipertextual.com/feed",
            
            # Negocios/Economía
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://elpais.com/economia/rss.xml",
            "https://www.expansion.com/rss/portada.xml",
            
            # Ciencia
            "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
            "https://www.nationalgeographic.com.es/rss/ciencia",
            "https://www.agenciasinc.es/rss/noticias",
            
            # General / Internacional
            "https://elpais.com/rss/elpais/portada.xml",
            "https://www.elmundo.es/rss/portada.xml",
            "https://www.clarin.com/rss/lo-ultimo/",
            "https://www.latercera.com/feed/",
            "https://www.elcomercio.pe/feed/",
        ]
        self.news_cache = []
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Genera brief bajo demanda o con filtros específicos."""
        tema = params.get("tema", "")
        cantidad = params.get("cantidad", 10)
        
        noticias = await self._fetch_news(tema)
        
        # >>> FIX: Filtrar por relevancia al tema SI hay tema
        if tema:
            noticias = self._filter_by_topic(noticias, tema)
        
        resumen = self._summarize_news(noticias[:cantidad])
        
        return {
            "findings": [{
                "title": f"📰 Brief: {tema or 'General'}",
                "content": resumen,
                "priority": "baja"
            }],
            "total_noticias": len(noticias),
            "status": "completed"
        }
    
    async def generate_daily_brief(self) -> str:
        """Genera el brief diario automático."""
        noticias = await self._fetch_news()
        
        noticias_recientes = [
            n for n in noticias 
            if self._is_recent(n.get("published", ""), hours=24)
        ]
        
        noticias_priorizadas = self._prioritize_by_interest(noticias_recientes)
        resumen = self._format_daily_brief(noticias_priorizadas[:15])
        return resumen
    
    async def autonomous_check(self) -> List[Dict[str, Any]]:
        """Verifica si hay noticias de última hora importantes."""
        noticias = await self._fetch_news()
        urgentes = []
        
        for noticia in noticias:
            if self._is_breaking_news(noticia):
                urgentes.append(self.format_finding(
                    title=f"🚨 Última hora: {noticia['title']}",
                    content=noticia.get("summary", noticia.get("description", ""))[:500],
                    priority="baja",
                    metadata={"source": noticia.get("source", "unknown"), "url": noticia.get("link", "")}
                ))
        
        return urgentes[:3]
    
    async def _fetch_news(self, query: str = "") -> List[Dict]:
        """Obtiene noticias de RSS, NewsAPI y Serper.dev como fallback."""
        noticias = []
        
        # 1. RSS Feeds (siempre, como base)
        for url in self.rss_sources:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    noticias.append({
                        "title": entry.get("title", ""),
                        "summary": entry.get("summary", entry.get("description", "")),
                        "link": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "source": feed.feed.get("title", "RSS"),
                        "type": "rss"
                    })
            except Exception as e:
                print(f"Error RSS {url}: {e}")
        
        # 2. NewsAPI (si hay API key y query)
        if SETTINGS.NEWS_API_KEY and query:
            try:
                response = requests.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": query,
                        "sortBy": "publishedAt",
                        "language": "es",
                        "apiKey": SETTINGS.NEWS_API_KEY,
                        "pageSize": 10
                    },
                    timeout=10
                )
                data = response.json()
                for article in data.get("articles", []):
                    noticias.append({
                        "title": article.get("title", ""),
                        "summary": article.get("description", ""),
                        "link": article.get("url", ""),
                        "published": article.get("publishedAt", ""),
                        "source": article.get("source", {}).get("name", "NewsAPI"),
                        "type": "newsapi"
                    })
            except Exception as e:
                print(f"Error NewsAPI: {e}")
        
        # >>> FIX 3: Usar Serper.dev como fallback si hay query y no hay NewsAPI
        elif SETTINGS.SERPER_API_KEY and query:
            try:
                response = requests.post(
                    "https://google.serper.dev/news",
                    headers={"X-API-KEY": SETTINGS.SERPER_API_KEY},
                    json={"q": query, "num": 10},
                    timeout=10
                )
                data = response.json()
                for article in data.get("news", []):
                    noticias.append({
                        "title": article.get("title", ""),
                        "summary": article.get("snippet", ""),
                        "link": article.get("link", ""),
                        "published": article.get("date", ""),
                        "source": article.get("source", "Serper"),
                        "type": "serper"
                    })
            except Exception as e:
                print(f"Error Serper news: {e}")
        
        return self._deduplicate(noticias)
    
    # >>> FIX 4: Nuevo método para filtrar por tema
    def _filter_by_topic(self, noticias: List[Dict], tema: str) -> List[Dict]:
        """Filtra noticias por relevancia al tema usando palabras clave."""
        if not tema:
            return noticias
        
        # Extraer palabras clave del tema (ignorar palabras comunes)
        stopwords = {"el", "la", "los", "las", "en", "de", "del", "al", "un", "una", 
                     "sobre", "sobre", "para", "por", "con", "sin", "hacia", "desde",
                     "the", "a", "an", "in", "on", "at", "to", "for", "of", "with"}
        
        keywords = [w.lower() for w in tema.split() if w.lower() not in stopwords and len(w) > 3]
        
        if not keywords:
            return noticias
        
        scored = []
        for n in noticias:
            text = f"{n.get('title', '')} {n.get('summary', '')}".lower()
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scored.append((score, n))
        
        # Ordenar por relevancia (mayor score primero)
        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored]
    
    def _summarize_news(self, noticias: List[Dict]) -> str:
        """Formatea noticias en resumen legible con enlaces clickeables."""
        if not noticias:
            return "No se encontraron noticias relevantes para el tema solicitado."
        
        lines = []
        for i, n in enumerate(noticias, 1):
            title = n.get('title', 'Sin título')
            summary = n.get('summary', '')[:120]
            link = n.get('link', '')
            source = n.get('source', 'Web')
            
            # >>> FIX: Formato más limpio y clickeable
            lines.append(f"*{i}. {title}*")
            if summary:
                lines.append(f"_{summary}..._")
            if link:
                lines.append(f"🔗 [Leer en {source}]({link})")
            lines.append("")  # Línea en blanco
        
        return "\n".join(lines)
    
    def _format_daily_brief(self, noticias: List[Dict]) -> str:
        """Formatea el brief diario completo."""
        fecha = datetime.now().strftime("%d/%m/%Y")
        
        sections = {
            "Tecnología": [],
            "Negocios": [],
            "Ciencia": [],
            "General": []
        }
        
        for n in noticias:
            title_lower = n["title"].lower()
            if any(w in title_lower for w in ["tech", "ai", "software", "app", "crypto", "blockchain", "robot", "ia", "inteligencia artificial"]):
                sections["Tecnología"].append(n)
            elif any(w in title_lower for w in ["stock", "market", "economy", "business", "finance", "precio", "mercado"]):
                sections["Negocios"].append(n)
            elif any(w in title_lower for w in ["science", "research", "study", "nasa", "space", "ciencia", "espacio"]):
                sections["Ciencia"].append(n)
            else:
                sections["General"].append(n)
        
        lines = [f"📰 *SwissBrain Daily Brief — {fecha}*\n"]
        
        for section, items in sections.items():
            if items:
                lines.append(f"*{section}*")
                for n in items[:3]:
                    lines.append(f"• [{n['title']}]({n.get('link', '')})")
                lines.append("")
        
        lines.append(f"_Total: {len(noticias)} noticias analizadas_")
        return "\n".join(lines)
    
    def _is_recent(self, published: str, hours: int = 24) -> bool:
        """Verifica si una noticia es reciente."""
        try:
            from dateutil import parser
            pub_date = parser.parse(published)
            return datetime.now(pub_date.tzinfo) - pub_date < timedelta(hours=hours)
        except:
            return True
    
    def _is_breaking_news(self, noticia: Dict) -> bool:
        """Detecta si es una noticia de última hora importante."""
        title = noticia.get("title", "").lower()
        keywords = ["breaking", "urgente", "alerta", "crisis", "guerra", "hackeo", 
                   "filtración", "quiebra", "colapso", "ataque", "sanciones"]
        return any(k in title for k in keywords)
    
    def _prioritize_by_interest(self, noticias: List[Dict]) -> List[Dict]:
        """Prioriza noticias según intereses del usuario."""
        return sorted(noticias, key=lambda x: x.get("published", ""), reverse=True)
    
    def _deduplicate(self, noticias: List[Dict]) -> List[Dict]:
        """Elimina noticias duplicadas por título similar."""
        seen = set()
        unique = []
        for n in noticias:
            key = n["title"].lower().replace(" ", "")[:30]
            if key not in seen:
                seen.add(key)
                unique.append(n)
        return unique