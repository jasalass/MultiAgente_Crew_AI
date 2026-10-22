from crewai import LLM, Process

from backend.delphi.crew import crear_crew_ronda, crear_moderador, crear_tarea_experto, crear_worker
from backend.delphi.experts import get_experto


def _llm():
    return LLM(model="openai/gpt-4o-mini", api_key="no-se-usa")   # nunca se invoca


def _armar(ids=("arquitectura", "cloud")):
    expertos = [get_experto(i) for i in ids]
    workers = [crear_worker(e, _llm()) for e in expertos]
    tareas = [crear_tarea_experto(w, "PROMPT", e["role"]) for w, e in zip(workers, expertos)]
    return crear_crew_ronda(crear_moderador(_llm()), workers, tareas), workers, tareas


def test_crew_jerarquico_con_manager_agent_propio():
    crew, workers, _ = _armar()
    assert crew.process == Process.hierarchical
    assert crew.manager_agent is not None and crew.manager_agent not in crew.agents
    assert crew.manager_agent.allow_delegation


def test_expertos_aislados():
    crew, workers, tareas = _armar()
    assert all(not w.allow_delegation for w in workers)
    assert all(t.context == [] for t in tareas)
    assert crew.memory is False and crew.cache is False
