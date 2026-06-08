import asyncio
import json
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict

from groq import APIError, Groq

from config.prompts import (
    CONVERSATIONAL_RESPONSE_PROMPT,
    ORCHESTRATOR_INTENT_CLASSIFICATION,
    SYNTHESIZER_PROMPT,
)
from config.settings import SETTINGS
from core.memory import Memory
from core.priority import PriorityEngine
from utils.logger import log_api_call, log_error, logger

class SwissBrainOrchestrator:
    def __init__(self):
        logger.info("=" * 60)
        logger.info("INICIANDO SWISSBRAIN ORCHESTRATOR")
        logger.info("=" * 60)

        if not SETTINGS.GROQ_API_KEY:
            logger.critical("GROQ_API_KEY no configurada")
            raise ValueError("GROQ_API_KEY no configurada")

        logger.info(f"GROQ_MODEL: {SETTINGS.GROQ_MODEL}")

        try:
            self.client = Groq(api_key=SETTINGS.GROQ_API_KEY)
            logger.info("Cliente Groq creado exitosamente")
        except Exception as e:
            log_error("Creando cliente Groq", e)
            raise

        self.memory = Memory()
        self.priority = PriorityEngine()
        self.telegram = None
        self.modules = {}
        self.running = False
        self.last_user_topic = None  # --- NUEVO: Guardar el último tema del usuario ---
        logger.info("Orquestador inicializado correctamente")

    def register_module(self, name: str, module_instance):
        self.modules[name] = module_instance
        logger.info(f"Modulo '{name}' registrado")

    async def process_user_message(self, message: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info(f"MENSAJE RECIBIDO: '{message[:80]}...'")
        logger.info("=" * 60)

        # Guardar el último tema solicitado (para respuestas cortas como "sí")
        if message.strip().lower() not in ["sí", "si", "ok", "claro", "ale", "ajá", "sip"]:
            self.last_user_topic = message  # Guardar el último tema

        profile_update = self._extract_profile_update(message)
        if profile_update:
            self.memory.update_user_profile(profile_update)
            if "guardian" in self.modules:
                self.modules["guardian"].configure_user_profile(self.memory.get_user_profile())

            summary = self._format_profile_update_response(profile_update)
            self.memory.log_interaction(
                user_message=message,
                intent="perfil_usuario",
                modules_used=[],
                response_summary=summary,
                priority="baja",
            )
            return {"conversacion": {"type": "conversacion", "message": summary}}

        intent = self._build_job_request_intent(message) or await self._classify_intent(message)
        logger.info(f"Intencion detectada: {intent.get('intencion_principal', 'desconocida')}")
        logger.info(f"Tipo de interaccion: {intent.get('tipo_interaccion', 'desconocido')}")
        logger.info(f"Urgencia: {intent.get('urgencia', 'desconocida')}")
        logger.info(f"Modulos a activar: {intent.get('modulos_activar', [])}")

        self.memory.log_interaction(
            user_message=message,
            intent=intent.get("intencion_principal", "desconocida"),
            modules_used=intent.get("modulos_activar", []),
            response_summary="",
            priority=intent.get("urgencia", "baja"),
        )

        if intent.get("tema") and intent.get("tipo_interaccion") != "conversacion":
            self.memory.add_interest(intent["tema"])

        if intent.get("necesita_aclaracion"):
            response = await self._direct_response(intent, message)
            self._update_interaction_summary(message, response.get("message", ""))
            return {"conversacion": response}

        modules_to_run = intent.get("modulos_activar", [])
        task_id = None
        if modules_to_run:
            task_id = self.memory.add_task(
                user_message=message,
                intent=intent.get("intencion_principal", "desconocida"),
                topic=intent.get("tema", ""),
                modules_used=modules_to_run,
            )
            logger.info(f"Tarea registrada con id={task_id}")

        results = await self._execute_modules(intent, message)
        logger.info(f"Modulos ejecutados: {list(results.keys())}")

        valid_results = {
            key: value
            for key, value in results.items()
            if isinstance(value, dict) and value.get("status") == "completed"
        }

        if len(valid_results) > 1:
            synthesized = await self._synthesize_results(valid_results, intent.get("tema", ""))
            results["synthesized"] = synthesized
        elif len(valid_results) == 0 and len(results) > 0:
            logger.warning("Ningun modulo devolvio datos validos; se omite sintesis")

        await self._process_findings(results, intent, notify=False)

        summary = self._summarize_result_for_memory(results)
        self._update_interaction_summary(message, summary)

        if task_id:
            has_errors = any(
                isinstance(value, dict) and value.get("status") in ("failed", "not_found")
                for value in results.values()
            )
            task_status = "failed" if has_errors else "completed"
            self.memory.update_task(
                task_id,
                status=task_status,
                result_summary=summary,
                error="" if not has_errors else "Uno o mas modulos fallaron",
            )
            results["task"] = {
                "id": task_id,
                "status": task_status,
                "summary": summary,
                "modules": modules_to_run,
            }

        logger.info("Procesamiento completado")
        return results

    async def _classify_intent(self, message: str) -> Dict[str, Any]:
        try:
            logger.info("Llamando a Groq API (classify_intent)")
            log_api_call("Groq", "chat.completions.create", "REQUEST", f"model={SETTINGS.GROQ_MODEL}")
            start_time = datetime.now()

            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=SETTINGS.GROQ_MODEL,
                messages=[{
                    "role": "system",
                    "content": ORCHESTRATOR_INTENT_CLASSIFICATION.format(message=message),
                }],
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            elapsed = (datetime.now() - start_time).total_seconds()
            log_api_call("Groq", "chat.completions.create", "SUCCESS", f"tiempo={elapsed:.2f}s")

            result = json.loads(response.choices[0].message.content)
            return self._normalize_intent(result)

        except APIError as e:
            log_error("Groq API Error en classify_intent", e)
            return self._fallback_intent(message, f"APIError: {e}")
        except json.JSONDecodeError as e:
            log_error("JSON Decode Error en classify_intent", e)
            return self._fallback_intent(message, "JSON invalido")
        except Exception as e:
            log_error("Error general en classify_intent", e)
            return self._fallback_intent(message, str(e))

    def _normalize_intent(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        allowed_modules = {"research", "market_watch", "brief", "sentinel", "guardian"}
        modules = intent.get("modulos_activar") or []
        if not isinstance(modules, list):
            modules = []
        intent["modulos_activar"] = [module for module in modules if module in allowed_modules]

        if intent.get("intencion_principal") == "conversacion":
            intent["modulos_activar"] = []

        intent.setdefault("intencion_principal", "conversacion")
        intent.setdefault("intenciones_secundarias", [])
        intent.setdefault("urgencia", "baja")
        intent.setdefault("tipo_interaccion", "tarea" if intent["modulos_activar"] else "conversacion")
        intent.setdefault("tema", "")
        intent.setdefault("accion_sugerida", "")
        intent.setdefault("parametros", {})
        intent.setdefault("necesita_aclaracion", False)
        intent.setdefault("pregunta_aclaratoria", "")
        return intent

    def _fallback_intent(self, message: str, error_reason: str) -> Dict[str, Any]:
        logger.warning(f"Usando fallback de intencion. Razon: {error_reason}")
        return {
            "intencion_principal": "conversacion",
            "intenciones_secundarias": [],
            "urgencia": "baja",
            "tipo_interaccion": "conversacion",
            "modulos_activar": [],
            "tema": message[:80],
            "accion_sugerida": "Responder de forma conversacional",
            "parametros": {},
            "necesita_aclaracion": False,
            "pregunta_aclaratoria": "",
            "error": error_reason,
        }

    async def _execute_modules(self, intent: Dict[str, Any], message: str) -> Dict[str, Any]:
        results = {}
        modules_to_run = intent.get("modulos_activar", [])

        if not modules_to_run:
            logger.info("No hay modulos especificos; usando respuesta directa")
            results["conversacion"] = await self._direct_response(intent, message)
            return results

        for module_name in modules_to_run:
            logger.info(f"Ejecutando modulo: {module_name}")
            if module_name not in self.modules:
                results[module_name] = {
                    "error": f"Modulo '{module_name}' no registrado",
                    "status": "not_found",
                }
                continue

            try:
                module = self.modules[module_name]
                params = dict(intent.get("parametros", {}))
                params["tema"] = intent.get("tema", "")
                if module_name == "guardian":
                    params["user_profile"] = self.memory.get_user_profile()

                start_time = datetime.now()
                result = await module.execute(params)
                elapsed = (datetime.now() - start_time).total_seconds()

                logger.info(
                    f"Modulo {module_name} completado en {elapsed:.2f}s "
                    f"(status: {result.get('status', 'unknown')})"
                )
                results[module_name] = result
            except Exception as e:
                log_error(f"Ejecutando modulo {module_name}", e)
                results[module_name] = {
                    "error": str(e),
                    "status": "failed",
                }

        return results

    async def _synthesize_results(self, results: Dict[str, Any], topic: str) -> str:
        synthesis_data = {}
        for module_name, result in results.items():
            if isinstance(result, dict) and "findings" in result:
                synthesis_data[module_name] = [
                    {
                        "title": finding.get("title", ""),
                        "content": finding.get("content", "")[:1000],
                        "sources": finding.get("sources", []),
                    }
                    for finding in result["findings"]
                ]

        if not synthesis_data:
            return "No hay datos suficientes para generar una síntesis."

        module_data = json.dumps(synthesis_data, ensure_ascii=False, indent=2)

        try:
            logger.info("Llamando a Groq API (synthesize)")
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=SETTINGS.GROQ_MODEL,
                messages=[{
                    "role": "system",
                    "content": SYNTHESIZER_PROMPT.format(
                        module_data=module_data[:4000],
                        topic=topic,
                    ),
                }],
                temperature=0.3,
                max_tokens=2000,
            )
            return response.choices[0].message.content
        except Exception as e:
            log_error("Error en sintesis", e)
            return f"Error en síntesis: {str(e)}"

    async def _process_findings(self, results: Dict[str, Any], intent: Dict[str, Any], notify: bool = True):
        for module_name, result in results.items():
            if module_name in ("synthesized", "task"):
                continue

            if not isinstance(result, dict):
                continue

            if result.get("status") in ("failed", "partial"):
                if notify and self.telegram and result.get("findings"):
                    finding = result["findings"][0]
                    await self.telegram.send_message(
                        f"⚠️ *{finding.get('title', 'Aviso')}*\n\n"
                        f"{finding.get('content', 'Sin información')}",
                        parse_mode="Markdown",
                    )
                continue

            if "findings" not in result or not result["findings"]:
                continue

            for finding in result["findings"]:
                original_priority = finding.get("priority", "media")
                finding_id = self.memory.add_finding(
                    module=module_name,
                    title=finding.get("title", "Sin título"),
                    content=finding.get("content", ""),
                    priority=original_priority,
                )

                if not notify:
                    continue

                user_context = self._build_user_context()
                assessment = await self.priority.assess(finding, user_context)

                if module_name in ["brief", "conversacion", "guardian", "research", "market_watch"]:
                    assessment["nivel"] = "baja"
                    assessment["canal"] = "telegram_delayed"
                    assessment["mensaje_telegram"] = finding.get("content", "")
                    assessment["requiere_accion_usuario"] = False
                    assessment["acciones_sugeridas"] = []

                should_notify, channel = self.priority.should_notify_now(finding, assessment)
                if notify and self.telegram and should_notify and channel == "telegram":
                    if module_name in ["brief", "conversacion", "guardian", "research", "market_watch"]:
                        await self.telegram.send_message(
                            assessment["mensaje_telegram"],
                            parse_mode="Markdown",
                        )
                    else:
                        await self.telegram.send_alert(
                            assessment["mensaje_telegram"],
                            priority=assessment["nivel"],
                            actions=assessment.get("acciones_sugeridas", []),
                        )
                    self.memory.mark_notified(finding_id)

    def _build_user_context(self) -> str:
        interests = self.memory.get_interests()
        interests_text = ", ".join([i["topic"] for i in interests[:5]])
        alerts = self.memory.get_active_alerts()
        profile = self.memory.get_user_profile()
        specialty = profile.get("specialty", "sin especialidad registrada")
        skills = ", ".join(profile.get("skills", [])[:6]) if isinstance(profile.get("skills"), list) else profile.get("skills", "")
        return (
            f"Intereses: {interests_text} | Alertas activas: {len(alerts)} | "
            f"Especialidad: {specialty} | Skills: {skills}"
        )

    async def _direct_response(self, intent: Dict[str, Any], message: str) -> Dict[str, Any]:
        logger.info("Generando respuesta directa")

        if intent.get("necesita_aclaracion") and intent.get("pregunta_aclaratoria"):
            return {
                "type": "conversacion",
                "message": intent["pregunta_aclaratoria"],
            }

        try:
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=SETTINGS.GROQ_MODEL,
                messages=[{
                    "role": "system",
                    "content": CONVERSATIONAL_RESPONSE_PROMPT.format(
                        history=self._format_recent_history(),
                        intent=json.dumps(intent, ensure_ascii=False),
                        message=message,
                    ),
                }],
                temperature=0.55,
                max_tokens=350,
            )
            answer = response.choices[0].message.content.strip()
        except Exception as e:
            log_error("Generando respuesta conversacional", e)
            answer = "Te escucho. Puedo conversar contigo o convertir lo que me pidas en una tarea concreta."

        return {
            "type": "conversacion",
            "message": answer,
        }

    def _format_recent_history(self) -> str:
        recent = list(reversed(self.memory.get_recent_interactions(limit=6)))
        if not recent:
            return "Sin historial reciente."

        lines = []
        for item in recent:
            user_message = (item.get("user_message") or "")[:160]
            intent = item.get("intent") or "desconocida"
            summary = (item.get("response_summary") or "")[:160]
            lines.append(f"- Usuario: {user_message} | intención: {intent} | respuesta: {summary}")
        return "\n".join(lines)

    def _summarize_result_for_memory(self, results: Dict[str, Any]) -> str:
        if "synthesized" in results:
            return str(results["synthesized"])[:500]
        if "conversacion" in results:
            return results["conversacion"].get("message", "")[:500]

        summaries = []
        for module_name, result in results.items():
            if not isinstance(result, dict):
                continue
            if result.get("findings"):
                first = result["findings"][0]
                summaries.append(f"{module_name}: {first.get('title', 'Sin título')}")
            elif result.get("error"):
                summaries.append(f"{module_name}: {result['error']}")
        return " | ".join(summaries)[:500] or "Tarea procesada"

    def _update_interaction_summary(self, user_message: str, response_summary: str):
        try:
            with sqlite3.connect(self.memory.db_path) as conn:
                conn.execute("""
                    UPDATE interactions
                    SET response_summary = ?
                    WHERE id = (
                        SELECT id
                        FROM interactions
                        WHERE user_message = ?
                        ORDER BY timestamp DESC
                        LIMIT 1
                    )
                """, (response_summary[:500], user_message))
        except Exception as e:
            log_error("Actualizando resumen de interaccion", e)

    def _extract_profile_update(self, message: str) -> Dict[str, Any]:
        text = message.strip()
        lower = text.lower()
        update = {}

        explicit_profile = any(
            keyword in lower
            for keyword in [
                "mi especialidad",
                "especialidad:",
                "me especializo",
                "mi perfil",
                "perfil laboral",
                "mis habilidades",
                "mis skills",
                "trabajo como",
                "soy desarrollador",
                "soy programador",
                "soy ingeniero",
            ]
        )
        if not explicit_profile:
            return {}

        specialty_patterns = [
            r"especialidad\s*:\s*(.+)",
            r"mi especialidad es\s+(.+)",
            r"me especializo en\s+(.+)",
            r"soy\s+(?:un|una)?\s*(desarrollador.+|programador.+|ingeniero.+)",
            r"trabajo como\s+(.+)",
        ]
        for pattern in specialty_patterns:
            match = re.search(pattern, lower, re.IGNORECASE)
            if match:
                specialty = self._clean_profile_phrase(match.group(1))
                if specialty:
                    update["specialty"] = specialty
                    update["desired_roles"] = [specialty]
                break

        skills_patterns = [
            r"(?:mis habilidades son|mis skills son|sé|se|uso|manejo)\s+(.+)",
            r"(?:con experiencia en|experiencia en)\s+(.+)",
        ]
        for pattern in skills_patterns:
            match = re.search(pattern, lower, re.IGNORECASE)
            if match:
                skills = self._split_profile_terms(match.group(1))
                if skills:
                    update["skills"] = skills
                break

        location_match = re.search(r"(?:busco en|ubicaci[oó]n|remoto en)\s+([a-záéíóúñ,\s]+)$", lower, re.IGNORECASE)
        if location_match:
            locations = self._split_profile_terms(location_match.group(1))
            if locations:
                update["locations"] = locations

        if any(keyword in lower for keyword in ["perfil laboral", "mi perfil", "mi especialidad", "me especializo", "trabajo como"]):
            update.setdefault("job_search_enabled", True)

        return update

    def _build_job_request_intent(self, message: str) -> Dict[str, Any]:
        lower = message.lower().strip()
        job_keywords = [
            "ofertas laborales",
            "oportunidades laborales",
            "convocatorias",
            "trabajos",
            "empleos",
            "vacantes",
            "puestos",
        ]
        if not any(keyword in lower for keyword in job_keywords):
            return {}

        role = self._extract_job_role(lower)
        topic = f"Oportunidades laborales {role}".strip()
        return {
            "intencion_principal": "guardian",
            "intenciones_secundarias": [],
            "urgencia": "media",
            "tipo_interaccion": "tarea",
            "tema": topic,
            "accion_sugerida": "Buscar convocatorias laborales relevantes",
            "modulos_activar": ["guardian"],
            "parametros": {
                "query": role or topic,
                "location": "remote",
            },
            "necesita_aclaracion": False,
            "pregunta_aclaratoria": "",
        }

    def _extract_job_role(self, lower_message: str) -> str:
        patterns = [
            r"(?:para|como|de)\s+(desarrollador[a]?\s+[a-záéíóúñ\s]+)",
            r"(?:para|como|de)\s+(programador[a]?\s+[a-záéíóúñ\s]+)",
            r"(frontend|backend|fullstack|full stack|devops|data engineer|mobile)",
        ]
        for pattern in patterns:
            match = re.search(pattern, lower_message, re.IGNORECASE)
            if match:
                return self._clean_profile_phrase(match.group(1))
        return ""

    def _clean_profile_phrase(self, value: str) -> str:
        value = re.split(r"\s+(?:y|con|usando|en|para)\s+", value, maxsplit=1)[0]
        return value.strip(" .,:;")

    def _split_profile_terms(self, value: str) -> list:
        value = re.sub(r"\b(?:y|and)\b", ",", value)
        return [part.strip(" .,:;") for part in re.split(r"[,;/|]+", value) if part.strip(" .,:;")]

    def _format_profile_update_response(self, update: Dict[str, Any]) -> str:
        profile = self.memory.get_user_profile()
        specialty = profile.get("specialty", "no definida")
        skills = profile.get("skills", [])
        skills_text = ", ".join(skills[:8]) if isinstance(skills, list) and skills else "por completar"
        return (
            "Perfecto, guardé tu perfil laboral.\n\n"
            f"Especialidad: *{specialty}*\n"
            f"Habilidades: *{skills_text}*\n\n"
            "Desde ahora Guardian buscará convocatorias con mejor coincidencia y te avisará cuando encuentre algo útil."
        )

    async def run_autonomous_loop(self):
        self.running = True
        logger.info("=" * 60)
        logger.info("LOOP AUTONOMO INICIADO")
        logger.info("=" * 60)

        while self.running:
            try:
                await self._run_autonomous_checks()
                await self._check_scheduled_tasks()
                await asyncio.sleep(SETTINGS.CHECK_INTERVAL_MINUTES * 60)
            except Exception as e:
                log_error("Loop autonomo", e)
                await asyncio.sleep(60)

    async def _run_autonomous_checks(self):
        if not self.telegram:
            return

        await self._ensure_job_profile_onboarding()

        for name, module in self.modules.items():
            if not hasattr(module, "autonomous_check"):
                continue

            try:
                if name == "guardian":
                    profile = self.memory.get_user_profile()
                    module.configure_user_profile(profile)
                    if not self.memory.has_job_profile():
                        continue

                findings = await module.autonomous_check()
                if not findings:
                    continue

                logger.info(f"Modulo {name} encontro {len(findings)} hallazgos")
                for finding in findings:
                    finding_id = self.memory.add_finding(
                        module=name,
                        title=finding.get("title", "Hallazgo autonomo"),
                        content=finding.get("content", ""),
                        priority=finding.get("priority", "media"),
                    )

                    assessment = await self.priority.assess(finding, self._build_user_context())
                    if name == "brief":
                        assessment["nivel"] = "baja"
                        assessment["canal"] = "telegram_delayed"
                        assessment["mensaje_telegram"] = finding.get("content", "")
                        assessment["requiere_accion_usuario"] = False
                        assessment["acciones_sugeridas"] = []

                    should_notify, channel = self.priority.should_notify_now(finding, assessment)
                    if should_notify and channel == "telegram":
                        if name == "brief":
                            await self.telegram.send_message(
                                assessment["mensaje_telegram"],
                                parse_mode="Markdown",
                            )
                        else:
                            await self.telegram.send_alert(
                                assessment["mensaje_telegram"],
                                priority=assessment["nivel"],
                                actions=assessment.get("acciones_sugeridas", []),
                            )
                        self.memory.mark_notified(finding_id)
            except Exception as e:
                log_error(f"Check autonomo de {name}", e)

    async def _ensure_job_profile_onboarding(self):
        profile = self.memory.get_user_profile()
        if self.memory.has_job_profile():
            return
        if profile.get("job_profile_prompted"):
            return

        await self.telegram.send_message(
            "Para que pueda buscar convocatorias realmente útiles, necesito conocer tu perfil laboral.\n\n"
            "Respóndeme algo como:\n"
            "`Mi especialidad es backend Python y mis habilidades son FastAPI, APIs, automatización, Docker`",
            parse_mode="Markdown",
        )
        self.memory.update_user_profile({"job_profile_prompted": True})

    async def _check_scheduled_tasks(self):
        if not self.telegram:
            return

        now = datetime.now()
        if now.hour == SETTINGS.DAILY_BRIEF_HOUR and now.minute < 5:
            logger.info("Generando brief diario programado")
            if "brief" in self.modules:
                brief = await self.modules["brief"].generate_daily_brief()
                await self.telegram.send_message(
                    f"📰 *Brief Diario - {now.strftime('%d/%m/%Y')}*\n\n{brief}",
                    parse_mode="Markdown",
                )

    # --- NUEVOS MÉTODOS PARA AUTONOMÍA ---
    async def _send_daily_brief(self):
        """Envía un brief diario automático a las 8 AM."""
        if "brief" not in self.modules or not self.telegram:
            return

        try:
            brief = await self.modules["brief"].generate_daily_brief()
            if brief:
                await self.telegram.send_message(
                    f"📰 *Brief Diario Automático - {datetime.now().strftime('%d/%m/%Y')}*\n\n{brief}",
                    parse_mode="Markdown"
                )
        except Exception as e:
            log_error("Error en brief diario automático", e)

    async def _check_critical_vulns(self):
        """Revisa vulnerabilidades críticas y alerta si es necesario."""
        if "sentinel" not in self.modules or not self.telegram:
            return

        try:
            findings = await self.modules["sentinel"].autonomous_check()
            for finding in findings:
                if finding.get("priority") == "critica":
                    await self.telegram.send_alert(
                        finding.get("content", ""),
                        priority="critica",
                        actions=finding.get("metadata", {}).get("acciones_sugeridas", [])
                    )
        except Exception as e:
            log_error("Error en check de vulnerabilidades autónomo", e)

    def stop(self):
        self.running = False
        logger.info("SwissBrain detenido")