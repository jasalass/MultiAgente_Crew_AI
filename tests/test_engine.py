"""Prueba el bucle del motor con LLM falsos: sin red, sin keys."""
import json
from types import SimpleNamespace

import pytest

from backend.delphi.engine import DelphiEngine, RunCancelado, decidir_continuar
from backend.delphi.models import ConfigRun, Proyecto

CUESTIONARIO = {
    "decisiones": [{"id": "ARQ-D1", "dimension": "arquitectura", "titulo": "Estilo",
                    "alternativas": ["Monolito modular", "Microservicios"]}],
    "items": [
        {"id": "ARQ-E1", "dimension": "arquitectura", "tipo": "evaluacion", "pregunta": "¿Viable?"},
        {"id": "ARQ-D1-a", "dimension": "arquitectura", "tipo": "alternativa", "pregunta": "¿Adecuado?",
         "decision_id": "ARQ-D1", "alternativa": "Monolito modular"},
        {"id": "ARQ-D1-b", "dimension": "arquitectura", "tipo": "alternativa", "pregunta": "¿Adecuado?",
         "decision_id": "ARQ-D1", "alternativa": "Microservicios"},
    ],
}
PANEL = ["arquitectura", "cloud", "desarrollo", "seguridad", "devops"]
CONFIG = ConfigRun(proyecto=Proyecto(nombre="P", objetivo="O", texto_original="# P"), expertos=PANEL)


def _salida(puntajes):
    puntajes = {**puntajes, "VIA-E1": puntajes.get("VIA-E1", 4)}   # el motor agrega siempre la viabilidad
    return json.dumps({"respuestas": [{"item_id": i, "puntaje": p, "justificacion": "Por mantenibilidad y seguridad."}
                                      for i, p in puntajes.items()], "riesgos_detectados": ["Plazo ajustado"]})


def _motor(puntajes_por_ronda):
    """puntajes_por_ronda[ronda-1] -> lista de dicts, uno por experto del panel."""
    llamadas = {"ronda": 0}

    def ejecutar(moderador_llm, expertos, llms, prompts, **_):
        puntajes = puntajes_por_ronda[min(llamadas["ronda"], len(puntajes_por_ronda) - 1)]
        llamadas["ronda"] += 1
        return {e["id"]: _salida(puntajes[n]) for n, e in enumerate(expertos)}

    llm = SimpleNamespace(model="modelo-falso")
    return DelphiEngine(lambda _id: llm, ejecutar,
                        lambda prompt: json.dumps(CUESTIONARIO) if "cuestionario" in prompt.lower()
                        else '{"continuar": true, "motivo": "falta consenso"}')


DISPERSO = [{"ARQ-E1": p, "ARQ-D1-a": p, "ARQ-D1-b": 6 - p} for p in (1, 5, 2, 5, 1)]
CONSENSO = [{"ARQ-E1": 4, "ARQ-D1-a": 5, "ARQ-D1-b": 2}] * 5


def _correr(motor, cancelar=lambda: False):
    eventos = []
    informe = motor.run("r1", CONFIG, eventos.append, cancelar)
    return informe, eventos


def test_consenso_desde_ronda_1_igual_hace_min_2_rondas():
    informe, eventos = _correr(_motor([CONSENSO]))
    assert [r.ronda for r in informe.rondas] == [1, 2]
    assert informe.rondas[0].motivo == "min_rondas" and informe.rondas[1].motivo == "consenso"
    assert [e.seq for e in eventos] == list(range(1, len(eventos) + 1))
    assert eventos[0].tipo == "run_iniciado" and eventos[-1].tipo == "run_finalizado"


def test_sin_consenso_ni_estabilidad_corta_en_max_rondas():
    invertido = [{k: 6 - v for k, v in p.items()} for p in DISPERSO]   # las medianas saltan >= 0,5
    informe, _ = _correr(_motor([DISPERSO, invertido, DISPERSO]))
    assert [r.ronda for r in informe.rondas] == [1, 2, 3]
    assert informe.rondas[-1].motivo == "max_rondas" and informe.rondas[-1].continuar is False


def test_respuestas_anonimas_y_con_auditoria():
    informe, eventos = _correr(_motor([CONSENSO]))
    assert {r.experto_id for r in informe.respuestas} == {"E1", "E2", "E3", "E4", "E5"}
    assert all(r.modelo == "modelo-falso" for r in informe.respuestas)
    assert sum(e.tipo == "respuesta_experto" for e in eventos) == 10


