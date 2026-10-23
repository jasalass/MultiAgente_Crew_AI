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


def test_moderador_sin_herramientas():
    # CrewAI lanza excepción si el manager_agent tiene tools; el kickoff real lo descubrió.
    assert not crear_moderador(_llm()).tools


def test_el_experto_responde_su_enunciado_sellado_y_no_el_del_moderador(monkeypatch):
    """La delegación real de CrewAI pasa el texto del Moderador; el experto usa el del código."""
    from crewai import Agent
    from crewai.tools.agent_tools.delegate_work_tool import DelegateWorkTool

    recibido = {}

    def ejecutar(self, task, context=None, tools=None):
        recibido.update(descripcion=task.description, contexto=context)
        return '{"respuestas": [], "riesgos_detectados": []}'
    monkeypatch.setattr(Agent, "execute_task", ejecutar)
    experto = get_experto("cloud")
    worker = crear_worker(experto, _llm())
    tarea = crear_tarea_experto(worker, "PROMPT SELLADO", experto["role"])
    assert "PROMPT SELLADO" not in tarea.description            # el Moderador ya no lo copia
    delegar = DelegateWorkTool(agents=[worker], description="delegar")
    salida = delegar._run(task="Resumen libre del Moderador", context="Lo que opinó otro experto",
                          coworker=experto["role"])
    assert recibido == {"descripcion": "PROMPT SELLADO", "contexto": None}
    assert worker.salida == salida and worker.error is None


def test_el_error_del_experto_queda_registrado_aunque_crewai_lo_oculte(monkeypatch):
    from crewai import Agent
    from crewai.tools.agent_tools.delegate_work_tool import DelegateWorkTool

    def falla(self, *a, **k):
        raise RuntimeError("Error 429: rate limit")
    monkeypatch.setattr(Agent, "execute_task", falla)
    experto = get_experto("cloud")
    worker = crear_worker(experto, _llm())
    crear_tarea_experto(worker, "P", experto["role"])
    texto = DelegateWorkTool(agents=[worker], description="d")._run(task="t", context=None,
                                                                    coworker=experto["role"])
    assert isinstance(texto, str)                               # CrewAI lo convirtió en texto…
    assert "429" in str(worker.error) and worker.salida is None  # …pero el motor lo ve
