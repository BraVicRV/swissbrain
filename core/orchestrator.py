import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from groq import Groq, APIError

from config.settings import SETTINGS
from config.prompts import ORCHESTRATOR_INTENT_CLASSIFICATION, SYNTHESIZER_PROMPT
from core.memory import Memory
from core.priority import PriorityEngine
from bot_telegram.bot import TelegramBot
from utils.logger import logger, log_error, log_api_call


class SwissBrainOrchestrator:
    def __init__(self):
        logger.info("="*60)
        logger.info("INICIANDO SWISSBRAIN ORCHESTRATOR")
        logger.info("="*60)
        
        # Verificar API key antes de crear cliente
        if not SETTINGS.GROQ_API_KEY:
            logger.critical("❌ GROQ_API_KEY está vacía")
            raise ValueError("GROQ_API_KEY no configurada")
        
        logger.info(f"GROQ_API_KEY: {SETTINGS.GROQ_API_KEY[:10]}... (longitud: {len(SETTINGS.GROQ_API_KEY)})")
        logger.info(f"GROQ_MODEL: {SETTINGS.GROQ_MODEL}")
        
        try:
            self.client = Groq(api_key=SETTINGS.GROQ_API_KEY)
            logger.info("✅ Cliente Groq creado exitosamente")
        except Exception as e:
            log_error("Creando cliente Groq", e)
            raise
        
        self.memory = Memory()
        self.priority = PriorityEngine()
        self.telegram = TelegramBot()
        self.modules = {}
        self.running = False
        logger.info("Orquestador inicializado correctamente")
    
    def register_module(self, name: str, module_instance):
        self.modules[name] = module_instance
        logger.info(f"✅ Módulo '{name}' registrado")
    
    async def process_user_message(self, message: str) -> Dict[str, Any]:
        logger.info(f"{'='*60}")
        logger.info(f"MENSAJE RECIBIDO: '{message[:50]}...'")
        logger.info(f"{'='*60}")
        
        # 1. Clasificar intención
        logger.info("[1/4] Clasificando intención...")
        intent = await self._classify_intent(message)
        logger.info(f"Intención detectada: {intent.get('intencion_principal', 'desconocida')}")
        logger.info(f"Urgencia: {intent.get('urgencia', 'desconocida')}")
        logger.info(f"Módulos a activar: {intent.get('modulos_activar', [])}")
        
        # 2. Guardar en memoria
        logger.info("[2/4] Guardando en memoria...")
        self.memory.log_interaction(
            user_message=message,
            intent=intent["intencion_principal"],
            modules_used=intent.get("modulos_activar", []),
            response_summary="",
            priority=intent.get("urgencia", "baja")
        )
        
        if intent.get("tema"):
            self.memory.add_interest(intent["tema"])
            logger.info(f"Tema de interés añadido: {intent['tema']}")
        
        # 3. Ejecutar módulos
        logger.info("[3/4] Ejecutando módulos...")
        results = await self._execute_modules(intent)
        logger.info(f"Módulos ejecutados: {list(results.keys())}")
        
        # 4. Sintetizar solo si hay múltiples módulos CON datos válidos
        valid_results = {k: v for k, v in results.items() 
                        if isinstance(v, dict) and v.get("status") == "completed"}
        
        if len(valid_results) > 1:
            logger.info("[4/4] Sintetizando resultados...")
            synthesized = await self._synthesize_results(valid_results, intent.get("tema", ""))
            results["synthesized"] = synthesized
        elif len(valid_results) == 0 and len(results) > 0:
            logger.warning("Ningún módulo devolvió datos válidos, omitiendo síntesis")
        
        # 5. Procesar hallazgos
        logger.info("Procesando hallazgos...")
        await self._process_findings(results, intent)
        
        logger.info("Procesamiento completado")
        return results
    
    async def _classify_intent(self, message: str) -> Dict[str, Any]:
        logger.debug(f"Prompt de clasificación (primeros 100 chars): {ORCHESTRATOR_INTENT_CLASSIFICATION[:100]}...")
        
        try:
            logger.info("Llamando a Groq API (classify_intent)...")
            log_api_call("Groq", "chat.completions.create", "REQUEST", f"model={SETTINGS.GROQ_MODEL}")
            
            start_time = datetime.now()
            
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=SETTINGS.GROQ_MODEL,
                messages=[{
                    "role": "system",
                    "content": ORCHESTRATOR_INTENT_CLASSIFICATION.format(message=message)
                }],
                temperature=0.1,
                max_tokens=400,
                response_format={"type": "json_object"}
            )
            
            elapsed = (datetime.now() - start_time).total_seconds()
            log_api_call("Groq", "chat.completions.create", "SUCCESS", f"tiempo={elapsed:.2f}s")
            
            result_text = response.choices[0].message.content
            logger.debug(f"Respuesta cruda de Groq: {result_text[:200]}...")
            
            result = json.loads(result_text)
            logger.info(f"✅ Intención clasificada correctamente: {result.get('intencion_principal')}")
            return result
            
        except APIError as e:
            log_error("Groq API Error en classify_intent", e)
            logger.error(f"Status code: {e.status_code if hasattr(e, 'status_code') else 'N/A'}")
            logger.error(f"Response: {e.response if hasattr(e, 'response') else 'N/A'}")
            return self._fallback_intent(message, f"APIError: {e}")
            
        except json.JSONDecodeError as e:
            log_error("JSON Decode Error en classify_intent", e)
            return self._fallback_intent(message, "JSON invalido")
            
        except Exception as e:
            log_error("Error general en classify_intent", e)
            return self._fallback_intent(message, str(e))
    
    def _fallback_intent(self, message: str, error_reason: str) -> Dict[str, Any]:
        logger.warning(f"Usando fallback de intención. Razón: {error_reason}")
        return {
            "intencion_principal": "conversacion",
            "urgencia": "baja",
            "modulos_activar": [],
            "tema": message[:50],
            "error": error_reason
        }
    
    async def _execute_modules(self, intent: Dict) -> Dict[str, Any]:
        results = {}
        modules_to_run = intent.get("modulos_activar", [])
        
        logger.info(f"Módulos a ejecutar: {modules_to_run}")
        
        if not modules_to_run:
            logger.info("No hay módulos específicos, usando respuesta directa")
            results["conversacion"] = await self._direct_response(intent)
            return results
        
        for module_name in modules_to_run:
            logger.info(f"Ejecutando módulo: {module_name}")
            
            if module_name in self.modules:
                try:
                    module = self.modules[module_name]
                    params = intent.get("parametros", {})
                    params["tema"] = intent.get("tema", "")
                    
                    logger.debug(f"Parámetros: {params}")
                    
                    start_time = datetime.now()
                    result = await module.execute(params)
                    elapsed = (datetime.now() - start_time).total_seconds()
                    
                    logger.info(f"✅ Módulo {module_name} completado en {elapsed:.2f}s (status: {result.get('status', 'unknown')})")
                    results[module_name] = result
                    
                except Exception as e:
                    log_error(f"Ejecutando módulo {module_name}", e)
                    results[module_name] = {
                        "error": str(e),
                        "status": "failed"
                    }
            else:
                logger.error(f"❌ Módulo '{module_name}' no registrado")
                results[module_name] = {
                    "error": f"Módulo '{module_name}' no registrado",
                    "status": "not_found"
                }
        
        return results
    
    async def _synthesize_results(self, results: Dict, topic: str) -> str:
        """Sintetiza resultados de múltiples módulos. Solo recibe módulos con status=completed."""
        # Preparar datos para el LLM, incluyendo solo contenido relevante
        synthesis_data = {}
        for module_name, result in results.items():
            if isinstance(result, dict) and "findings" in result:
                findings_data = []
                for f in result["findings"]:
                    findings_data.append({
                        "title": f.get("title", ""),
                        "content": f.get("content", "")[:1000],  # Limitar para no saturar
                        "sources": f.get("sources", [])
                    })
                synthesis_data[module_name] = findings_data
        
        if not synthesis_data:
            return "No hay datos suficientes para generar una síntesis."
        
        module_data = json.dumps(synthesis_data, ensure_ascii=False, indent=2)
        
        try:
            logger.info("Llamando a Groq API (synthesize)...")
            
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=SETTINGS.GROQ_MODEL,
                messages=[{
                    "role": "system",
                    "content": SYNTHESIZER_PROMPT.format(
                        module_data=module_data[:4000],
                        topic=topic
                    )
                }],
                temperature=0.3,
                max_tokens=2000
            )
            
            logger.info("✅ Síntesis completada")
            return response.choices[0].message.content
            
        except Exception as e:
            log_error("Error en síntesis", e)
            return f"Error en síntesis: {str(e)}"
    
    async def _process_findings(self, results: Dict, intent: Dict):
        for module_name, result in results.items():
            if module_name == "synthesized":
                continue
            
            # >>> FIX: Saltar módulos con error o sin datos válidos
            if isinstance(result, dict):
                if result.get("status") in ("failed", "partial"):
                    logger.warning(f"Módulo {module_name} devolvió status={result.get('status')}, saltando...")
                    # Enviar el mensaje de error/información directamente
                    if result.get("findings"):
                        finding = result["findings"][0]
                        await self.telegram.send_message(
                            f"⚠️ *{finding.get('title', 'Aviso')}*\n\n"
                            f"{finding.get('content', 'Sin información')}",
                            parse_mode="Markdown"
                        )
                    continue
                
                if "findings" not in result or not result["findings"]:
                    logger.warning(f"Módulo {module_name} sin findings, saltando...")
                    continue
            else:
                continue
            
            logger.info(f"Procesando {len(result['findings'])} hallazgos de {module_name}")
            
            for finding in result["findings"]:
                original_priority = finding.get("priority", "media")
                
                finding_id = self.memory.add_finding(
                    module=module_name,
                    title=finding.get("title", "Sin título"),
                    content=finding.get("content", ""),
                    priority=original_priority
                )
                
                user_context = self._build_user_context()
                
                # >>> FIX: Agregar await porque assess() ahora es async
                assessment = await self.priority.assess(finding, user_context)
                
                # Override para módulos informativos (no alertas)
                if module_name in ["brief", "conversacion", "guardian"]:
                    assessment["nivel"] = "baja"
                    assessment["canal"] = "telegram_delayed"
                    assessment["mensaje_telegram"] = finding.get("content", "")
                    assessment["requiere_accion_usuario"] = False
                    assessment["acciones_sugeridas"] = []
                
                should_notify, channel = self.priority.should_notify_now(
                    finding, assessment
                )
                
                if should_notify and channel == "telegram":
                    logger.info(f"Enviando mensaje por Telegram (módulo: {module_name}, prioridad: {assessment['nivel']})")
                    
                    if module_name in ["brief", "conversacion", "guardian"]:
                        await self.telegram.send_message(
                            assessment["mensaje_telegram"],
                            parse_mode="Markdown"
                        )
                    else:
                        await self.telegram.send_alert(
                            assessment["mensaje_telegram"],
                            priority=assessment["nivel"],
                            actions=assessment.get("acciones_sugeridas", [])
                        )
                    self.memory.mark_notified(finding_id)
    
    def _build_user_context(self) -> str:
        interests = self.memory.get_interests()
        interests_text = ", ".join([i["topic"] for i in interests[:5]])
        alerts = self.memory.get_active_alerts()
        
        return f"Intereses: {interests_text} | Alertas: {len(alerts)}"
    
    async def _direct_response(self, intent: Dict) -> Dict:
        logger.info("Generando respuesta directa")
        return {
            "type": "conversacion",
            "message": "Entendido. ¿En qué más puedo ayudarte?"
        }
    
    async def run_autonomous_loop(self):
        self.running = True
        logger.info("="*60)
        logger.info("LOOP AUTÓNOMO INICIADO")
        logger.info("="*60)
        
        while self.running:
            try:
                logger.debug("Ejecutando checks autónomos...")
                await self._run_autonomous_checks()
                await self._check_scheduled_tasks()
                logger.debug(f"Esperando {SETTINGS.CHECK_INTERVAL_MINUTES} minutos...")
                await asyncio.sleep(SETTINGS.CHECK_INTERVAL_MINUTES * 60)
                
            except Exception as e:
                log_error("Loop autónomo", e)
                await asyncio.sleep(60)
    
    async def _run_autonomous_checks(self):
        for name, module in self.modules.items():
            if hasattr(module, 'autonomous_check'):
                try:
                    logger.debug(f"Check autónomo: {name}")
                    findings = await module.autonomous_check()
                    
                    if findings:
                        logger.info(f"Módulo {name} encontró {len(findings)} hallazgos")
                        
                        for finding in findings:
                            finding_id = self.memory.add_finding(
                                module=name,
                                title=finding.get("title", "Hallazgo autónomo"),
                                content=finding.get("content", ""),
                                priority=finding.get("priority", "media")
                            )
                            
                            user_context = self._build_user_context()
                            
                            # >>> FIX: Agregar await porque assess() ahora es async
                            assessment = await self.priority.assess(finding, user_context)
                            
                            # Override para brief autónomo
                            if name == "brief":
                                assessment["nivel"] = "baja"
                                assessment["canal"] = "telegram_delayed"
                                assessment["mensaje_telegram"] = finding.get("content", "")
                                assessment["requiere_accion_usuario"] = False
                                assessment["acciones_sugeridas"] = []
                            
                            should_notify, channel = self.priority.should_notify_now(
                                finding, assessment
                            )
                            
                            if should_notify and channel == "telegram":
                                if name == "brief":
                                    await self.telegram.send_message(
                                        assessment["mensaje_telegram"],
                                        parse_mode="Markdown"
                                    )
                                else:
                                    await self.telegram.send_alert(
                                        assessment["mensaje_telegram"],
                                        priority=assessment["nivel"],
                                        actions=assessment.get("acciones_sugeridas", [])
                                    )
                                self.memory.mark_notified(finding_id)
                                
                except Exception as e:
                    log_error(f"Check autónomo de {name}", e)
    
    async def _check_scheduled_tasks(self):
        now = datetime.now()
        
        if now.hour == SETTINGS.DAILY_BRIEF_HOUR and now.minute < 5:
            logger.info("Generando brief diario programado")
            if "brief" in self.modules:
                brief = await self.modules["brief"].generate_daily_brief()
                await self.telegram.send_message(
                    f"📰 *Brief Diario - {now.strftime('%d/%m/%Y')}*\n\n{brief}",
                    parse_mode="Markdown"
                )
    
    def stop(self):
        self.running = False
        logger.info("🛑 SwissBrain detenido")