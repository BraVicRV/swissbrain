from apscheduler.schedulers.asyncio import AsyncIOScheduler
from typing import Callable, Dict, Any

class AutonomousScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()

    def schedule_task(
        self,
        task_func: Callable,
        trigger: str = "interval",
        **kwargs
    ) -> str:
        """Programa una tarea autónoma.
        Args:
            task_func: Función asíncrona a ejecutar.
            trigger: Tipo de disparador ("interval", "cron", "date").
            **kwargs: Argumentos para el disparador (ej: hours=6, hour=8, etc.).
        Returns:
            ID de la tarea programada.
        """
        job = self.scheduler.add_job(
            task_func,
            trigger=trigger,
            **kwargs
        )
        return job.id

    def remove_task(self, job_id: str):
        """Elimina una tarea programada."""
        self.scheduler.remove_job(job_id)

    def shutdown(self):
        """Detiene el scheduler."""
        self.scheduler.shutdown()