import asyncio
import os
from dotenv import load_dotenv

# Configurar logging ANTES de todo
from config.logging_config import setup_logging
setup_logging()

# Cargar .env
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(env_path)

print(f"Directorio: {script_dir}")
print(f"GROQ_API_KEY: {bool(os.getenv('GROQ_API_KEY'))}")
print(f"TELEGRAM_BOT_TOKEN: {bool(os.getenv('TELEGRAM_BOT_TOKEN'))}")
print(f"TELEGRAM_CHAT_ID: {bool(os.getenv('TELEGRAM_CHAT_ID'))}")

from core.orchestrator import SwissBrainOrchestrator
from modules.research import ResearchModule
from modules.market_watch import MarketWatchModule
from modules.brief import BriefModule
from modules.sentinel import SentinelModule
from modules.guardian import GuardianModule
from bot_telegram.bot import TelegramBot

async def main():
    required = ["GROQ_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing = [r for r in required if not os.getenv(r)]
    if missing:
        print(f"❌ Faltan variables: {', '.join(missing)}")
        return
    
    orchestrator = SwissBrainOrchestrator()
    
    orchestrator.register_module("research", ResearchModule())
    orchestrator.register_module("market_watch", MarketWatchModule())
    orchestrator.register_module("brief", BriefModule())
    orchestrator.register_module("sentinel", SentinelModule())
    orchestrator.register_module("guardian", GuardianModule())
    
    telegram = TelegramBot()
    telegram.set_orchestrator(orchestrator)
    orchestrator.telegram = telegram
    
    print("SwissBrain v1.0 iniciado")
    print("Prueba enviando: 'Investiga el impacto de la IA en la educación'")
    
    try:
        await asyncio.gather(
            orchestrator.run_autonomous_loop(),
            telegram.run_polling_async()
        )
    except KeyboardInterrupt:
        print("\n👋 Deteniendo...")
    finally:
        orchestrator.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 SwissBrain detenido")