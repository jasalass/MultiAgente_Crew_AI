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
