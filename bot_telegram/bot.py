import asyncio
import re
from typing import List, Optional, Dict
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config.settings import SETTINGS


def clean_rss_escapes(text: str) -> str:
    """
    Limpia escapes de backslash que vienen de fuentes RSS/HTML.
    Convierte backslash-guion en guion, backslash-punto en punto, etc.
    para que los enlaces funcionen en Telegram.
    """
    if not text:
        return ""
    
    # Paso 1: Reemplazos literales simples (sin regex)
    literal_replacements = {
        r'\-': '-',
        r'\.': '.',
        r'\_': '_',
        r'\[': '[',
        r'\]': ']',
        r'\(': '(',
        r'\)': ')',
        r'\*': '*',
        r'\`': '`',
        r'\>': '>',
        r'\#': '#',
        r'\+': '+',
        r'\=': '=',
        r'\|': '|',
        r'\{': '{',
        r'\}': '}',
        r'\!': '!',
        '&nbsp;': ' ',
    }
    
    for old, new in literal_replacements.items():
        text = text.replace(old, new)
    
    # Paso 2: Reemplazos con regex
    # HTML <a href="url">texto</a> → [texto](url)
    text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r'[\2](\1)', text)
    # Eliminar imágenes HTML
    text = re.sub(r'<img[^>]+>', '', text)
    # Eliminar cualquier tag HTML restante
    text = re.sub(r'<[^>]+>', '', text)
    
    return text