def test_cancelacion_emite_evento_y_corta():
    eventos = []
    with pytest.raises(RunCancelado):
        _motor([CONSENSO]).run("r1", CONFIG, eventos.append, lambda: True)
    assert eventos[-1].tipo == "run_cancelado"


def test_respuesta_invalida_de_experto_emite_error():
    motor = _motor([CONSENSO])
    motor._ejecutar_ronda = lambda *a, **k: {e: "no es json" for e in PANEL}
    eventos = []
    with pytest.raises(Exception):
        motor.run("r1", CONFIG, eventos.append, lambda: False)
    assert eventos[-1].tipo == "error"


def test_reglas_de_continuacion():
    cfg = CONFIG
    assert decidir_continuar(1, cfg, 1.0, False, None) == (True, "min_rondas")
    assert decidir_continuar(2, cfg, 0.9, False, None) == (False, "consenso")
    assert decidir_continuar(2, cfg, 0.2, True, None) == (False, "estabilidad")
    assert decidir_continuar(3, cfg, 0.2, False, True) == (False, "max_rondas")
    assert decidir_continuar(2, cfg, 0.2, False, False) == (False, "moderador")
    assert decidir_continuar(2, cfg, 0.2, False, True) == (True, "moderador")


def test_moderadores_rotan_entre_modelos():
    from backend.delphi.engine import elegir_moderador
    assert [elegir_moderador(["A", "B"], n) for n in range(5)] == ["A", "B", "A", "B", "A"]
    assert elegir_moderador("unico", 3) == "unico"


def test_el_prompt_no_repite_el_texto_original():
    from backend.delphi.engine import _proyecto_para_experto
    solo_texto = Proyecto(nombre="P", objetivo="O", texto_original="# P\nlibre")
    assert "texto_original" in _proyecto_para_experto(solo_texto)            # nada estructurado: se conserva
    estructurado = Proyecto(nombre="P", objetivo="O", restricciones=["6 meses"], texto_original="# P\n...")
    assert "texto_original" not in _proyecto_para_experto(estructurado)


def test_reintenta_una_vez_si_el_experto_omite_items():
    completo = _salida({"ARQ-E1": 4, "ARQ-D1-a": 5, "ARQ-D1-b": 2})
    parcial = _salida({"ARQ-E1": 4})                                  # se salta las alternativas
    llamadas = []

    class LLMDistraido:
        model = "distraido"

        def call(self, prompt):
            llamadas.append(prompt)
            return completo                                           # el reintento sí responde todo

    motor = _motor([CONSENSO])
    motor._ejecutar_ronda = lambda *a, **k: {e: parcial for e in PANEL}
    motor._llm_para = lambda _id: LLMDistraido()
    informe, _ = _correr(motor)
    assert len(llamadas) == 5 * 2 and "no fue válida" in llamadas[0]   # 1 reintento por experto y ronda
    assert len(informe.respuestas[0].respuestas) == 3 + 1          # + la viabilidad que agrega el motor


# --- Ronda con CrewAI simulado: cambio de modelo y cancelación entre expertos ---------

def _crew_falso(monkeypatch, responder):
    """Reemplaza el Crew por uno que delega directo en el worker, como haría el Moderador."""
    from crewai import Agent

    import backend.delphi.crew as crew

    class CrewFalso:
        def __init__(self, workers):
            self.workers = workers

        def kickoff(self):
            for w in self.workers:
                try:
                    w.execute_task(None)
                except Exception:
                    pass                                        # CrewAI se lo pasa al manager como texto
    monkeypatch.setattr(Agent, "execute_task", lambda self, task, context=None, tools=None: responder(self))
    monkeypatch.setattr(crew, "crear_crew_ronda", lambda moderador, workers, tareas, *a: CrewFalso(workers))
    monkeypatch.setattr(crew, "crear_moderador", lambda llm: None)


def _motor_crewai(llm_para, **extra):
    from functools import partial

    from backend.delphi.engine import ejecutar_ronda_crewai
    return DelphiEngine(llm_para, partial(ejecutar_ronda_crewai, dormir=lambda s: None),
                        lambda prompt: json.dumps(CUESTIONARIO) if "cuestionario" in prompt.lower()
                        else '{"continuar": true}', **extra)


def _llm(nombre):
    from crewai import LLM
    # Igual que ModelPool: un endpoint compatible permite nombres ajenos al
    # catálogo nativo. El Crew falso intercepta las llamadas de estas pruebas.
    return LLM(model=f"openai/{nombre}", api_key="no-se-usa", base_url="http://127.0.0.1:1/v1")


