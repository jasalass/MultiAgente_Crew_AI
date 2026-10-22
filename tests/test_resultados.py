"""Decisiones, riesgos, ADR e informe, sobre una corrida completa con LLM falsos."""
from backend.delphi.adr import escribir_adrs, renderizar_adr
from backend.delphi.decisiones import clasificar_decision, consolidar_riesgos
from backend.delphi.models import Cuestionario, Decision, EstadisticaItem, RespuestaExperto
from backend.delphi.report import renderizar_informe
from tests.test_engine import CONFIG, CONSENSO, CUESTIONARIO, DISPERSO, _correr, _motor


def _stat(item_id, mediana, iqr):
    return EstadisticaItem(item_id=item_id, mediana=mediana, q1=mediana, q3=mediana + iqr, iqr=iqr,
                           consenso=iqr <= 1, argumentos_a_favor=[], argumentos_en_contra=[])


def _clasificar(a, b):
    c = Cuestionario.model_validate(CUESTIONARIO)
    return clasificar_decision(c.decisiones[0], c, {"ARQ-D1-a": _stat("ARQ-D1-a", *a),
                                                    "ARQ-D1-b": _stat("ARQ-D1-b", *b)})


def test_regla_firme_condicionada_abierta():
    firme = _clasificar((5, 0), (2, 0))
    assert firme.estado == "firme" and firme.alternativa_recomendada == "Monolito modular"
    assert _clasificar((4, 0), (3.5, 0)).estado == "condicionada"      # margen < 1
    assert _clasificar((3, 0), (2, 0)).estado == "condicionada"        # mediana 3
    abierta = _clasificar((4, 2), (2, 0))                              # IQR > 1
    assert abierta.estado == "abierta" and abierta.alternativa_recomendada is None and abierta.poc_sugerida
    assert _clasificar((2, 0), (1, 0)).estado == "abierta"             # ninguna es adecuada


def test_informe_completo_con_consenso(tmp_path):
    informe, _ = _correr(_motor([CONSENSO]))
    d = informe.decisiones[0]
    assert d.estado == "firme" and d.alternativa_recomendada == "Monolito modular"
    assert informe.riesgos and informe.riesgos[0].menciones == 5          # respaldo determinista
    assert "panel mono-modelo" in informe.avisos[0]                       # los LLM falsos son uno solo
    assert informe.sesgo_por_modelo and informe.evaluacion_por_dimension["arquitectura"] == 4
    md = renderizar_informe(informe)
    assert "✅ Firme" in md and "Matriz de riesgos" in md
    rutas = escribir_adrs(informe.adrs, tmp_path / "adr")
    assert rutas[0].name == "ADR-001-estilo.md"
    assert "Evidencia Delphi" in renderizar_adr(informe.adrs[0]) and informe.adrs[0].estado == "aceptada"


def test_sin_consenso_deja_la_decision_abierta():
    invertido = [{k: 6 - v for k, v in p.items()} for p in DISPERSO]
    informe, _ = _correr(_motor([DISPERSO, invertido, DISPERSO]))
    assert informe.decisiones[0].estado == "abierta" and informe.disensos
    assert informe.adrs[0].estado == "abierta" and "PoC" in informe.adrs[0].decision


def test_riesgos_usan_respaldo_si_el_llm_falla():
    resp = [RespuestaExperto(experto_id=f"E{n}", rol="x", modelo="m", ronda=1, respuestas=[],
                             riesgos_detectados=["Plazo ajustado"] if n < 3 else ["Fuga de datos"])
            for n in range(1, 4)]
    riesgos = consolidar_riesgos(resp, lambda p: "basura", 3)
    assert {r.descripcion: r.menciones for r in riesgos} == {"Plazo ajustado": 2, "Fuga de datos": 1}
