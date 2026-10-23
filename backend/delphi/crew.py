"""Moderador Delphi + panel como un Crew jerárquico de CrewAI (README §5, Pamela).

Idea central: el Moderador es el `manager_agent` y los expertos son los workers.
En proceso jerárquico el manager recibe cada tarea y la DELEGA al experto que
corresponde. Se arma un Crew nuevo por ronda (engine.py) para que ninguna
memoria o contexto de una ronda se filtre a la siguiente.

Garantías de independencia que se configuran aquí (CrewAI no las da solas):
  - Task(context=[]): sin esto CrewAI podría pasar la salida de otras tareas.
  - Workers sin delegación, sin memoria y sin cache: no se consultan entre sí.
  - El prompt de cada experto lo valida guard_independencia (engine.py).

Los LLM llegan por `llm_para(agente_id)` (será ModelPool.get_llm de Juan), así
este módulo no depende de config.py ni de ninguna API key.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from crewai import Agent, Crew, Process, Task

from backend.delphi.moderador_prompts import BACKSTORY, GOAL, ROLE

MAX_ITER_MODERADOR = 6
MAX_ITER_EXPERTO = 3

SALIDA_ESPERADA_EXPERTO = (
    'Un único objeto JSON: {"respuestas": [{"item_id": "...", "puntaje": 1-5, '
    '"justificacion": "..."}], "riesgos_detectados": ["..."]}, sin texto adicional.'
)


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


def crear_worker(experto: dict[str, Any], llm: Any) -> Agent:
    """Un experto del panel. Aislado: no delega, no recuerda, no usa herramientas."""
    return Agent(
        role=experto["role"], goal=experto["goal"], backstory=experto["backstory"], llm=llm,
        allow_delegation=False, max_iter=MAX_ITER_EXPERTO, memory=False, cache=False, verbose=False,
    )


def crear_tarea_experto(worker: Agent, prompt: str, rol_experto: str) -> Task:
    """Tarea de un experto. El prompt es lo único que recibe (ver prompts.py)."""
    return Task(
        description=f"Delega esta tarea al experto «{rol_experto}», sin modificarla:\n\n{prompt}",
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
    """Crew jerárquico de UNA ronda. El moderador va aparte de `agents`."""
    return Crew(
        agents=workers,
        tasks=tareas,
        process=Process.hierarchical,
        manager_agent=moderador,
        memory=False, cache=False, planning=False, verbose=False,
        step_callback=step_callback, task_callback=task_callback,
    )