def test_429_persistente_cambia_el_modelo_del_experto_y_lo_registra(monkeypatch):
    def responder(worker):
        if worker.llm.model.endswith("saturado"):
            raise RuntimeError("429 Rate limit reached for model `saturado`")
        return _salida(CONSENSO[0])
    _crew_falso(monkeypatch, responder)
    llms = {"cloud": _llm("saturado"), "moderador": [_llm("moderador")]}
    motor = _motor_crewai(lambda i: llms.get(i, _llm("sano")), modelo_alternativo=lambda i: _llm("respaldo"))
    informe, eventos = _correr(motor)
    cambio = next(e for e in eventos if e.tipo == "cambio_modelo")
    saturado, respaldo = _llm("saturado").model, _llm("respaldo").model
    assert cambio.payload == {"experto": "cloud", "anterior": saturado, "nuevo": respaldo,
                              "motivo": "límite de tasa persistente"}
    assert {r.modelo for r in informe.respuestas if r.rol == "cloud"} == {respaldo}


def test_si_el_limite_es_del_moderador_no_se_cambia_al_experto(monkeypatch):
    def responder(worker):
        raise RuntimeError("429 Rate limit reached for model `moderador`")
    _crew_falso(monkeypatch, responder)
    cambios = []
    motor = _motor_crewai(lambda i: [_llm("moderador")] if i == "moderador" else _llm("sano"),
                          modelo_alternativo=lambda i: cambios.append(i))
    with pytest.raises(Exception):
        _correr(motor)
    assert cambios == []


def test_la_cancelacion_se_revisa_entre_expertos(monkeypatch):
    respondidos = []

    def responder(worker):
        respondidos.append(worker.role)
        return _salida(CONSENSO[0])
    _crew_falso(monkeypatch, responder)
    motor = _motor_crewai(lambda i: [_llm("m")] if i == "moderador" else _llm("sano"))
    eventos = []
    with pytest.raises(RunCancelado):
        motor.run("r1", CONFIG, eventos.append, lambda: len(respondidos) >= 2)
    assert len(respondidos) == 2 and eventos[-1].tipo == "run_cancelado"


def test_aviso_si_roles_afines_terminan_con_el_mismo_modelo():
    from backend.delphi.models import RespuestaExperto
    modelos = {"arquitectura": "m1", "desarrollo": "m1", "cloud": "m2", "devops": "m3"}
    respuestas = [RespuestaExperto(experto_id=f"E{n}", rol=rol, modelo=m, ronda=1, respuestas=[])
                  for n, (rol, m) in enumerate(modelos.items(), 1)]
    avisos = DelphiEngine(lambda _: None, avisos=["del pool"])._avisos_finales(respuestas)
    assert avisos[0] == "del pool" and "arquitectura y desarrollo" in avisos[1]


def test_cuestionario_y_riesgos_van_al_llm_puntual_con_respaldo_del_moderador():
    llamadas = []

    class LLMFalso:
        def __init__(self, nombre, falla=False):
            self.model, self.falla = nombre, falla

        def call(self, prompt):
            llamadas.append((self.model, "cuestionario" if "Diseña el cuestionario" in prompt
                             else "riesgos" if "riesgos técnicos" in prompt else "continuar"))
            if self.falla:
                raise RuntimeError("timeout")
            return json.dumps(CUESTIONARIO) if "Diseña el cuestionario" in prompt else '{"continuar": true}'

    def ejecutar(moderador_llm, expertos, llms, prompts, **_):
        return {e["id"]: _salida(CONSENSO[n]) for n, e in enumerate(expertos)}

    for falla, quien in ((False, "puntual"), (True, "moderador")):
        llamadas.clear()
        llms = {"puntual": [LLMFalso("puntual", falla)], "moderador": [LLMFalso("moderador")]}
        motor = DelphiEngine(lambda i: llms.get(i, SimpleNamespace(model="experto")), ejecutar)
        informe, _ = _correr(motor)
        hechas = {tarea: modelo for modelo, tarea in llamadas if not (falla and modelo == "puntual")}
        assert hechas["cuestionario"] == quien and hechas["riesgos"] == quien
        assert any("puntual" in a for a in informe.avisos) == falla


