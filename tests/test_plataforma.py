"""stats.py, llm_io.py, project_loader.py, data/ y contratos de models.py frente al README."""
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from backend.delphi import llm_io, models, stats
from backend.delphi.project_loader import cargar_proyecto, parsear_markdown
from tests.test_contracts import contratos

RAIZ = Path(__file__).resolve().parents[1]


# --- stats.py ---------------------------------------------------------------------

def test_mediana_cuartiles_e_iqr():
    valores = [1, 2, 3, 4, 5]
    assert stats.mediana(valores) == 3
    assert stats.cuartiles(valores) == (2.0, 4.0)
    assert stats.iqr(valores) == 2.0
    assert stats.cuartiles([4]) == (4.0, 4.0)


def test_consenso_por_item_y_global():
    assert stats.hay_consenso([4, 4, 5, 4, 4]) and not stats.hay_consenso([1, 5, 1, 5, 3])
    assert stats.porcentaje_consenso([True, False, True, True]) == 0.75
    assert stats.porcentaje_consenso([]) == 0.0


def test_estabilidad_entre_rondas():
    assert not stats.es_estable({"A": 4}, None)
    assert stats.es_estable({"A": 4.0, "B": 2.0}, {"A": 4.4, "B": 2.0})
    assert not stats.es_estable({"A": 4.0}, {"A": 3.5})                  # 0,5 ya no es estable


@pytest.mark.parametrize("consenso, mediana, margen, esperado", [
    (True, 5, 3, "firme"), (True, 4, 1, "firme"),
    (True, 4, 0.5, "condicionada"), (True, 3, 2, "condicionada"), (True, 3.5, 1, "condicionada"),
    (False, 5, 3, "abierta"), (True, 2, 1, "abierta"),
])
def test_regla_de_recomendacion(consenso, mediana, margen, esperado):
    assert stats.estado_decision(consenso, mediana, margen) == esperado


# --- llm_io.py --------------------------------------------------------------------

class _Salida(BaseModel):
    texto: str


def test_extrae_json_con_think_cercas_y_comillas_escapadas():
    crudo = '<think>razono {mucho}</think>Aquí va:\n```json\n{"texto": "usa \\"microservicios {no}\\" ya"}\n```'
    assert llm_io.validar(crudo, _Salida).texto == 'usa "microservicios {no}" ya'


def test_reintenta_una_vez_con_el_error():
    respuestas = iter(["sin json", '{"texto": "ok"}'])
    prompts = []

    def llamar(prompt):
        prompts.append(prompt)
        return next(respuestas)
    assert llm_io.llamar_y_validar(llamar, "P", _Salida).texto == "ok"
    assert "no fue válida" in prompts[1]
    with pytest.raises((ValueError, ValidationError)):
        llm_io.llamar_y_validar(lambda _: "nada", "P", _Salida)


# --- project_loader.py y data/ ------------------------------------------------------

def test_parsea_secciones_listas_y_comentarios():
    texto = ("# Portal\n\n## Objetivo y contexto\n<!-- instrucción -->\nAtender\nusuarios\n\n"
             "## Requisitos no funcionales\n- 99 %\n2. Latencia\n- \n\n## Decisiones a evaluar (opc.)\n- A vs B\n")
    p = parsear_markdown(texto)
    assert p.nombre == "Portal" and p.objetivo == "Atender\nusuarios"
    assert p.requisitos_no_funcionales == ["99 %", "Latencia"]
    assert p.decisiones_a_evaluar == ["A vs B"] and p.texto_original == texto


def test_exige_objetivo():
    with pytest.raises(ValueError, match="Objetivo"):
        parsear_markdown("# Sin objetivo\n\n## Equipo\nDos personas\n")


def test_proyectos_de_ejemplo_y_plantilla():
    proyectos = sorted((RAIZ / "data" / "proyectos").glob("*.md"))
    assert len(proyectos) == 3
    for ruta in proyectos:
        p = cargar_proyecto(ruta)
        assert p.objetivo and p.requisitos_funcionales and p.restricciones and p.equipo
    with pytest.raises(ValueError):                    # la plantilla vacía no tiene objetivo
        cargar_proyecto(RAIZ / "data" / "plantilla_proyecto.md")


# --- models.py = README §4.1 ------------------------------------------------------

def test_models_coincide_con_el_contrato_del_readme():
    publicados = {n: c for n, c in contratos().items() if isinstance(c, type) and issubclass(c, BaseModel)
                  and c is not BaseModel}
    assert publicados
    for nombre, publicado in publicados.items():
        local = getattr(models, nombre)
        assert local.model_fields.keys() == publicado.model_fields.keys(), nombre


def test_quita_el_razonamiento_con_thought():
    assert llm_io.validar('<thought>pienso {"x": 1}</thought>{"texto": "ok"}', _Salida).texto == "ok"
