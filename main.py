import asyncio
import os

from dotenv import load_dotenv

from config.logging_config import setup_logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

setup_logging()

script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, ".env")
load_dotenv(env_path)

print(f"Directorio: {script_dir}")
print(f"GROQ_API_KEY: {bool(os.getenv('GROQ_API_KEY'))}")
print(f"TELEGRAM_BOT_TOKEN: {bool(os.getenv('TELEGRAM_BOT_TOKEN'))}")
print(f"TELEGRAM_CHAT_ID: {bool(os.getenv('TELEGRAM_CHAT_ID'))}")

from bot_telegram.bot import TelegramBot
from core.orchestrator import SwissBrainOrchestrator
from modules.brief import BriefModule
from modules.guardian import GuardianModule
from modules.market_watch import MarketWatchModule
from modules.research import ResearchModule
from modules.sentinel import SentinelModule

async def main():
    required = ["GROQ_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        print(f"ERROR: Faltan variables: {', '.join(missing)}")
        return

    orchestrator = SwissBrainOrchestrator()

    # --- REGISTRAR MÓDULOS EXISTENTES ---
    orchestrator.register_module("research", ResearchModule())
    orchestrator.register_module("market_watch", MarketWatchModule())
    orchestrator.register_module("brief", BriefModule())
    orchestrator.register_module("sentinel", SentinelModule())
    orchestrator.register_module("guardian", GuardianModule())

    # --- INICIALIZAR SCHEDULER PARA TAREAS AUTÓNOMAS ---
    scheduler = AsyncIOScheduler()
    scheduler.start()

    # Programar brief diario a las 8 AM (hora de Lima)
    scheduler.add_job(
        lambda: orchestrator._send_daily_brief(),
        trigger="cron",
        hour=8,
        timezone="America/Lima",
        id="daily_brief"
    )

    # Programar check de vulnerabilidades cada 6 horas
    scheduler.add_job(
        lambda: orchestrator._check_critical_vulns(),
        trigger="interval",
        hours=6,
        id="vuln_check"
    )

    telegram = TelegramBot()
    telegram.set_orchestrator(orchestrator)
    orchestrator.telegram = telegram

    print("SwissBrain v2.0 iniciado (Agente Autónomo)")
    print("Ejemplo: 'Investiga el impacto de la IA en la educación'")

    try:
        await asyncio.gather(
            orchestrator.run_autonomous_loop(),
            telegram.run_polling_async(),
        )
    except KeyboardInterrupt:
        print("\nDeteniendo...")
        scheduler.shutdown()
    finally:
        orchestrator.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSwissBrain detenido")