def test_modelo_retirado_cambia_de_inmediato_y_no_se_vuelve_a_ofrecer(monkeypatch):
    def responder(worker):
        if worker.llm.model.endswith("retirado"):
            raise RuntimeError("Error code: 404 - The `:free` variant has been retired")
        return _salida(CONSENSO[0])
    _crew_falso(monkeypatch, responder)
    pedidos = []

    def alternativo(experto_id, caido=False):
        pedidos.append((experto_id, caido))
        return _llm("respaldo")
    llms = {"cloud": _llm("retirado"), "moderador": [_llm("moderador")]}
    motor = _motor_crewai(lambda i: llms.get(i, _llm("sano")), modelo_alternativo=alternativo)
    informe, eventos = _correr(motor)
    assert pedidos == [("cloud", True)]
    assert next(e for e in eventos if e.tipo == "cambio_modelo").payload["motivo"] == "modelo no disponible"


def test_el_cuestionario_se_acota_a_las_reglas_del_readme():
    from backend.delphi.engine import acotar_cuestionario
    from backend.delphi.models import Cuestionario
    decisiones = [{"id": f"ARQ-D{n}", "dimension": "arquitectura", "titulo": f"D{n}", "alternativas": ["a", "b"]}
                  for n in range(1, 8)]
    items = [{"id": f"ARQ-E{n}", "dimension": "arquitectura", "tipo": "evaluacion", "pregunta": "?"} for n in range(1, 14)]
    items += [{"id": f"{d['id']}-{x}", "dimension": "arquitectura", "tipo": "alternativa", "pregunta": "?",
               "decision_id": d["id"], "alternativa": x} for d in decisiones for x in "ab"]
    c = acotar_cuestionario(Cuestionario.model_validate({"decisiones": decisiones, "items": items}))
    assert [d.id for d in c.decisiones] == [f"ARQ-D{n}" for n in range(1, 6)]
    assert sum(i.tipo == "evaluacion" for i in c.items) == 10 and len(c.items) == 10 + 5 * 2
    assert {i.decision_id for i in c.items if i.decision_id} == {d.id for d in c.decisiones}


def test_cada_respuesta_se_emite_apenas_responde_el_experto():
    eventos = []

    def ejecutar(moderador_llm, expertos, llms, prompts, al_responder=None, **_):
        salida = {}
        for n, e in enumerate(expertos):
            salida[e["id"]] = _salida(CONSENSO[n])
            al_responder(e["id"], salida[e["id"]])
            # Cuando responde el experto n, sus respuestas ya están en los eventos.
            assert sum(ev.tipo == "respuesta_experto" and ev.ronda == eventos[-1].ronda
                       for ev in eventos) == n + 1
        return salida
    motor = DelphiEngine(lambda _id: SimpleNamespace(model="m"), ejecutar,
                         lambda p: json.dumps(CUESTIONARIO) if "cuestionario" in p.lower() else '{"continuar": true}')
    informe = motor.run("r1", CONFIG, eventos.append, lambda: False)
    assert sum(e.tipo == "respuesta_experto" for e in eventos) == 5 * len(informe.rondas)


def test_expertos_en_paralelo_con_eventos_en_orden(monkeypatch):
    import threading
    juntos = threading.Barrier(5, timeout=10)      # solo se cruza si los 5 responden a la vez

    def responder(worker):
        juntos.wait()
        return _salida(CONSENSO[0])
    _crew_falso(monkeypatch, responder)
    motor = _motor_crewai(lambda i: [_llm("m")] if i == "moderador" else _llm("sano"), paralelo=5)
    informe, eventos = _correr(motor)
    assert [e.seq for e in eventos] == list(range(1, len(eventos) + 1))
    for ronda in informe.rondas:
        tipos = [e.tipo for e in eventos if e.ronda == ronda.ronda]
        assert tipos.count("respuesta_experto") == 5 and tipos.index("ronda_agregada") > 5


