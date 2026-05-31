import requests
import feedparser
import re
from typing import Dict, Any, List
from datetime import datetime
from modules.base import BaseModule


class GuardianModule(BaseModule):
    def __init__(self):
        super().__init__(
            name="guardian",
            description="Monitorea oportunidades laborales relevantes"
        )
        self.job_sources = {
            "remoteok": "https://remoteok.com/remote-dev-jobs.rss",
            "weworkremotely": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        }
        self.user_profile = {
            "skills": ["python", "ai", "backend", "api", "automation"],
            "desired_roles": ["backend engineer", "ai engineer", "python developer"],
            "locations": ["remote", "spain", "europe"],
            "min_salary_usd": 60000,
            "companies_target": ["openai", "anthropic", "groq", "stripe", "github"]
        }
        self.seen_jobs = set()
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Busca trabajos según criterios específicos."""
        query = params.get("query", "")
        location = params.get("location", "remote")
        
        jobs = await self._search_jobs(query, location)
        matches = self._filter_matching_jobs(jobs)
        
        # >>> FIX: Agregar status
        return {
            "findings": [{
                "title": f"💼 Oportunidades: {query or 'General'}",
                "content": self._format_jobs(matches[:5]),
                "priority": "media"
            }],
            "matches_found": len(matches),
            "status": "completed"  # <<< AGREGAR
        }
    
    async def autonomous_check(self) -> List[Dict[str, Any]]:
        """Escanea periódicamente nuevas oportunidades."""
        all_jobs = []
        
        for source_name, url in self.job_sources.items():
            try:
                if source_name == "github_jobs":
                    jobs = await self._fetch_github_jobs()
                else:
                    jobs = await self._fetch_rss_jobs(url, source_name)
                all_jobs.extend(jobs)
            except Exception as e:
                print(f"Error en {source_name}: {e}")
        
        # Filtrar solo nuevos y relevantes
        new_jobs = [j for j in all_jobs if self._is_new_job(j)]
        matching = self._filter_matching_jobs(new_jobs)
        
        findings = []
        for job in matching:
            match_score = self._calculate_match_score(job)
            priority = "alta" if match_score > 85 else "media"
            
            findings.append(self.format_finding(
                title=f"💼 Match {match_score}%: {job['title']}",
                content=f"*{job['company']}*\n{job.get('description', '')[:300]}...\n"
                       f"📍 {job.get('location', 'Remote')}\n"
                       f"💰 {job.get('salary', 'No especificado')}\n"
                       f"[Aplicar]({job.get('url', '')})",
                priority=priority,
                metadata={"match_score": match_score, "source": job.get("source")}
            ))
            
            self.seen_jobs.add(self._job_id(job))
        
        return findings[:5]
    
    async def _search_jobs(self, query: str, location: str) -> List[Dict]:
        """Busca trabajos en múltiples fuentes."""
        jobs = []
        # Por ahora devuelve vacío, se puede implementar búsqueda específica
        return jobs
    
    async def _fetch_rss_jobs(self, url: str, source: str) -> List[Dict]:
        """Obtiene trabajos de feeds RSS."""
        feed = feedparser.parse(url)
        jobs = []
        
        for entry in feed.entries[:10]:
            jobs.append({
                "title": entry.get("title", ""),
                "company": self._extract_company(entry),
                "description": entry.get("summary", ""),
                "url": entry.get("link", ""),
                "location": "Remote",
                "published": entry.get("published", ""),
                "source": source
            })
        
        return jobs
    
    async def _fetch_github_jobs(self) -> List[Dict]:
        """Obtiene trabajos de GitHub Jobs."""
        try:
            response = requests.get(
                "https://jobs.github.com/positions.json",
                params={"description": "python"},
                timeout=10
            )
            data = response.json()
            
            return [{
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "description": j.get("description", ""),
                "url": j.get("url", ""),
                "location": j.get("location", ""),
                "salary": self._extract_salary(j.get("description", "")),
                "published": j.get("created_at", ""),
                "source": "github"
            } for j in data]
        except:
            return []
    
    def _filter_matching_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Filtra trabajos que coinciden con el perfil."""
        matching = []
        
        for job in jobs:
            score = self._calculate_match_score(job)
            if score > 60:
                job["match_score"] = score
                matching.append(job)
        
        return sorted(matching, key=lambda x: x["match_score"], reverse=True)
    
    def _calculate_match_score(self, job: Dict) -> int:
        """Calcula puntaje de coincidencia 0-100."""
        score = 0
        text = f"{job.get('title', '')} {job.get('description', '')}".lower()
        
        # Skills match (40 puntos)
        skills_found = sum(1 for skill in self.user_profile["skills"] if skill in text)
        score += min(40, skills_found * 8)
        
        # Role match (30 puntos)
        role_match = any(role in text for role in self.user_profile["desired_roles"])
        score += 30 if role_match else 0
        
        # Company target (20 puntos)
        company = job.get("company", "").lower()
        if any(target in company for target in self.user_profile["companies_target"]):
            score += 20
        
        # Remote/location (10 puntos)
        location = job.get("location", "").lower()
        if any(loc in location for loc in self.user_profile["locations"]):
            score += 10
        
        return min(100, score)
    
    def _extract_company(self, entry) -> str:
        """Extrae nombre de empresa del RSS."""
        title = entry.get("title", "")
        if ":" in title:
            return title.split(":")[0].strip()
        if " at " in title:
            return title.split(" at ")[-1].strip()
        return "Empresa no especificada"
    
    def _extract_salary(self, text: str) -> str:
        """Intenta extraer rango salarial del texto."""
        patterns = [
            r'\$\d{2,3}[kK]?\s*[-–]\s*\$\d{2,3}[kK]?',
            r'\d{2,3}[kK]?\s*[-–]\s*\d{2,3}[kK]?\s*USD',
            r'salary:?\s*\$?\d{2,3}[kK]?'
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        return "No especificado"
    
    def _is_new_job(self, job: Dict) -> bool:
        """Verifica si el trabajo es nuevo."""
        return self._job_id(job) not in self.seen_jobs
    
    def _job_id(self, job: Dict) -> str:
        """Genera ID único para el trabajo."""
        return f"{job.get('company', '')}-{job.get('title', '')}"[:50]
    
    def _format_jobs(self, jobs: List[Dict]) -> str:
        """Formatea lista de trabajos."""
        if not jobs:
            return "No se encontraron coincidencias recientes. El módulo guardian está activo y monitoreará nuevas oportunidades."
        
        lines = []
        for job in jobs:
            score = job.get("match_score", 0)
            emoji = "🔥" if score > 85 else "⭐" if score > 70 else "📋"
            lines.append(f"{emoji} *{job['title']}* ({score}% match)")
            lines.append(f"   🏢 {job['company']} | 📍 {job.get('location', 'Remote')}")
            lines.append(f"   [Ver detalles]({job.get('url', '')})")
            lines.append("")
        return "\n".join(lines)