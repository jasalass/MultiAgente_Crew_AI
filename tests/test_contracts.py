"""Valida la demo contra el contrato publicado sin crear models.py de Juan.

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
