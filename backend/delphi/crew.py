"""Moderador Delphi + panel como un Crew jerárquico de CrewAI (README §5, Pamela).

Idea central: el Moderador es el `manager_agent` y los expertos son los workers.
En proceso jerárquico el manager recibe cada tarea y la DELEGA al experto que
corresponde. engine.py arma un Crew nuevo por experto y ronda, para que ninguna
memoria o contexto se filtre de un experto a otro ni de una ronda a la siguiente.

Garantías de independencia que se configuran aquí (CrewAI no las da solas):
  - Enunciado sellado (ExpertoDelphi): el experto responde el prompt armado por el
    código, no el texto que redacta el Moderador al delegar.
  - Salida directa: la respuesta se toma del experto, no de la respuesta final del
    Moderador, que podría resumirla o cambiar puntajes.
  - Task(context=[]): sin esto CrewAI pasa la salida de las tareas anteriores.
  - Workers sin delegación, sin memoria y sin cache: no se consultan entre sí.
  - El prompt de cada experto lo valida guard_independencia (engine.py).

Los LLM llegan por `llm_para(agente_id)` (ModelPool.get_llm), así este módulo no
depende de config.py ni de ninguna API key.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from crewai import Agent, Crew, Process, Task
from pydantic import PrivateAttr

from backend.delphi.moderador_prompts import BACKSTORY, GOAL, ROLE

MAX_ITER_MODERADOR = 6
MAX_ITER_EXPERTO = 3

SALIDA_ESPERADA_EXPERTO = (
    'Un único objeto JSON: {"respuestas": [{"item_id": "...", "puntaje": 1-5, '
    '"justificacion": "..."}], "riesgos_detectados": ["..."]}, sin texto adicional.'
)
ENCARGO = "Responder el cuestionario Delphi asignado"


class ExpertoDelphi(Agent):
    """Worker con el enunciado sellado: el Moderador decide CUÁNDO delegar, no QUÉ recibe el experto.

    CrewAI delega llamando a `execute_task` del worker con el texto y el contexto que
    redactó el manager. Aquí se descartan ambos y se usa el prompt armado por el código.
    Además el Moderador ya no copia el prompt completo al delegar, lo que reduce sus tokens.

    Los errores se guardan antes de relanzarlos: la herramienta de delegación de CrewAI
    los convierte en texto para el manager, y el motor necesita ver un 429 para reintentar
    o cambiar de modelo.
    """

    _enunciado: str = PrivateAttr(default="")
    _salida: str | None = PrivateAttr(default=None)
    _error: Exception | None = PrivateAttr(default=None)

    def sellar(self, enunciado: str) -> None:
        self._enunciado, self._salida, self._error = enunciado, None, None

    @property
    def salida(self) -> str | None:
        """Lo que respondió el experto (la última vez, si el Moderador pidió rehacer)."""
        return self._salida

    @property
    def error(self) -> Exception | None:
        return self._error

    def execute_task(self, task: Task, context: str | None = None, tools: list | None = None) -> Any:
        sellada = Task(description=self._enunciado, expected_output=SALIDA_ESPERADA_EXPERTO, agent=self)
        try:
            resultado = super().execute_task(sellada, None, tools)
        except Exception as error:
            self._error = error
            raise
        self._salida, self._error = str(resultado), None
        return resultado


def crear_moderador(llm: Any) -> Agent:
    """El manager_agent. CrewAI le fuerza allow_delegation=True al armar el Crew.

    Sin herramientas: CrewAI rechaza un manager con tools ("Manager agent should not
    have tools"). Por eso DelphiStatsTool y el anonimizador los invoca engine.py
    directamente, lo cual además hace los números deterministas.
    """
    return Agent(
        role=ROLE, goal=GOAL, backstory=BACKSTORY, llm=llm,
        allow_delegation=True, max_iter=MAX_ITER_MODERADOR, memory=False, verbose=False,
    )


def crear_worker(experto: dict[str, Any], llm: Any) -> ExpertoDelphi:
    """Un experto del panel. Aislado: no delega, no recuerda, no usa herramientas."""
    return ExpertoDelphi(
        role=experto["role"], goal=experto["goal"], backstory=experto["backstory"], llm=llm,
        allow_delegation=False, max_iter=MAX_ITER_EXPERTO, memory=False, cache=False, verbose=False,
    )


def crear_tarea_experto(worker: ExpertoDelphi, prompt: str, rol_experto: str) -> Task:
    """Sella el prompt en el experto y devuelve la tarea que el Moderador debe delegar."""
    worker.sellar(prompt)
    return Task(
        description=(f"Delega en el experto «{rol_experto}» su cuestionario Delphi de esta ronda. "
                     f"El experto ya tiene el enunciado completo: como tarea escribe solo «{ENCARGO}» "
                     "y no agregues contexto. Tu respuesta final es el JSON que devuelva el experto, "
                     "sin cambios."),
        expected_output=SALIDA_ESPERADA_EXPERTO,
        agent=worker,
        context=[],          # explícito: ninguna salida de otros expertos
    )


def crear_crew_ronda(
    moderador: Agent,
    workers: list[Agent],
    tareas: list[Task],
    step_callback: Callable[..., Any] | None = None,
    task_callback: Callable[..., Any] | None = None,
) -> Crew:
    """Crew jerárquico (en la práctica, de un experto). El moderador va aparte de `agents`."""
    return Crew(
        agents=workers,
        tasks=tareas,
        process=Process.hierarchical,
        manager_agent=moderador,
        memory=False, cache=False, planning=False, verbose=False,
        step_callback=step_callback, task_callback=task_callback,
    )
