# 🧠 SwissBrain

Agente autónomo de inteligencia y seguridad digital con interfaz de Telegram.

## 🚀 Características

- 🔬 Investigación profunda con verificación de fuentes
- 📈 Monitoreo de precios de criptomonedas
- 📰 Briefs diarios de noticias personalizados
- 🛡️ Vigilancia de seguridad digital (breaches, CVEs, phishing)
- 💼 Oportunidades laborales con scoring de match
- 💬 Interfaz conversacional con botones interactivos

## 📋 Requisitos

- Python 3.11+
- Cuenta en [Groq](https://console.groq.com)
- Bot de [Telegram](https://t.me/BotFather)
- (Opcional) API keys: NewsAPI, Serper.dev, Jina AI

## ⚙️ Instalación

```bash
git clone https://github.com/TU_USUARIO/swissbrain.git
cd swissbrain
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
cp .env.example .env
# Editar .env con tus credenciales
python main.py