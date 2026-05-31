from abc import ABC, abstractmethod
from typing import Dict, Any, List

class BaseModule(ABC):
    """Clase base para todos los módulos de SwissBrain."""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.enabled = True
    
    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta el módulo con los parámetros dados."""
        pass
    
    async def autonomous_check(self) -> List[Dict[str, Any]]:
        """Verificación autónoma periódica. Override opcional."""
        return []
    
    def format_finding(self, title: str, content: str, 
                      priority: str = "media", metadata: Dict = None) -> Dict:
        """Formatea un hallazgo estándar."""
        return {
            "title": title,
            "content": content,
            "priority": priority,
            "metadata": metadata or {},
            "module": self.name
        }