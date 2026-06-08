import re
import requests
from typing import Any, Dict, List

import feedparser

from modules.base import BaseModule

class GuardianModule(BaseModule):
    def __init__(self):
        super().__init__(
            name="guardian",
            description="Monitorea convocatorias y oportunidades laborales relevantes por especialidad y ubicación",
        )
        # Feeds RSS y APIs para diferentes regiones
        self.job_sources = {
            "github": "https://jobs.github.com/positions.json?description={query}&location={location}",
            "indeed_peru": "https://pe.indeed.com/rss?q={query}&l={location}",
            "remoteok": "https://remoteok.com/remote-dev-jobs.rss",
            "weworkremotely": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        }
        self.user_profile = {
            "specialty": "",
            "skills": [],
            "desired_roles": [],
            "locations": ["remote"],
            "min_salary_usd": None,
            "companies_target": [],
        }
        self.seen_jobs = set()

    def configure_user_profile(self, profile: Dict[str, Any]):
        """Actualiza el perfil laboral usado para puntuar convocatorias."""
        if not profile:
            return

        merged = dict(self.user_profile)
        for key in merged:
            if profile.get(key) not in (None, "", []):
                merged[key] = profile[key]

        if isinstance(merged.get("skills"), str):
            merged["skills"] = self._split_terms(merged["skills"])
        if isinstance(merged.get("desired_roles"), str):
            merged["desired_roles"] = self._split_terms(merged["desired_roles"])
        if isinstance(merged.get("locations"), str):
            merged["locations"] = self._split_terms(merged["locations"])
        if isinstance(merged.get("companies_target"), str):
            merged["companies_target"] = self._split_terms(merged["companies_target"])

        self.user_profile = merged

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Busca trabajos según el perfil o criterios específicos."""
        query = params.get("query") or params.get("tema") or self.user_profile.get("specialty", "")

        # Extraer especialidad y ubicación de la consulta
        specialty, locations = self._extract_specialty_and_location(query)

        # Configurar perfil temporalmente para esta búsqueda
        profile = {
            "specialty": specialty,
            "skills": self._get_skills_for_specialty(specialty),
            "desired_roles": [specialty] if specialty else [],
            "locations": locations,
        }
        self.configure_user_profile(profile)

        # Actualizar fuentes de empleo según la especialidad y ubicación
        self._update_job_sources(specialty, locations)

        location = params.get("location") or self._first_location()
        jobs = await self._search_jobs(specialty, location)
        matches = self._filter_matching_jobs(jobs)

        return {
            "findings": [{
                "title": f"Convocatorias: {specialty or 'perfil laboral'} en {', '.join(locations) or 'cualquier ubicación'}",
                "content": self._format_jobs(matches[:10]),
                "priority": "alta" if matches else "media",
            }],
            "matches_found": len(matches),
            "status": "completed",
        }

    def _extract_specialty_and_location(self, query: str) -> tuple:
        """Extrae la especialidad y ubicación de la consulta del usuario."""
        query_lower = query.lower()

        # Especialidades comunes
        specialties = {
            "backend": ["backend", "back-end", "desarrollador backend", "backend developer"],
            "frontend": ["frontend", "front-end", "desarrollador frontend", "frontend developer"],
            "fullstack": ["fullstack", "full-stack", "desarrollador fullstack"],
            "devops": ["devops", "dev ops", "ingeniero devops"],
            "data analyst": ["analista de datos", "data analyst", "analista datos"],
            "data scientist": ["científico de datos", "data scientist"],
        }

        # Ubicaciones comunes
        locations_list = {
            "peru": ["perú", "peru", "lima", "arequipa", "trujillo", "cusco"],
            "latam": ["latam", "latin america", "américa latina"],
            "remote": ["remoto", "remote"],
        }

        # Detectar especialidad
        specialty = ""
        for spec, keywords in specialties.items():
            if any(keyword in query_lower for keyword in keywords):
                specialty = spec
                break

        # Detectar ubicaciones
        locations = []
        for loc, keywords in locations_list.items():
            if any(keyword in query_lower for keyword in keywords):
                locations.append(loc)

        # Si no se detectó ubicación, usar "remote" por defecto
        if not locations:
            locations = ["remote"]

        return specialty, locations

    def _get_skills_for_specialty(self, specialty: str) -> List[str]:
        """Devuelve habilidades típicas para una especialidad."""
        skills_map = {
            "backend": ["python", "django", "flask", "node.js", "java", "spring", "sql", "nosql"],
            "frontend": ["javascript", "react", "angular", "vue", "typescript", "html", "css"],
            "fullstack": ["javascript", "react", "node.js", "python", "django", "sql", "html", "css"],
            "devops": ["docker", "kubernetes", "aws", "azure", "ci/cd", "linux"],
            "data analyst": ["python", "pandas", "sql", "excel", "power bi", "tableau"],
        }
        return skills_map.get(specialty.lower(), [])

    def _update_job_sources(self, specialty: str, locations: List[str]):
        """Actualiza las fuentes de empleo según la especialidad y ubicación."""
        if any(loc in ["peru", "perú"] for loc in locations):
            self.job_sources = {
                "indeed_peru": f"https://pe.indeed.com/rss?q={specialty}&l=Per%C3%BA",
                "github": f"https://jobs.github.com/positions.json?description={specialty}&location=Peru",
                "remoteok": "https://remoteok.com/remote-dev-jobs.rss",
            }
        elif any(loc in ["latam", "latin america"] for loc in locations):
            self.job_sources = {
                "github": f"https://jobs.github.com/positions.json?description={specialty}&location=Latin%20America",
                "remoteok": "https://remoteok.com/remote-dev-jobs.rss",
            }
        else:
            self.job_sources = {
                "github": f"https://jobs.github.com/positions.json?description={specialty}",
                "remoteok": "https://remoteok.com/remote-dev-jobs.rss",
                "weworkremotely": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
            }

    async def autonomous_check(self) -> List[Dict[str, Any]]:
        """Escanea periódicamente nuevas oportunidades relevantes."""
        if not self._has_enough_profile():
            return []

        all_jobs = await self._search_jobs(self.user_profile.get("specialty", ""), self._first_location())
        new_jobs = [job for job in all_jobs if self._is_new_job(job)]
        matching = self._filter_matching_jobs(new_jobs)

        findings = []
        for job in matching[:5]:
            match_score = job.get("match_score", self._calculate_match_score(job))
            priority = "alta" if match_score >= 85 else "media"

            findings.append(self.format_finding(
                title=f"Convocatoria {match_score}%: {job['title']}",
                content=self._format_single_job(job),
                priority=priority,
                metadata={"match_score": match_score, "source": job.get("source")},
            ))
            self.seen_jobs.add(self._job_id(job))

        return findings

    async def _search_jobs(self, query: str, location: str) -> List[Dict]:
        """Busca trabajos en las fuentes configuradas."""
        jobs = []
        for source_name, url in self.job_sources.items():
            try:
                # Reemplazar {query} y {location} en la URL
                url = url.format(query=query, location=location)
                jobs.extend(await self._fetch_rss_jobs(url, source_name))
            except Exception as e:
                print(f"Error en {source_name}: {e}")

        query_terms = self._profile_terms(query)
        location_terms = [loc.lower() for loc in self.user_profile.get("locations", [])]
        if not query_terms:
            query_terms = [query.lower()]

        filtered = []
        for job in jobs:
            text = self._job_text(job)
            job_location = job.get("location", "").lower()
            # Filtrar por especialidad Y (ubicación O remoto)
            if (any(term in text for term in query_terms) and
                (any(loc in job_location for loc in location_terms) or "remote" in job_location)):
                filtered.append(job)

        return filtered or jobs

    async def _fetch_rss_jobs(self, url: str, source: str) -> List[Dict]:
        """Obtiene trabajos de un feed RSS o API."""
        if source == "github":
            # Usar GitHub Jobs API
            try:
                response = requests.get(url, timeout=10)
                jobs = response.json()
                return [{
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "description": job.get("description", ""),
                    "url": job.get("url", ""),
                    "location": job.get("location", "Remote"),
                    "salary": job.get("salary", "No especificado"),
                    "published": job.get("created_at", ""),
                    "source": source,
                } for job in jobs[:20]]
            except Exception as e:
                print(f"Error en GitHub Jobs API: {e}")
                return []

        elif source == "indeed_peru":
            # Usar Indeed RSS (no requiere API key)
            try:
                feed = feedparser.parse(url)
                jobs = []
                for entry in feed.entries[:20]:
                    description = entry.get("summary", entry.get("description", ""))
                    jobs.append({
                        "title": entry.get("title", ""),
                        "company": self._extract_company(entry),
                        "description": description,
                        "url": entry.get("link", ""),
                        "location": self._extract_location(description) or "Remote",
                        "salary": self._extract_salary(description),
                        "published": entry.get("published", ""),
                        "source": source,
                    })
                return jobs
            except Exception as e:
                print(f"Error en Indeed Perú: {e}")
                return []

        else:
            # Lógica original para feeds RSS
            feed = feedparser.parse(url)
            jobs = []
            for entry in feed.entries[:20]:
                description = entry.get("summary", entry.get("description", ""))
                jobs.append({
                    "title": entry.get("title", ""),
                    "company": self._extract_company(entry),
                    "description": description,
                    "url": entry.get("link", ""),
                    "location": self._extract_location(description) or "Remote",
                    "salary": self._extract_salary(description),
                    "published": entry.get("published", ""),
                    "source": source,
                })
            return jobs

    def _filter_matching_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Filtra trabajos según el match_score."""
        matching = []
        for job in jobs:
            score = self._calculate_match_score(job)
            if score >= 40:  # Umbral ajustado
                job["match_score"] = score
                matching.append(job)
        return sorted(matching, key=lambda item: item["match_score"], reverse=True)

    def _calculate_match_score(self, job: Dict) -> int:
        """Calcula el score de coincidencia para un trabajo."""
        score = 0
        text = self._job_text(job)

        # Puntuación por habilidades (50% del score)
        skills = [skill.lower() for skill in self.user_profile.get("skills", [])]
        if skills:
            skills_found = sum(1 for skill in skills if skill in text)
            score += min(50, skills_found * 10)

        # Puntuación por roles (30% del score)
        roles = [role.lower() for role in self.user_profile.get("desired_roles", [])]
        specialty = (self.user_profile.get("specialty") or "").lower()
        role_terms = roles + self._split_terms(specialty)
        if any(role and role in text for role in role_terms):
            score += 30

        # Puntuación por ubicación (20% del score)
        locations = [loc.lower() for loc in self.user_profile.get("locations", [])]
        job_location = job.get("location", "").lower()
        if any(loc in job_location for loc in locations):
            score += 20
        elif "remote" in job_location:
            score += 10  # Puntuación adicional si es remoto

        return min(100, score)

    def _format_jobs(self, jobs: List[Dict]) -> str:
        """Formatea la lista de trabajos."""
        if not jobs:
            return (
                "No encontré convocatorias con buena coincidencia ahora. "
                "Guardian seguirá revisando automáticamente y te avisará cuando aparezca algo relevante."
            )

        lines = []
        for job in jobs:
            lines.append(self._format_single_job(job))
            lines.append("")
        return "\n".join(lines).strip()

    def _format_single_job(self, job: Dict) -> str:
        """Formatea un trabajo individual."""
        score = job.get("match_score", 0)
        salary = job.get("salary") or "No especificado"
        return (
            f"*{job.get('title', 'Sin título')}* ({score}% match)\n"
            f"Empresa: {job.get('company', 'No especificada')}\n"
            f"Ubicación: {job.get('location', 'Remote')}\n"
            f"Salario: {salary}\n"
            f"Fuente: {job.get('source', 'web')}\n"
            f"[Ver convocatoria]({job.get('url', '')})"
        )

    def _has_enough_profile(self) -> bool:
        """Verifica si el perfil tiene suficiente información."""
        return bool(
            self.user_profile.get("specialty")
            or self.user_profile.get("skills")
            or self.user_profile.get("desired_roles")
        )

    def _profile_terms(self, query: str) -> List[str]:
        """Obtiene términos del perfil para la búsqueda."""
        terms = []
        terms.extend(self._split_terms(query))
        terms.extend(self._split_terms(self.user_profile.get("specialty", "")))
        for key in ("skills", "desired_roles", "locations"):
            for item in self.user_profile.get(key, []):
                terms.extend(self._split_terms(item))
        stopwords = {"engineer", "developer", "senior", "junior", "mid", "trabajo"}
        return sorted({term for term in terms if len(term) > 2 and term not in stopwords})

    def _first_location(self) -> str:
        """Obtiene la primera ubicación del perfil."""
        locations = self.user_profile.get("locations") or ["remote"]
        return locations[0] if isinstance(locations, list) else str(locations)

    def _extract_company(self, entry) -> str:
        """Extrae el nombre de la empresa del título."""
        title = entry.get("title", "")
        if ":" in title:
            return title.split(":")[0].strip()
        if " at " in title:
            return title.split(" at ")[-1].strip()
        return "Empresa no especificada"

    def _extract_location(self, text: str) -> str:
        """Extrae la ubicación del texto."""
        clean_text = re.sub(r"<[^>]+>", " ", text or "")
        location_keywords = [
            "remote", "latam", "latin america", "américa latina",
            "peru", "perú", "lima", "arequipa", "trujillo", "cusco",
            "colombia", "bogotá", "medellín", "cali",
            "mexico", "méxico", "cdmx", "guadalajara",
            "argentina", "buenos aires", "córdoba",
            "chile", "santiago", "valparaíso",
        ]
        match = re.search(
            r"(" + "|".join(location_keywords) + r")",
            clean_text,
            re.IGNORECASE
        )
        return match.group(0).lower() if match else "remote"

    def _extract_salary(self, text: str) -> str:
        """Extrae el salario del texto."""
        patterns = [
            r"\$\d{2,3}[kK]?\s*[-–]?\s*\$?\d{2,3}[kK]?",
            r"\d{2,3}[kK]?\s*[-–]?\s*\d{2,3}[kK]?\s*(USD|dólares?)",
            r"S\/\.\s*\d{1,4}(?:,\d{3})*(?:\.\d{2})?",
            r"\d{1,4}(?:,\d{3})*\s*soles?",
            r"€\d{2,3}[kK]?\s*[-–]?\s*€?\d{2,3}[kK]?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text or "", re.IGNORECASE)
            if match:
                return match.group(0)
        return "No especificado"

    def _is_new_job(self, job: Dict) -> bool:
        """Verifica si un trabajo es nuevo."""
        return self._job_id(job) not in self.seen_jobs

    def _job_id(self, job: Dict) -> str:
        """Genera un ID único para un trabajo."""
        return f"{job.get('company', '')}-{job.get('title', '')}-{job.get('url', '')}"[:180]

    def _job_text(self, job: Dict) -> str:
        """Obtiene el texto completo de un trabajo para búsqueda."""
        return f"{job.get('title', '')} {job.get('company', '')} {job.get('description', '')}".lower()

    def _split_terms(self, value: str) -> List[str]:
        """Divide un valor en términos individuales."""
        if not value:
            return []
        return [
            part.strip().lower()
            for part in re.split(r"[,;/|]+|\s+y\s+|\s+and\s+", str(value))
            if part.strip()
        ]