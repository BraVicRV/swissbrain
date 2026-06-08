import asyncio
import re
from typing import Dict, List

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from config.settings import SETTINGS

def clean_rss_escapes(text: str) -> str:
    """Limpia escapes comunes de RSS/HTML para Telegram."""
    if not text:
        return ""

    literal_replacements = {
        r"\-": "-",
        r"\.": ".",
        r"\_": "_",
        r"\[": "[",
        r"\]": "]",
        r"\(": "(",
        r"\)": ")",
        r"\*": "*",
        r"\`": "`",
        r"\>": ">",
        r"\#": "#",
        r"\+": "+",
        r"\=": "=",
        r"\|": "|",
        r"\{": "{",
        r"\}": "}",
        r"\!": "!",
        "&nbsp;": " ",
    }

    for old, new in literal_replacements.items():
        text = text.replace(old, new)

    text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"[\2](\1)", text)
    text = re.sub(r"<img[^>]+>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text

def to_plain_text(text: str) -> str:
    """Convierte Markdown simple a texto plano para fallback robusto."""
    text = clean_rss_escapes(text or "")
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1: \2", text)
    text = re.sub(r"[*_`~]", "", text)
    return text

class TelegramBot:
    def __init__(self):
        self.bot = Bot(token=SETTINGS.TELEGRAM_BOT_TOKEN)
        self.chat_id = SETTINGS.TELEGRAM_CHAT_ID
        self.orchestrator = None

    def set_orchestrator(self, orchestrator):
        self.orchestrator = orchestrator

    def _clasificar_solicitud(self, texto: str) -> str:
        """Clasifica si el mensaje es charla, consulta o tarea."""
        texto = texto.lower()

        palabras_tarea = [
            "investiga", "genera", "haz", "crea", "reporte", "analiza",
            "busca", "monitorea", "prepara", "alertame", "revisa"
        ]
        if any(palabra in texto for palabra in palabras_tarea):
            return "tarea"

        if "?" in texto or any(
            palabra in texto
            for palabra in ["qué", "cómo", "cuándo", "dónde", "por qué", "cuánto"]
        ):
            return "consulta"

        return "charla"

    async def _send_with_fallback(
        self,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup=None,
        chat_id=None,
    ) -> bool:
        """Envía por Telegram y cae a texto plano si Markdown o red fallan."""
        chat_id = chat_id or self.chat_id
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=clean_rss_escapes((text or "")[:4096]),
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=False,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
            )
            return True
        except BadRequest as e:
            print(f"Telegram no aceptó Markdown, reenviando plano: {e}")
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=to_plain_text(text)[:4096],
                    reply_markup=reply_markup,
                    disable_web_page_preview=False,
                    read_timeout=30,
                    write_timeout=30,
                    connect_timeout=30,
                )
                return True
            except TelegramError as e2:
                print(f"Error enviando mensaje plano: {e2}")
                return False
        except RetryAfter as e:
            print(f"Telegram rate limit: esperar {e.retry_after}s")
            return False
        except (TimedOut, NetworkError) as e:
            print(f"Telegram timeout/red al enviar mensaje: {e}")
            return False
        except TelegramError as e:
            print(f"Error Telegram al enviar mensaje: {e}")
            return False

    async def _safe_reply(self, update: Update, text: str, parse_mode: str = "Markdown") -> bool:
        if not update.message:
            return False
        try:
            await update.message.reply_text(
                clean_rss_escapes((text or "")[:4096]),
                parse_mode=parse_mode,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
            )
            return True
        except BadRequest as e:
            print(f"Telegram no aceptó reply Markdown, reenviando plano: {e}")
            try:
                await update.message.reply_text(
                    to_plain_text(text)[:4096],
                    read_timeout=30,
                    write_timeout=30,
                    connect_timeout=30,
                )
                return True
            except TelegramError as e2:
                print(f"Error enviando reply plano: {e2}")
                return False
        except (TimedOut, NetworkError) as e:
            print(f"Telegram timeout/red al responder: {e}")
            return False
        except TelegramError as e:
            print(f"Error Telegram al responder: {e}")
            return False

    async def _safe_edit(self, query, text: str, parse_mode: str = "Markdown", **kwargs) -> bool:
        try:
            await query.edit_message_text(
                clean_rss_escapes((text or "")[:4096]),
                parse_mode=parse_mode,
                **kwargs,
            )
            return True
        except BadRequest as e:
            print(f"Telegram no aceptó edit Markdown, reenviando plano: {e}")
            try:
                await query.edit_message_text(to_plain_text(text)[:4096], **kwargs)
                return True
            except TelegramError as e2:
                print(f"Error editando mensaje plano: {e2}")
                return False
        except (TimedOut, NetworkError) as e:
            print(f"Telegram timeout/red al editar mensaje: {e}")
            return False
        except TelegramError as e:
            print(f"Error Telegram al editar mensaje: {e}")
            return False

    async def send_message(self, text: str, parse_mode: str = "Markdown"):
        """Envía un mensaje simple con fallback a texto plano."""
        await self._send_with_fallback(text, parse_mode=parse_mode)

    async def send_alert(self, text: str, priority: str = "media", actions: List[str] = None):
        """Envía alerta con botones de acción."""
        priority_emoji = {
            "critica": "🔴",
            "alta": "🟠",
            "media": "🟡",
            "baja": "🟢",
        }
        emoji = priority_emoji.get(priority, "⚪")
        full_text = f"{emoji} *SwissBrain Alert*\n\n{clean_rss_escapes(text)}"

        keyboard = []
        if actions:
            for i, action in enumerate(actions):
                keyboard.append([InlineKeyboardButton(action, callback_data=f"action_{i}")])
        keyboard.append([InlineKeyboardButton("✅ Entendido", callback_data="dismiss")])

        await self._send_with_fallback(
            full_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def start_command(self, update: Update, context):
        await self._safe_reply(
            update,
            "🧠 *SwissBrain activado*\n\n"
            "Soy tu agente autónomo. Puedo investigar, preparar reportes, monitorear precios, "
            "vigilar seguridad digital, generar briefs y buscar oportunidades.\n\n"
            "También podemos conversar normal: no convertiré cada mensaje en una tarea.",
        )

    async def help_command(self, update: Update, context):
        await self._safe_reply(
            update,
            "*Comandos disponibles:*\n\n"
            "/start - Iniciar SwissBrain\n"
            "/status - Ver estado de módulos\n"
            "/tasks - Ver últimas tareas y reportes\n"
            "/profile - Ver o guardar tu perfil laboral\n"
            "/help - Este mensaje\n\n"
            "También puedes escribirme en lenguaje natural: si detecto una tarea, la ejecuto; "
            "si es conversación, respondo sin activar módulos.",
        )

    async def status_command(self, update: Update, context):
        if not self.orchestrator:
            await self._safe_reply(update, "Orquestador no inicializado")
            return

        modules_status = "\n".join([
            f"{'✅' if getattr(module, 'enabled', False) else '❌'} {name}"
            for name, module in self.orchestrator.modules.items()
        ])

        await self._safe_reply(
            update,
            f"🧠 *Estado de SwissBrain*\n\n"
            f"Módulos:\n{modules_status}\n\n"
            f"Modo: {'Autónomo' if self.orchestrator.running else 'Manual'}\n"
            f"Memoria: SQLite activa",
        )

    async def tasks_command(self, update: Update, context):
        if not self.orchestrator:
            await self._safe_reply(update, "Orquestador no inicializado")
            return

        tasks = self.orchestrator.memory.get_recent_tasks(limit=8)
        if not tasks:
            await self._safe_reply(update, "Todavía no tengo tareas registradas.")
            return

        lines = ["*Últimas tareas*"]
        for task in tasks:
            status = task.get("status", "pending")
            icon = {"completed": "✅", "failed": "⚠️", "pending": "⏳"}.get(status, "•")
            topic = task.get("topic") or task.get("intent") or "Sin tema"
            summary = task.get("result_summary") or "Sin reporte todavía"
            lines.append(f"\n{icon} *#{task['id']} {topic}*")
            lines.append(f"Estado: `{status}`")
            lines.append(clean_rss_escapes(summary[:300]))

        await self._safe_reply(update, "\n".join(lines)[:4000])

    async def profile_command(self, update: Update, context):
        if not self.orchestrator:
            await self._safe_reply(update, "Orquestador no inicializado")
            return

        raw_text = " ".join(context.args).strip() if context.args else ""
        if raw_text:
            profile_update = self.orchestrator._extract_profile_update(raw_text)
            if not profile_update:
                profile_update = {
                    "specialty": raw_text,
                    "desired_roles": [raw_text],
                    "job_search_enabled": True,
                }
            self.orchestrator.memory.update_user_profile(profile_update)
            if "guardian" in self.orchestrator.modules:
                self.orchestrator.modules["guardian"].configure_user_profile(
                    self.orchestrator.memory.get_user_profile()
                )
            await self._safe_reply(
                update,
                self.orchestrator._format_profile_update_response(profile_update),
            )
            return

        profile = self.orchestrator.memory.get_user_profile()
        if not self.orchestrator.memory.has_job_profile():
            await self._safe_reply(
                update,
                "Aún no tengo tu perfil laboral.\n\n"
                "Puedes escribir:\n"
                "`/profile backend Python, FastAPI, automatización, Docker`\n\n"
                "O en lenguaje natural:\n"
                "`Mi especialidad es backend Python y mis habilidades son FastAPI, APIs, Docker`",
            )
            return

        skills = profile.get("skills", [])
        roles = profile.get("desired_roles", [])
        locations = profile.get("locations", [])
        await self._safe_reply(
            update,
            "*Perfil laboral*\n\n"
            f"Especialidad: *{profile.get('specialty', 'No definida')}*\n"
            f"Habilidades: *{', '.join(skills) if isinstance(skills, list) else skills or 'No definidas'}*\n"
            f"Roles objetivo: *{', '.join(roles) if isinstance(roles, list) else roles or 'No definidos'}*\n"
            f"Ubicaciones: *{', '.join(locations) if isinstance(locations, list) else locations or 'Remote'}*",
        )

    async def handle_message(self, update: Update, context):
        if not self.orchestrator:
            await self._safe_reply(update, "Orquestador no listo")
            return

        message = update.message.text.strip()

        # --- NUEVO: Manejo de respuestas cortas ("sí", "ok", "claro") ---
        if message.lower() in ["sí", "si", "ok", "claro", "ale", "ajá", "sip"]:
            # Obtener el último tema o tarea del usuario
            last_interaction = self.orchestrator.memory.get_recent_interactions(limit=1)
            if last_interaction:
                last_message = last_interaction[0].get("user_message", "").lower()
                last_intent = last_interaction[0].get("intent", "")

                # Si el último mensaje fue una solicitud de información
                if any(
                    keyword in last_message
                    for keyword in [
                        "noticias", "informe", "investiga", "busca",
                        "desarrollo", "tecnología", "economía", "perú", "mundo"
                    ]
                ):
                    # Reejecutar la última solicitud
                    await self._safe_reply(update, "🔍 Buscando más información sobre el tema anterior...")
                    result = await self.orchestrator.process_user_message(last_message)
                    response = self._format_response(result)
                    await self._safe_reply(update, response)
                    return
                else:
                    # Si no hay contexto claro, pedir aclaración
                    await self._safe_reply(
                        update,
                        "¿A qué te refieres con 'sí'? ¿Quieres que continúe con el tema anterior o algo nuevo?"
                    )
                    return

        # --- Lógica existente para clasificar solicitudes ---
        tipo = self._clasificar_solicitud(message)

        if tipo == "tarea":
            await self._safe_reply(update, "🔍 Procesando tu solicitud...")
        elif tipo == "consulta":
            await self._safe_reply(update, "🤔 Un momento...")

        try:
            result = await self.orchestrator.process_user_message(message)
            response = self._format_response(result)
        except Exception as e:
            print(f"Error procesando mensaje del usuario: {e}")
            response = "Tuve un problema procesando eso. Intenta de nuevo en un momento."

        await self._safe_reply(update, response)

    async def handle_callback(self, update: Update, context):
        query = update.callback_query
        try:
            await query.answer()
        except (TimedOut, NetworkError, TelegramError) as e:
            print(f"Error respondiendo callback: {e}")

        if query.data == "dismiss":
            await self._safe_edit(query, query.message.text + "\n\n✅ *Marcado como leído*")
            return

        if not query.data.startswith("action_"):
            return

        action_idx = int(query.data.split("_")[1])
        message_text = query.message.text

        if "CVE" in message_text:
            await self._handle_cve_action(query, action_idx, message_text)
        elif "Phishing" in message_text:
            await self._handle_phishing_action(query, action_idx)
        elif "Email comprometido" in message_text:
            await self._handle_breach_action(query, action_idx)
        else:
            await self._safe_edit(
                query,
                query.message.text + f"\n\n🔄 *Acción {action_idx + 1} en desarrollo*",
            )

    async def _handle_cve_action(self, query, action_idx, message_text):
        if action_idx == 0:
            cve_match = re.search(r"CVE-\d{4}-\d+", message_text)
            cve_id = cve_match.group(0) if cve_match else "CVE-UNKNOWN"
            await self._safe_edit(
                query,
                message_text + f"\n\n🔍 *Información adicional:*\n"
                f"🔗 [NVD Detail](https://nvd.nist.gov/vuln/detail/{cve_id})\n"
                f"🔗 [MITRE](https://cve.mitre.org/cgi-bin/cvename.cgi?name={cve_id})\n"
                f"🔗 [VulDB](https://vuldb.com/?id={cve_id})",
                disable_web_page_preview=True,
            )
        elif action_idx == 1:
            await self._safe_edit(
                query,
                message_text + "\n\n📋 *Checklist de verificación:*\n"
                "☐ ¿Usas el software afectado?\n"
                "☐ ¿Está en tu infraestructura?\n"
                "☐ ¿Hay patch disponible?\n"
                "☐ ¿Puedes mitigar temporalmente?",
            )

    async def _handle_phishing_action(self, query, action_idx):
        if action_idx == 0:
            await self._safe_edit(
                query,
                query.message.text + "\n\n🛡️ *Pasos a seguir:*\n"
                "1. [Reportar a Google](https://safebrowsing.google.com/safebrowsing/report_phish/)\n"
                "2. [Reportar a Microsoft](https://www.microsoft.com/en-us/wdsi/support/report-unsafe-site)\n"
                "3. Borrar el mensaje/email\n"
                "4. Si ingresaste datos: cambia contraseña inmediatamente",
            )
        elif action_idx == 1:
            await self._safe_edit(
                query,
                query.message.text + "\n\n🔍 *Verificar sitio legítimo:*\n"
                "• Revisa la URL carácter por carácter\n"
                "• Busca el sitio real en Google, no uses el enlace\n"
                "• Verifica el certificado SSL\n"
                "• Contacta directamente a la empresa",
            )

    async def _handle_breach_action(self, query, action_idx):
        if action_idx == 0:
            await self._safe_edit(
                query,
                query.message.text + "\n\n🔐 *Cambio de contraseña:*\n"
                "Usa una contraseña única y fuerte:\n"
                "`openssl rand -base64 16`\n\n"
                "O genera una en: [1Password](https://1password.com/password-generator/)",
            )
        elif action_idx == 1:
            await self._safe_edit(
                query,
                query.message.text + "\n\n📱 *Activar 2FA:*\n"
                "• Authy: [Descargar](https://authy.com/)\n"
                "• Google Authenticator\n"
                "• Microsoft Authenticator\n\n"
                "Evita SMS como 2FA si puedes usar una app autenticadora.",
            )

    def _format_response(self, result: Dict) -> str:
        if "synthesized" in result:
            task = result.get("task", {})
            header = self._task_header(task) if task else "*Reporte de tarea*\n\n"
            return clean_rss_escapes((header + result["synthesized"])[:4000])

        if "conversacion" in result:
            msg = result["conversacion"].get("message", "Listo")
            return clean_rss_escapes(msg)

        parts = []
        task = result.get("task")
        if task:
            parts.append(self._task_header(task))

        for module, data in result.items():
            if module == "task":
                continue
            if isinstance(data, dict) and "findings" in data:
                for finding in data["findings"]:
                    title = finding.get("title", "Hallazgo")
                    content = finding.get("content", "")[:700]
                    parts.append(f"*{clean_rss_escapes(title)}*\n{clean_rss_escapes(content)}")
            elif isinstance(data, dict) and data.get("error"):
                parts.append(f"*{module}*\n{clean_rss_escapes(data['error'])}")

        return "\n\n".join(parts)[:4000] or "✅ Tarea completada"

    def _task_header(self, task: Dict) -> str:
        status = task.get("status", "completed")
        icon = "✅" if status == "completed" else "⚠️"
        modules = ", ".join(task.get("modules", [])) or "sin módulos"
        task_id = task.get("id", "?")
        return f"{icon} *Reporte de tarea #{task_id}*\nMódulos: `{modules}`\n\n"

    async def run_polling_async(self):
        application = (
            Application.builder()
            .token(SETTINGS.TELEGRAM_BOT_TOKEN)
            .connect_timeout(30)
            .read_timeout(30)
            .write_timeout(30)
            .pool_timeout(30)
            .build()
        )

        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("status", self.status_command))
        application.add_handler(CommandHandler("tasks", self.tasks_command))
        application.add_handler(CommandHandler("profile", self.profile_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        application.add_error_handler(self.error_handler)

        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        print("🤖 Bot de Telegram iniciado y escuchando")

        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
            print("🤖 Bot de Telegram detenido")

    async def error_handler(self, update: object, context):
        error = context.error
        if isinstance(error, (TimedOut, NetworkError)):
            print(f"Telegram error de red controlado: {error}")
            return
        print(f"Telegram error no esperado: {error}")