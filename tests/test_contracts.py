"""Valida la demo contra el contrato publicado y los modelos integrados de la API.

El bloque Python del README es la fuente acordada de los modelos. Se compila
en memoria para que cambiar un campo del mock nunca pase inadvertido.
"""
from datetime import datetime
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field
from backend.delphi.experts import listar_expertos
from frontend.api_client import ApiClient
from frontend.mocks import ejemplos_proyectos


def contratos():
    texto = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    seccion = texto.split("### 4.1 Modelos de datos", 1)[1]
    codigo = seccion.split("```python", 1)[1].split("```", 1)[0]
    contexto = dict(BaseModel=BaseModel, Field=Field, Literal=Literal, datetime=datetime)
    exec(compile(codigo, "README §4.1", "exec"), contexto)
    return contexto


def test_catalogo_y_proyectos_cumplen_contrato_publicado():
    modelos = contratos()
    for experto in listar_expertos():
        modelos["Experto"].model_validate(experto)
    for proyecto in ejemplos_proyectos():
        modelos["Proyecto"].model_validate(proyecto)


def test_run_eventos_informe_cumplen_contrato_publicado():
    modelos = contratos()
    api = ApiClient(use_mocks=True)
    for estado in api.listar_runs():
        modelos["EstadoRun"].model_validate(estado)
        for evento in api.obtener_eventos(estado["run_id"]):
            modelos["EventoDelphi"].model_validate(evento)
        informe = api.obtener_informe(estado["run_id"])
        modelos["InformeDelphi"].model_validate(informe)


def test_mock_cumple_modelos_reales_y_regla_de_viabilidad():
    from backend.delphi.models import ConfigRun, EstadoRun, EventoDelphi, InformeDelphi
    from backend.delphi.stats import veredicto_viabilidad

    api = ApiClient(use_mocks=True)
    for proyecto in ejemplos_proyectos():
        config = ConfigRun(proyecto=proyecto, expertos=["arquitectura", "cloud", "desarrollo", "seguridad", "devops"])
        run_id = api.crear_run(config)["run_id"]
        cursor = 0
        for _ in range(100):
            for evento in api.obtener_eventos(run_id, cursor):
                EventoDelphi.model_validate(evento)
                cursor = evento["seq"]
            estado = EstadoRun.model_validate(api.obtener_run(run_id))
            if estado.estado == "finalizado":
                break
        assert estado.estado == "finalizado"
        informe = InformeDelphi.model_validate(api.obtener_informe(run_id))
        assert informe.viabilidad is not None
        ultima = next(e for e in informe.rondas[-1].estadisticas if e.item_id == "VIA-E1")
        assert informe.viabilidad.veredicto == veredicto_viabilidad(ultima.consenso, ultima.mediana)


def test_parser_mock_y_api_comparten_la_plantilla_y_los_ejemplos():
    from backend.delphi.project_loader import parsear_markdown

    api = ApiClient(use_mocks=True)
    rutas = (Path(__file__).resolve().parents[1] / "data" / "proyectos").glob("*.md")
    for ruta in rutas:
        texto = ruta.read_text(encoding="utf-8-sig")
        assert api.parsear_proyecto(texto) == parsear_markdown(texto).model_dump()