class TelegramBot:
    def __init__(self):
        self.bot = Bot(token=SETTINGS.TELEGRAM_BOT_TOKEN)
        self.chat_id = SETTINGS.TELEGRAM_CHAT_ID
        self.orchestrator = None  # Se inyecta después
    
    def set_orchestrator(self, orchestrator):
        self.orchestrator = orchestrator
    
    async def send_message(self, text: str, parse_mode: str = "Markdown"):
        """Envía mensaje simple con formato limpio."""
        try:
            clean_text = clean_rss_escapes(text[:4096])
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=clean_text,
                parse_mode=parse_mode,
                disable_web_page_preview=False
            )
        except Exception as e:
            print(f"Error enviando mensaje con Markdown: {e}")
            try:
                plain_text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1: \2', text[:4096])
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=plain_text
                )
            except Exception as e2:
                print(f"Error enviando mensaje plano: {e2}")
    
    async def send_alert(self, text: str, priority: str = "media", 
                        actions: List[str] = None):
        """Envía alerta con botones de acción."""
        priority_emoji = {
            "critica": "🔴",
            "alta": "🟠",
            "media": "🟡",
            "baja": "🟢"
        }
        
        emoji = priority_emoji.get(priority, "⚪")
        clean_text = clean_rss_escapes(text)
        full_text = f"{emoji} *SwissBrain Alert*\n\n{clean_text}"
        
        keyboard = []
        if actions:
            for i, action in enumerate(actions):
                keyboard.append([InlineKeyboardButton(
                    action, callback_data=f"action_{i}"
                )])
        
        keyboard.append([InlineKeyboardButton(
            "✅ Entendido", callback_data="dismiss"
        )])
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=full_text[:4096],
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                disable_web_page_preview=False
            )
        except Exception as e:
            print(f"Error enviando alerta con Markdown: {e}")
            try:
                plain_text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1: \2', text[:4000])
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"{emoji} SwissBrain Alert\n\n{plain_text}",
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
            except Exception as e2:
                print(f"Error enviando alerta plana: {e2}")
    
    async def start_command(self, update: Update, context):
        """Handler para /start."""
        await update.message.reply_text(
            "🧠 *SwissBrain activado*\n\n"
            "Soy tu agente autónomo. Puedo:\n"
            "• 🔬 Investigar temas a fondo\n"
            "• 📈 Monitorear precios y alertarte\n"
            "• 📰 Enviarte briefs diarios\n"
            "• 🛡️ Vigilar tu seguridad digital\n\n"
            "Simplemente dime qué necesitas o espera mis alertas proactivas.",
            parse_mode="Markdown"
        )
    
    async def help_command(self, update: Update, context):
        """Handler para /help."""
        await update.message.reply_text(
            "*Comandos disponibles:*\n\n"
            "/start - Iniciar SwissBrain\n"
            "/status - Ver estado de módulos\n"
            "/brief - Generar brief manual\n"
            "/alerts - Ver alertas activas\n"
            "/interests - Ver temas de interés\n"
            "/mute - Silenciar notificaciones no críticas\n"
            "/help - Este mensaje\n\n"
            "O simplemente escríbeme lo que necesites."
        )
    
    async def status_command(self, update: Update, context):
        """Ver estado del sistema."""
        if not self.orchestrator:
            await update.message.reply_text("Orquestador no inicializado")
            return
        
        modules_status = "\n".join([
            f"{'✅' if hasattr(m, 'enabled') and m.enabled else '❌'} {name}"
            for name, m in self.orchestrator.modules.items()
        ])
        
        await update.message.reply_text(
            f"🧠 *Estado de SwissBrain*\n\n"
            f"Módulos:\n{modules_status}\n\n"
            f"Modo: {'Autónomo' if self.orchestrator.running else 'Manual'}\n"
            f"Memoria: SQLite activa"
        )
    
    async def handle_message(self, update: Update, context):
        """Procesa mensajes del usuario."""
        if not self.orchestrator:
            await update.message.reply_text("Orquestador no listo")
            return
        
        message = update.message.text
        await update.message.reply_text("🔄 Procesando...")
        
        # Procesar con el orquestador
        result = await self.orchestrator.process_user_message(message)
        
        # Construir respuesta
        response = self._format_response(result)
        
        try:
            await update.message.reply_text(response, parse_mode="Markdown")
        except Exception as e:
            print(f"Error enviando respuesta con Markdown: {e}")
            # Fallback a texto plano
            await update.message.reply_text(response)
    
    async def handle_callback(self, update: Update, context):
        query = update.callback_query
        await query.answer()
        
        if query.data == "dismiss":
            await query.edit_message_text(
                query.message.text + "\n\n✅ *Marcado como leído*",
                parse_mode="Markdown"
            )
        elif query.data.startswith("action_"):
            action_idx = int(query.data.split("_")[1])
            message_text = query.message.text
            
            if "CVE" in message_text:
                await self._handle_cve_action(query, action_idx, message_text)
            elif "Phishing" in message_text:
                await self._handle_phishing_action(query, action_idx)
            elif "Email comprometido" in message_text:
                await self._handle_breach_action(query, action_idx)
            else:
                await query.edit_message_text(
                    query.message.text + f"\n\n🔄 *Acción {action_idx + 1} en desarrollo*",
                    parse_mode="Markdown"
                )

    async def _handle_cve_action(self, query, action_idx, message_text):
        """Acciones para alertas de CVE."""
        if action_idx == 0:
            import re
            cve_match = re.search(r'CVE-\d{4}-\d+', message_text)
            cve_id = cve_match.group(0) if cve_match else "CVE-UNKNOWN"
            
            await query.edit_message_text(
                message_text + f"\n\n🔍 *Información adicional:*\n"
                            f"🔗 [NVD Detail](https://nvd.nist.gov/vuln/detail/{cve_id})\n"
                            f"🔗 [MITRE](https://cve.mitre.org/cgi-bin/cvename.cgi?name={cve_id})\n"
                            f"🔗 [VulDB](https://vuldb.com/?id={cve_id})",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        elif action_idx == 1:
            await query.edit_message_text(
                message_text + "\n\n📋 *Checklist de verificación:*\n"
                            "☐ ¿Usas el software afectado?\n"
                            "☐ ¿Está en tu infraestructura?\n"
                            "☐ ¿Hay patch disponible?\n"
                            "☐ ¿Puedes mitigar temporalmente?",
                parse_mode="Markdown"
            )

    async def _handle_phishing_action(self, query, action_idx):
        """Acciones para alertas de phishing."""
        if action_idx == 0:
            await query.edit_message_text(
                query.message.text + "\n\n🛡️ *Pasos a seguir:*\n"
                                    "1. [Reportar a Google](https://safebrowsing.google.com/safebrowsing/report_phish/)\n"
                                    "2. [Reportar a Microsoft](https://www.microsoft.com/en-us/wdsi/support/report-unsafe-site)\n"
                                    "3. Borrar el mensaje/email\n"
                                    "4. Si ingresaste datos: cambia contraseña inmediatamente",
                parse_mode="Markdown"
            )
        elif action_idx == 1:
            await query.edit_message_text(
                query.message.text + "\n\n🔍 *Verificar sitio legítimo:*\n"
                                    "• Revisa la URL carácter por carácter\n"
                                    "• Busca el sitio real en Google, no uses el enlace\n"
                                    "• Verifica el certificado SSL\n"
                                    "• Contacta directamente a la empresa",
                parse_mode="Markdown"
            )

    async def _handle_breach_action(self, query, action_idx):
        """Acciones para alertas de breach."""
        if action_idx == 0:
            await query.edit_message_text(
                query.message.text + "\n\n🔐 *Cambio de contraseña:*\n"
                                    "Usa una contraseña única y fuerte:\n"
                                    "`openssl rand -base64 16`\n\n"
                                    "O genera una en: [1Password](https://1password.com/password-generator/)",
                parse_mode="Markdown"
            )
        elif action_idx == 1:
            await query.edit_message_text(
                query.message.text + "\n\n📱 *Activar 2FA:*\n"
                                    "• Authy: [Descargar](https://authy.com/)\n"
                                    "• Google Authenticator\n"
                                    "• Microsoft Authenticator\n\n"
                                    "Nunca uses SMS como 2FA si es posible.",
                parse_mode="Markdown"
            )
    
    def _format_response(self, result: Dict) -> str:
        """Formatea resultado para Telegram."""
        if "synthesized" in result:
            text = result["synthesized"][:4000]
            return clean_rss_escapes(text)
        
        if "conversacion" in result:
            msg = result["conversacion"].get("message", "Listo")
            return clean_rss_escapes(msg)
        
        parts = []
        for module, data in result.items():
            if isinstance(data, dict) and "findings" in data:
                for finding in data["findings"]:
                    title = finding.get('title', 'Hallazgo')
                    content = finding.get('content', '')[:500]
                    parts.append(f"*{clean_rss_escapes(title)}*\n{clean_rss_escapes(content)}")
        
        return "\n\n".join(parts)[:4000] or "✅ Tarea completada"
        
    async def run_polling_async(self):
        """Inicia el bot de forma asíncrona compatible con el loop existente."""
        application = Application.builder().token(SETTINGS.TELEGRAM_BOT_TOKEN).build()
        
        # Handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("status", self.status_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        print("🤖 Bot de Telegram iniciado y escuchando")
        
        # Mantener el bot vivo indefinidamente
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
            print("🤖 Bot de Telegram detenido")