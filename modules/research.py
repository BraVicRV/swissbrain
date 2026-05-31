import requests
from typing import Dict, Any, List
from modules.base import BaseModule
from config.settings import SETTINGS


class ResearchModule(BaseModule):
    def __init__(self):
        super().__init__(
            name="research",
            description="Investigación profunda con verificación de fuentes"
        )
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        tema = params.get("tema", "")
        profundidad = params.get("profundidad", "media")
        
        # Buscar en Serper.dev
        search_results = await self._search_web(tema)
        
        if not search_results:
            return {
                "findings": [{
                    "title": f"Investigación: {tema}",
                    "content": f"⚠️ No se encontraron resultados de búsqueda para '{tema}'.",
                    "priority": "baja",
                    "sources": []
                }],
                "sources_analyzed": 0,
                "status": "failed"
            }
        
        # Extraer contenido de las mejores fuentes
        sources = await self._extract_sources(search_results)
        
        # Validar que tenemos contenido real
        valid_sources = [
            s for s in sources 
            if s.get("content") and len(s["content"].strip()) > 100
        ]
        
        # >>> FIX: Validar relevancia temática del contenido
        relevant_sources = self._filter_relevant_sources(valid_sources, tema)
        
        if not relevant_sources:
            return {
                "findings": [{
                    "title": f"Investigación: {tema}",
                    "content": (
                        f"⚠️ *Atención:* Se encontraron {len(search_results)} resultados de búsqueda "
                        f"pero no se pudo extraer contenido relevante sobre '{tema}'.\n\n"
                        f"• Fuentes extraídas: {len(sources)}\n"
                        f"• Con contenido válido: {len(valid_sources)}\n"
                        f"• Relevantes al tema: {len(relevant_sources)}\n\n"
                        f"Esto puede deberse a:\n"
                        f"• Las páginas bloquean extracción automatizada\n"
                        f"• El contenido está detrás de paywalls\n"
                        f"• Los resultados de búsqueda no eran precisos\n\n"
                        f"Fuentes encontradas (no extraídas):\n" +
                        "\n".join([f"- {s.get('title', 'Sin título')}: {s.get('link', '')}" 
                                  for s in search_results[:5]])
                    ),
                    "priority": "baja",
                    "sources": [s.get("link", "") for s in search_results[:5]]
                }],
                "sources_analyzed": 0,
                "status": "partial"
            }
        
        findings = [{
            "title": f"Investigación: {tema}",
            "content": self._build_research_summary(relevant_sources),
            "priority": "media",
            "sources": [s["url"] for s in relevant_sources[:5]]
        }]
        
        return {
            "findings": findings,
            "sources_analyzed": len(relevant_sources),
            "status": "completed"
        }
    
    async def _search_web(self, query: str) -> List[Dict]:
        """Busca en la web usando Serper.dev."""
        if not SETTINGS.SERPER_API_KEY:
            print("ERROR: SERPER_API_KEY no configurada")
            return []
        
        try:
            response = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": SETTINGS.SERPER_API_KEY},
                json={"q": query, "num": 10},
                timeout=15
            )
            data = response.json()
            return data.get("organic", [])
        except Exception as e:
            print(f"Error en búsqueda: {e}")
            return []
    
    async def _extract_sources(self, search_results: List[Dict]) -> List[Dict]:
        """Extrae contenido de las fuentes usando Jina AI."""
        sources = []
        
        for result in search_results[:5]:
            url = result.get("link")
            if not url:
                continue
            
            try:
                jina_url = f"https://r.jina.ai/{url}"
                response = requests.get(jina_url, timeout=30)
                content = response.text[:3000]
                
                # Validar que Jina no devolvió error o HTML
                if len(content.strip()) < 50 or "<html" in content.lower()[:100]:
                    print(f"Contenido inválido de Jina para {url}, saltando...")
                    continue
                
                # >>> FIX: Detectar si es contenido de error/paywall
                error_phrases = [
                    "access denied", "403 forbidden", "404 not found",
                    "subscribe to read", "sign in to continue", "cookie policy",
                    "please enable javascript", "bot detection", "captcha"
                ]
                content_lower = content.lower()
                if any(phrase in content_lower for phrase in error_phrases):
                    print(f"Contenido bloqueado/paywall para {url}, saltando...")
                    continue
                
                sources.append({
                    "url": url,
                    "title": result.get("title", ""),
                    "content": content,
                    "source": result.get("source", "web")
                })
            except Exception as e:
                print(f"Error extrayendo {url}: {e}")
        
        return sources
    
    # >>> FIX: Nuevo método para filtrar por relevancia
    def _filter_relevant_sources(self, sources: List[Dict], tema: str) -> List[Dict]:
        """Filtra fuentes que realmente hablan del tema solicitado."""
        if not tema or not sources:
            return sources
        
        # Extraer palabras clave del tema
        stopwords = {"el", "la", "los", "las", "en", "de", "del", "al", "un", "una",
                     "sobre", "para", "por", "con", "sin", "y", "o", "the", "a", "an",
                     "in", "on", "at", "to", "for", "of", "with", "and", "or"}
        
        keywords = [w.lower() for w in tema.split() 
                   if w.lower() not in stopwords and len(w) > 3]
        
        if not keywords:
            return sources
        
        relevant = []
        for source in sources:
            text = f"{source.get('title', '')} {source.get('content', '')}".lower()
            # Debe contener al menos 2 palabras clave o 1 palabra clave + variación
            matches = sum(1 for kw in keywords if kw in text)
            if matches >= 1:  # Al menos 1 match (flexible)
                relevant.append(source)
            else:
                print(f"Fuente descartada por irrelevancia: {source.get('title', '')[:50]}...")
        
        return relevant
    
    def _build_research_summary(self, sources: List[Dict]) -> str:
        """Construye resumen de la investigación con enlaces limpios."""
        if not sources:
            return "No se encontraron fuentes relevantes."
        
        summary = "*Fuentes verificadas:*\n\n"
        for i, source in enumerate(sources[:5], 1):
            title = source.get('title', 'Sin título')
            content = source.get('content', '')[:200]
            url = source.get('url', '')
            
            summary += f"{i}. *{title}*\n"
            if content:
                summary += f"_{content}..._\n"
            if url:
                summary += f"🔗 [Ver fuente]({url})\n"
            summary += "\n"
        
        return summary