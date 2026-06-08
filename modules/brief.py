import aiohttp
import asyncio
import re
import feedparser
from typing import Dict, Any, List
from datetime import datetime, timedelta
from modules.base import BaseModule
from config.settings import SETTINGS

class BriefModule(BaseModule):
    def __init__(self):
        super().__init__(
            name="brief",
            description="Genera resumen de noticias relevantes por tema y ubicación"
        )
        # Fuentes RSS organizadas por categoría
        self.rss_sources = {
            "perú": {
                "general": [
                    "https://www.elcomercio.pe/rss/",
                    "https://larepublica.pe/arc/outboundfeeds/rss/?outputType=xml",
                    "https://gestion.pe/rss/feed.xml",
                    "https://rpp.pe/rss",
                ],
                "tecnología": [
                    "https://elcomercio.pe/tecnologia/rss/",
                    "https://larepublica.pe/tecnologia/rss/",
                    "https://gestion.pe/tecnologia/rss/",
                ],
                "economía": [
                    "https://gestion.pe/economia/rss/",
                    "https://elcomercio.pe/economia/rss/",
                ],
                "política": [
                    "https://elcomercio.pe/politica/rss/",
                    "https://larepublica.pe/politica/rss/",
                ],
            },
            "mundo": {
                "general": [
                    "https://feeds.bbci.co.uk/news/world/rss.xml",
                    "https://elpais.com/rss/elpais/portada.xml",
                    "https://www.elmundo.es/rss/portada.xml",
                ],
                "tecnología": [
                    "https://feeds.bbci.co.uk/news/technology/rss.xml",
                    "https://www.xataka.com/feedburner.xml",
                    "https://www.genbeta.com/feedburner.xml",
                ],
                "economía": [
                    "https://feeds.bbci.co.uk/news/business/rss.xml",
                    "https://elpais.com/economia/rss.xml",
                ],
            },
            "tecnología": {
                "general": [
                    "https://feeds.bbci.co.uk/news/technology/rss.xml",
                    "https://www.xataka.com/feedburner.xml",
                    "https://www.genbeta.com/feedburner.xml",
                ],
            },
            "economía": {
                "general": [
                    "https://feeds.bbci.co.uk/news/business/rss.xml",
                    "https://elpais.com/economia/rss.xml",
                    "https://www.expansion.com/rss/portada.xml",
                ],
            },
        }
        self.news_cache = []
        self.last_query = ""

    async def _test_feed(self, url: str) -> bool:
        """Verifica si un feed RSS es accesible."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                    return response.status == 200
        except Exception as e:
            print(f"Feed no accesible: {url} - {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Genera brief bajo demanda o con filtros específicos."""
        tema = params.get("tema", "")
        self.last_query = tema
        cantidad = params.get("cantidad", 5)  # Reducido a 5 para evitar sobrecarga

        try:
            noticias = await asyncio.wait_for(self._fetch_news(tema), timeout=15)
        except asyncio.TimeoutError:
            print("⚠️ Timeout en módulo brief")
            return {
                "findings": [{
                    "title": "📰 Brief: Error de timeout",
                    "content": f"No se pudieron obtener noticias sobre '{tema}' en el tiempo esperado. Intenta de nuevo más tarde.",
                    "priority": "baja"
                }],
                "status": "failed"
            }

        if tema:
            noticias = self._filter_by_topic(noticias, tema)

        if not noticias:
            return {
                "findings": [{
                    "title": f"📰 Brief: {tema}",
                    "content": self._get_no_news_message(tema),
                    "priority": "baja"
                }],
                "status": "completed"
            }

        resumen = self._summarize_news(noticias[:cantidad])
        return {
            "findings": [{
                "title": f"📰 Brief: {tema or 'Noticias generales'}",
                "content": resumen,
                "priority": "baja"
            }],
            "total_noticias": len(noticias),
            "status": "completed"
        }

    async def generate_daily_brief(self) -> str:
        """Genera un brief diario con noticias relevantes de Perú."""
        try:
            noticias_perú = await self._fetch_news("Perú")
            noticias_tecnología = await self._fetch_news("tecnología en Perú")
            noticias_mundo = await self._fetch_news("mundo")

            todas_noticias = noticias_perú + noticias_tecnología + noticias_mundo
            todas_noticias = self._deduplicate(todas_noticias)

            if not todas_noticias:
                return "No hay noticias recientes para el brief diario."

            return self._format_daily_brief(todas_noticias)
        except Exception as e:
            print(f"Error generando brief diario: {e}")
            return "Error al generar el brief diario."

    async def _fetch_news(self, query: str = "") -> List[Dict]:
        """Obtiene noticias de RSS o APIs según el tema."""
        noticias = []
        query_lower = query.lower()

        # Si el tema es muy específico (ej: "desarrollo de software en Lima"), usar APIs
        if any(t in query_lower for t in ["desarrollo de software", "startups", "empresas de tecnología", "programación"]):
            if SETTINGS.NEWS_API_KEY:
                noticias_api = await self._fetch_news_from_api(query, "newsapi")
                noticias.extend(noticias_api)
            elif SETTINGS.SERPER_API_KEY:
                noticias_api = await self._fetch_news_from_api(query, "serper")
                noticias.extend(noticias_api)

        # Si no hay noticias de APIs o el tema no es específico, usar RSS
        if not noticias or len(noticias) < 3:
            # Determinar categoría y sub-categoría
            categoría = "general"
            subcategoría = None

            if "perú" in query_lower or "peru" in query_lower:
                categoría = "perú"
                if "tecnología" in query_lower:
                    subcategoría = "tecnología"
                elif "economía" in query_lower:
                    subcategoría = "economía"
                elif "política" in query_lower:
                    subcategoría = "política"
            elif "mundo" in query_lower or "internacional" in query_lower:
                categoría = "mundo"
                if "tecnología" in query_lower:
                    subcategoría = "tecnología"
                elif "economía" in query_lower:
                    subcategoría = "economía"
            elif "tecnología" in query_lower:
                categoría = "tecnología"
            elif "economía" in query_lower:
                categoría = "economía"

            if categoría in self.rss_sources:
                if subcategoría and subcategoría in self.rss_sources[categoría]:
                    sources_to_use = self.rss_sources[categoría][subcategoría]
                else:
                    sources_to_use = self.rss_sources[categoría].get("general", [])
            else:
                sources_to_use = []
                for cat in self.rss_sources.values():
                    sources_to_use.extend(cat.get("general", []))

            # Filtrar fuentes accesibles
            valid_sources = []
            for url in sources_to_use:
                if await self._test_feed(url):
                    valid_sources.append(url)

            if not valid_sources:
                print("⚠️ No hay fuentes accesibles. Usando NewsAPI/Serper como fallback.")
                valid_sources = [
                    "https://feeds.bbci.co.uk/news/world/rss.xml",
                    "https://feeds.bbci.co.uk/news/technology/rss.xml",
                ]

            # Obtener noticias de las fuentes válidas
            async with aiohttp.ClientSession() as session:
                tasks = []
                for url in valid_sources[:5]:  # Limitar a 5 fuentes
                    task = self._fetch_single_feed(session, url, query)
                    tasks.append(task)

                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, list):
                        noticias.extend(result)

        return self._deduplicate(noticias)

    async def _fetch_news_from_api(self, query: str, api: str) -> List[Dict]:
        """Obtiene noticias de una API (NewsAPI o Serper)."""
        noticias = []
        try:
            async with aiohttp.ClientSession() as session:
                if api == "newsapi" and SETTINGS.NEWS_API_KEY:
                    params = {
                        "q": query or "noticias",
                        "language": "es",
                        "apiKey": SETTINGS.NEWS_API_KEY,
                        "pageSize": 10,
                        "sortBy": "publishedAt"
                    }
                    async with session.get(
                        "https://newsapi.org/v2/everything",
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            for article in data.get("articles", []):
                                noticias.append({
                                    "title": article.get("title", ""),
                                    "summary": article.get("description", ""),
                                    "link": article.get("url", ""),
                                    "published": article.get("publishedAt", ""),
                                    "source": article.get("source", {}).get("name", "NewsAPI"),
                                    "type": "newsapi"
                                })
                elif api == "serper" and SETTINGS.SERPER_API_KEY:
                    headers = {"X-API-KEY": SETTINGS.SERPER_API_KEY}
                    payload = {"q": query or "noticias", "num": 10}
                    async with session.post(
                        "https://google.serper.dev/news",
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
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
            print(f"Error en API {api}: {e}")

        return noticias

    async def _fetch_single_feed(self, session: aiohttp.ClientSession, url: str, query: str) -> List[Dict]:
        """Obtiene noticias de un solo feed RSS."""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    text = await response.text()
                    feed = feedparser.parse(text)
                    noticias = []
                    for entry in feed.entries[:10]:  # Limitar a 10 entradas por feed
                        noticia = {
                            "title": entry.get("title", ""),
                            "summary": entry.get("summary", entry.get("description", "")),
                            "link": entry.get("link", ""),
                            "published": entry.get("published", ""),
                            "source": feed.feed.get("title", "RSS"),
                            "type": "rss"
                        }
                        noticias.append(noticia)
                    return noticias
                else:
                    print(f"Error HTTP {response.status} en {url}")
                    return []
        except Exception as e:
            print(f"Error al obtener {url}: {e}")
            return []

    def _filter_by_topic(self, noticias: List[Dict], tema: str) -> List[Dict]:
        """Filtra noticias por relevancia al tema usando palabras clave y exclusiones."""
        if not tema:
            return noticias

        # Palabras clave por tema
        tema_keywords = {
            "perú": [
                "perú", "peruano", "lima", "arequipa", "trujillo", "cusco", "puno",
                "gobierno peruano", "congreso", "presidente", "economía peruana",
                "sol", "bcr", "sunat", "mef", "pbi", "inflación", "desempleo"
            ],
            "tecnología": [
                "tecnología", "tecnológico", "digital", "innovación", "startup", "emprendimiento",
                "software", "hardware", "IA", "inteligencia artificial", "machine learning",
                "blockchain", "criptomonedas", "bitcoin", "ethereum", "python", "java",
                "desarrollo", "programación", "código", "app", "aplicación", "sistema",
                "cloud", "aws", "azure", "google cloud", "servidor", "base de datos",
                "ciberseguridad", "hacking", "vulnerabilidad", "seguridad informática",
                "redes", "internet", "5G", "fibra óptica", "conectividad"
            ],
            "economía": [
                "economía", "finanzas", "mercado", "bolsa", "acciones", "inversión",
                "dólar", "euro", "bitcoin", "cripto", "petróleo", "oro", "inflación",
                "banco central", "tipo de cambio", "exportación", "importación"
            ],
            "política": [
                "política", "gobierno", "congreso", "presidente", "ministro", "elecciones",
                "ley", "decreto", "proyecto de ley", "debate", "voto"
            ],
            "mundo": [
                "internacional", "global", "mundial", "ee.uu.", "europa", "asia",
                "guerra", "conflicto", "onu", "otán", "unión europea", "china", "rusia"
            ],
            "deportes": [
                "fútbol", "deporte", "partido", "gol", "selección", "campeonato",
                "atletismo", "tenis", "básquet", "olímpico"
            ],
            "clima": [
                "clima", "pronóstico", "senamhi", "lluvia", "temperatura", "humedad",
                "sol", "nubes", "viento", "alerta meteorológica"
            ]
        }

        # Exclusiones: Palabras que indican que la noticia NO es relevante para el tema
        tema_exclusions = {
            "tecnología": ["clima", "pronóstico", "senamhi", "lluvia", "temperatura", "deporte", "fútbol"],
            "perú": ["clima", "deporte", "fútbol"],
            "economía": ["clima", "deporte", "fútbol"],
            "política": ["clima", "deporte", "fútbol"],
            "mundo": ["clima", "deporte"],
        }

        tema_lower = tema.lower()
        keywords = tema_keywords.get(tema_lower, [])
        exclude_words = tema_exclusions.get(tema_lower, [])

        # Si el tema no está en el diccionario, usar el tema como palabra clave
        if not keywords:
            stopwords = {"el", "la", "los", "las", "en", "de", "del", "al", "un", "una", "y", "o"}
            keywords = [w.lower() for w in tema.split() if w.lower() not in stopwords and len(w) > 3]

        scored_noticias = []
        for noticia in noticias:
            title = noticia.get("title", "").lower()
            summary = noticia.get("summary", "").lower()
            text = f"{title} {summary}"

            # Puntuación positiva: Cuántas palabras clave aparecen
            score = sum(1 for kw in keywords if kw in text)

            # Puntuación negativa: Si aparece alguna palabra de exclusión, restar puntos
            exclude_score = sum(1 for ew in exclude_words if ew in text)

            # Solo incluir si tiene al menos 1 palabra clave y 0 exclusiones
            if score > 0 and exclude_score == 0:
                scored_noticias.append((score, noticia))

        # Ordenar por puntuación (de mayor a menor)
        scored_noticias.sort(key=lambda x: x[0], reverse=True)

        return [noticia for _, noticia in scored_noticias]

    def _get_no_news_message(self, tema: str) -> str:
        """Genera un mensaje personalizado cuando no hay noticias."""
        tema_lower = tema.lower()

        if "tecnología" in tema_lower and ("perú" in tema_lower or "peru" in tema_lower):
            return (
                "No se encontraron noticias recientes sobre **tecnología en Perú** en las fuentes configuradas.\n\n"
                "Puedes intentar con:\n"
                "- Un tema más específico (ej: 'startups de IA en Perú', 'desarrollo de software en Lima').\n"
                "- Verificar tu conexión a internet.\n"
                "- Probar más tarde.\n\n"
                "🔗 *Fuentes consultadas:*\n"
                "- El Comercio (Tecnología)\n"
                "- La República (Tecnología)\n"
                "- Gestión (Tecnología)\n"
                "- BBC Technology"
            )
        elif "perú" in tema_lower or "peru" in tema_lower:
            return (
                "No se encontraron noticias recientes sobre **Perú** en las fuentes configuradas.\n\n"
                "Puedes intentar con:\n"
                "- Un tema más específico (ej: 'economía en Perú', 'política peruana').\n"
                "- Verificar tu conexión a internet.\n"
                "- Probar más tarde."
            )
        elif "mundo" in tema_lower or "internacional" in tema_lower:
            return (
                "No se encontraron noticias internacionales recientes.\n\n"
                "Puedes intentar con:\n"
                "- Un tema más específico (ej: 'guerra en Ucrania', 'elecciones en EE.UU.', 'economía global').\n"
                "- Verificar tu conexión a internet.\n"
                "- Probar más tarde."
            )
        elif "tecnología" in tema_lower:
            return (
                "No se encontraron noticias recientes sobre **tecnología**.\n\n"
                "Puedes intentar con:\n"
                "- Un tema más específico (ej: 'IA', 'blockchain', 'desarrollo web').\n"
                "- Verificar tu conexión a internet.\n"
                "- Probar más tarde."
            )
        elif "economía" in tema_lower:
            return (
                "No se encontraron noticias recientes sobre **economía**.\n\n"
                "Puedes intentar con:\n"
                "- Un tema más específico (ej: 'bitcoin', 'mercado de acciones', 'inflación').\n"
                "- Verificar tu conexión a internet.\n"
                "- Probar más tarde."
            )
        else:
            return (
                f"No se encontraron noticias recientes sobre **{tema}**.\n\n"
                "Puedes intentar con:\n"
                "- Un tema más específico.\n"
                "- Verificar tu conexión a internet.\n"
                "- Probar más tarde."
            )

    def _summarize_news(self, noticias: List[Dict]) -> str:
        """Formatea noticias en resumen legible con enlaces clickeables."""
        if not noticias:
            return self._get_no_news_message(self.last_query)

        lines = []
        for i, n in enumerate(noticias, 1):
            title = self._clean_text(n.get('title', 'Sin título'))
            summary = self._clean_text(n.get('summary', '')[:150])  # Aumentado a 150 caracteres
            link = n.get('link', '')
            source = self._clean_text(n.get('source', 'Web'))

            lines.append(f"{i}. *{title}*")
            if summary:
                lines.append(f"_{summary}..._")
            if link:
                safe_link = link.replace("(", "%28").replace(")", "%29")
                lines.append(f"[Leer en {source}]({safe_link})")
            lines.append("")  # Línea en blanco para separar noticias

        return "\n".join(lines)

    def _format_daily_brief(self, noticias: List[Dict]) -> str:
        """Formatea el brief diario completo."""
        fecha = datetime.now().strftime("%d/%m/%Y")

        sections = {
            "Perú": [],
            "Tecnología": [],
            "Economía": [],
            "Mundo": [],
            "General": []
        }

        for n in noticias:
            title_lower = n["title"].lower()
            summary_lower = n.get("summary", "").lower()
            text = f"{title_lower} {summary_lower}"

            if any(city in text for city in ["lima", "arequipa", "trujillo", "perú", "peru"]):
                sections["Perú"].append(n)
            elif any(w in text for w in ["tecnología", "digital", "software", "ia", "blockchain"]):
                sections["Tecnología"].append(n)
            elif any(w in text for w in ["economía", "finanzas", "mercado", "dólar", "bitcoin"]):
                sections["Economía"].append(n)
            elif any(w in text for w in ["mundo", "internacional", "ee.uu.", "europa", "asia"]):
                sections["Mundo"].append(n)
            else:
                sections["General"].append(n)

        lines = [f"📰 *SwissBrain Daily Brief — {fecha}*\n"]
        for section, items in sections.items():
            if items:
                lines.append(f"*{section}*")
                for n in items[:3]:  # Máximo 3 noticias por sección
                    title = self._clean_text(n['title'])
                    link = n.get('link', '')
                    source = self._clean_text(n.get('source', 'Web'))
                    lines.append(f"• [{title}]({link}) *({source})*")
                lines.append("")  # Línea en blanco entre secciones

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

    def _deduplicate(self, noticias: List[Dict]) -> List[Dict]:
        """Elimina noticias duplicadas por título similar."""
        seen = set()
        unique = []
        for n in noticias:
            key = n["title"].lower().replace(" ", "")[:50]  # Usar más caracteres para evitar falsos positivos
            if key not in seen:
                seen.add(key)
                unique.append(n)
        return unique

    def _clean_text(self, text: str) -> str:
        """Limpia texto para evitar errores de Markdown en Telegram."""
        if not text:
            return ""

        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        text = text.replace("*", "").replace("_", "").replace("`", "'")
        return text[:500]  # Limitar a 500 caracteres