def test_evaluacion_vinculada_a_una_decision_no_compite_como_alternativa():
    from backend.delphi.adr import construir_adrs
    from backend.delphi.decisiones import recomendar_decisiones
    from backend.delphi.engine import acotar_cuestionario
    from backend.delphi.models import Cuestionario, EstadisticaItem, ResumenRonda
    crudo = json.loads(json.dumps(CUESTIONARIO))
    crudo["items"][0]["decision_id"] = "ARQ-D1"         # evaluación "colgada" de la decisión (pasó con LLM real)
    c = acotar_cuestionario(Cuestionario.model_validate(crudo))
    assert c.items[0].decision_id is None
    stats = [EstadisticaItem(item_id=i, mediana=m, q1=m, q3=m, iqr=0, consenso=True,
                             argumentos_a_favor=[], argumentos_en_contra=[])
             for i, m in (("ARQ-E1", 5), ("ARQ-D1-a", 4), ("ARQ-D1-b", 2))]
    rondas = [ResumenRonda(ronda=1, estadisticas=stats, porcentaje_consenso=1, continuar=False, motivo="consenso")]
    sin_normalizar = Cuestionario.model_validate(crudo)       # también robusto sin normalizar
    for cuestionario in (c, sin_normalizar):
        [d] = recomendar_decisiones(cuestionario, rondas[0])
        assert d.alternativa_recomendada == "Monolito modular"
        [adr] = construir_adrs(CONFIG.proyecto, cuestionario, rondas, [d])
        assert adr.alternativas_consideradas == ["Monolito modular", "Microservicios"]


def test_respuesta_invalida_persistente_cambia_de_modelo_en_vez_de_abortar():
    completo = _salida({"ARQ-E1": 4, "ARQ-D1-a": 5, "ARQ-D1-b": 2})
    parcial = _salida({"ARQ-E1": 4})

    class LLMTerco:
        model = "terco"

        def call(self, prompt):
            return parcial                                     # el reintento tampoco corrige

    class LLMBueno:
        model = "bueno"

        def call(self, prompt):
            return completo
    motor = _motor([CONSENSO])
    motor._ejecutar_ronda = lambda *a, **k: {e: (parcial if e == "cloud" else completo) for e in PANEL}
    motor._llm_para = lambda i: LLMTerco() if i == "cloud" else LLMBueno()
    motor._modelo_alternativo = lambda i: LLMBueno()
    informe, eventos = _correr(motor)
    cambios = [e.payload for e in eventos if e.tipo == "cambio_modelo"]
    assert cambios and cambios[0]["motivo"] == "respuesta inválida" and cambios[0]["experto"] == "cloud"
    assert {r.modelo for r in informe.respuestas if r.rol == "cloud"} == {"bueno"}


def test_encadena_modelos_de_respaldo_hasta_que_uno_responde(monkeypatch):
    def responder(worker):
        if worker.llm.model.endswith(("caido-1", "caido-2")):
            raise RuntimeError("Error code: 404 - model not found")
        return _salida(CONSENSO[0])
    _crew_falso(monkeypatch, responder)
    respaldos = iter(["caido-2", "sano-3"])
    llms = {"cloud": _llm("caido-1"), "moderador": [_llm("moderador")]}
    motor = _motor_crewai(lambda i: llms.get(i, _llm("sano")),
                          modelo_alternativo=lambda i, caido=False: _llm(next(respaldos)))
    informe, eventos = _correr(motor)
    assert [e.payload["nuevo"].removeprefix("openai/") for e in eventos if e.tipo == "cambio_modelo"] == ["caido-2", "sano-3"]


@pytest.mark.parametrize("notas, veredicto", [
    ([4, 4, 5, 4, 4], "viable"), ([3, 3, 4, 3, 3], "viable_con_condiciones"),
    ([2, 1, 2, 2, 2], "no_viable"), ([1, 5, 1, 5, 3], "en_discusion"),
])
def test_veredicto_de_viabilidad_explicito(notas, veredicto):
    puntajes = [{**CONSENSO[0], "VIA-E1": n} for n in notas]
    informe, eventos = _correr(_motor([puntajes]))
    assert any(i.id == "VIA-E1" for i in informe.cuestionario.items)      # la pregunta la agrega el motor
    assert informe.viabilidad.veredicto == veredicto and informe.viabilidad.explicacion
    from backend.delphi.report import renderizar_informe
    assert "## Veredicto de viabilidad" in renderizar_informe(informe)


def test_un_500_del_proveedor_se_reintenta_y_luego_cambia_de_modelo(monkeypatch):
    def responder(worker):
        if worker.llm.model.endswith("inestable"):
            raise RuntimeError("Error code: 500 - [{'error': {'code': 500, 'message': 'Internal error encountered.'}}]")
        return _salida(CONSENSO[0])
    _crew_falso(monkeypatch, responder)
    llms = {"cloud": _llm("inestable"), "moderador": [_llm("moderador")]}
    motor = _motor_crewai(lambda i: llms.get(i, _llm("sano")), modelo_alternativo=lambda i: _llm("respaldo"))
    informe, eventos = _correr(motor)
    assert next(e for e in eventos if e.tipo == "cambio_modelo").payload["experto"] == "cloud"
    assert informe.rondas
