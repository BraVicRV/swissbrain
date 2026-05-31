import requests
from typing import Dict, Any, List
from modules.base import BaseModule
from config.settings import SETTINGS

class MarketWatchModule(BaseModule):
    def __init__(self):
        super().__init__(
            name="market_watch",
            description="Monitoreo de precios de criptos y alertas"
        )
        self.price_cache = {}
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        cripto = params.get("cripto", "bitcoin")
        umbral = params.get("umbral")
        condicion = params.get("condicion", "mayor")
        
        # Obtener precio actual
        precio_actual = await self._get_crypto_price(cripto)
        
        if umbral:
            # Configurar alerta
            return {
                "findings": [{
                    "title": f"Alerta configurada: {cripto}",
                    "content": f"Se alertará cuando {cripto} {'suba' if condicion == 'mayor' else 'baje'} de ${umbral}",
                    "priority": "baja"
                }],
                "alert_configured": True,
                "current_price": precio_actual,
                "status": "completed"  # >>> FIX: Agregado status
            }
        
        return {
            "findings": [{
                "title": f"Precio actual de {cripto}",
                "content": f"${precio_actual:,.2f}",
                "priority": "baja"
            }],
            "current_price": precio_actual,
            "status": "completed"  # >>> FIX: Agregado status
        }
    
    async def autonomous_check(self) -> List[Dict[str, Any]]:
        """Verifica precios y genera alertas si hay cambios significativos."""
        findings = []
        cryptos = ["bitcoin", "ethereum", "solana"]
        
        for crypto in cryptos:
            current = await self._get_crypto_price(crypto)
            previous = self.price_cache.get(crypto)
            
            if previous and previous > 0:
                change_pct = ((current - previous) / previous) * 100
                
                if abs(change_pct) > 5:  # Cambio significativo
                    priority = "alta" if abs(change_pct) > 10 else "media"
                    findings.append(self.format_finding(
                        title=f"🚨 Movimiento fuerte: {crypto.upper()}",
                        content=f"Precio: ${current:,.2f} ({change_pct:+.2f}% en 5 min)",
                        priority=priority,
                        metadata={"price_change_pct": change_pct, "crypto": crypto}
                    ))
            
            self.price_cache[crypto] = current
        
        return findings
    
    async def _get_crypto_price(self, crypto_id: str) -> float:
        """Obtiene precio de CoinGecko."""
        try:
            response = requests.get(
                f"https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": crypto_id,
                    "vs_currencies": "usd"
                },
                timeout=10
            )
            data = response.json()
            return data.get(crypto_id, {}).get("usd", 0.0)
        except Exception as e:
            print(f"Error obteniendo precio de {crypto_id}: {e}")
            return 0.0