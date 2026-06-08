
from datetime import datetime
from typing import Dict, Any, List
from modules.base import BaseModule

class GoalManager(BaseModule):
    def __init__(self):
        super().__init__(
            name="goal_manager",
            description="Gestiona objetivos a largo plazo para el agente"
        )
        self.active_goals = {}  # {goal_id: {"description": str, "tasks": list, "status": str, "user_id": str}}

    def add_goal(self, user_id: str, description: str, tasks: List[Dict]) -> str:
        """Añade un nuevo objetivo."""
        goal_id = f"goal_{user_id}_{len(self.active_goals) + 1}"
        self.active_goals[goal_id] = {
            "description": description,
            "tasks": tasks,
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "user_id": user_id
        }
        return goal_id

    def get_goals(self, user_id: str) -> List[Dict]:
        """Obtiene todos los objetivos activos de un usuario."""
        return [
            goal for goal in self.active_goals.values()
            if goal["user_id"] == user_id and goal["status"] == "active"
        ]

    def complete_goal(self, goal_id: str):
        """Marca un objetivo como completado."""
        if goal_id in self.active_goals:
            self.active_goals[goal_id]["status"] = "completed"

    def delete_goal(self, goal_id: str):
        """Elimina un objetivo."""
        if goal_id in self.active_goals:
            del self.active_goals[goal_id]

    async def check_goals(self, orchestrator) -> List[Dict]:
        """Revisa objetivos activos y ejecuta tareas asociadas."""
        findings = []
        for goal_id, goal in self.active_goals.items():
            if goal["status"] != "active":
                continue

            for task in goal["tasks"]:
                # Ejecutar la tarea (ej: buscar noticias sobre elecciones)
                result = await orchestrator.process_user_message(task["query"])
                if result.get("findings"):
                    findings.extend(result["findings"])

        return findings