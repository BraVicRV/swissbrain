import asyncio
import json
from datetime import datetime
from typing import Dict, Any, Tuple
from groq import Groq
from config.settings import SETTINGS
from config.prompts import PRIORITY_ASSESSMENT


class PriorityEngine:
    def __init__(self):
        self.client = Groq(api_key=SETTINGS.GROQ_API_KEY)
        self.critical_keywords = SETTINGS.CRITICAL_KEYWORDS
    
    # >>> FIX 1: Convertir a async para poder usar await
    async def assess(self, finding: Dict[str, Any], user_context: str = "") -> Dict[str, Any]:
        quick_priority = self._quick_assess(finding)
        if quick_priority == "critica":
            return self._build_critical_response(finding)
        
        # >>> FIX 2: Usar await en lugar de llamar directo
        return await self._llm_assess(finding, user_context)
    
    def _quick_assess(self, finding: Dict) -> str:
        text = f"{finding.get('title', '')} {finding.get('content', '')}".lower()
        
        for keyword in self.critical_keywords:
            if keyword.lower() in text:
                return "critica"
        
        if finding.get("module") == "sentinel" and "filtración" in text:
            return "critica"
        if finding.get("module") == "market_watch":
            change = finding.get("metadata", {}).get("price_change_pct", 0)
            if abs(change) > 20:
                return "alta"
        
        return "media"
    
    # >>> FIX 3: Convertir a async
    async def _llm_assess(self, finding: Dict, user_context: str) -> Dict[str, Any]:
        try:
            current_time = datetime.now().strftime("%H:%M")
            
            # >>> FIX 4: Eliminar asyncio.run() anidado, usar await directo
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=SETTINGS.GROQ_MODEL,
                messages=[{
                    "role": "system",
                    "content": PRIORITY_ASSESSMENT.format(
                        finding=json.dumps(finding, ensure_ascii=False),
                        user_context=user_context,
                        current_time=current_time
                    )
                }],
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            return self._apply_night_mode(result)
            
        except Exception as e:
            print(f"Error en LLM assess: {e}")
            return self._fallback_assess(finding)
    
    def _apply_night_mode(self, result: Dict) -> Dict:
        hour = datetime.now().hour
        is_night = SETTINGS.NIGHT_MODE_START <= hour or hour < SETTINGS.NIGHT_MODE_END
        
        if is_night and result.get("nivel") != "critica":
            result["canal"] = "email_daily"
            result["nota_night_mode"] = "Modo nocturno activo. Se notificará en el resumen matutino."
        
        return result
    
    def _build_critical_response(self, finding: Dict) -> Dict:
        return {
            "nivel": "critica",
            "justificacion": "Detectado por heurística de seguridad",
            "canal": "telegram_immediate",
            "mensaje_telegram": self._format_critical_message(finding),
            "requiere_accion_usuario": True,
            "acciones_sugeridas": ["Revisar inmediatamente", "Verificar fuentes"],
            "tiempo_respuesta_esperado": "inmediato"
        }
    
    def _format_critical_message(self, finding: Dict) -> str:
        return (
            f"🚨 *ALERTA CRÍTICA - SwissBrain*\n\n"
            f"*{finding.get('title', 'Sin título')}*\n\n"
            f"{finding.get('content', '')[:500]}...\n\n"
            f"📊 Módulo: `{finding.get('module', 'desconocido')}`\n"
            f"⏰ Detectado: {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"⚡ *Requiere tu atención inmediata*"
        )
    
    def _fallback_assess(self, finding: Dict) -> Dict:
        return {
            "nivel": "media",
            "justificacion": "Fallback por error en evaluación",
            "canal": "telegram_delayed",
            "mensaje_telegram": f"📋 Nuevo hallazgo: {finding.get('title', 'Sin título')}",
            "requiere_accion_usuario": False,
            "acciones_sugeridas": [],
            "tiempo_respuesta_esperado": "4horas"
        }
    
    def should_notify_now(self, finding: Dict, assessment: Dict) -> Tuple[bool, str]:
        canal = assessment.get("canal", "email_daily")
        
        if canal == "telegram_immediate":
            return True, "telegram"
        elif canal == "telegram_delayed":
            return True, "telegram"
        
        return False, canal