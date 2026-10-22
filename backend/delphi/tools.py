"""DelphiStatsTool: la estadística de cada ronda la calcula código, no el LLM.

El Moderador (LLM) puede invocar esta herramienta, pero los números salen de
stats.py. Así la mediana, el IQR y el consenso son reproducibles y auditables.
La herramienta NO redacta argumentos: eso es del AnonymizerTool (anonymizer.py).
El motor une ambos resultados en cada EstadisticaItem.
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from backend.delphi import stats


def _dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, Mapping):
        raise ValueError("Se esperaba un objeto de datos")
    return dict(value)


def estadisticas_ronda(respuestas: list[Any], umbral_iqr: float = 1.0) -> list[dict[str, Any]]:
    """Agrupa los puntajes por ítem y calcula mediana, Q1, Q3, IQR y consenso.

    `respuestas` son RespuestaExperto (modelo o dict) de UNA sola ronda.
    Devuelve una lista de dicts compatibles con EstadisticaItem (sin argumentos).
    """
    puntajes: dict[str, list[float]] = defaultdict(list)
    rondas = set()
    for respuesta in respuestas:
        datos = _dict(respuesta)
        rondas.add(datos.get("ronda"))
        for item in datos["respuestas"]:
            item = _dict(item)
            puntaje = item["puntaje"]
            if not 1 <= puntaje <= 5:
                raise ValueError(f"Puntaje fuera de la escala 1-5 en {item['item_id']}")
            puntajes[item["item_id"]].append(puntaje)
    if len(rondas) > 1:
        raise ValueError("Las estadísticas deben calcularse sobre una sola ronda")

    resultado = []
    for item_id in sorted(puntajes):
        valores = puntajes[item_id]
        q1, q3 = stats.cuartiles(valores)
        resultado.append({
            "item_id": item_id,
            "mediana": stats.mediana(valores),
            "q1": q1,
            "q3": q3,
            "iqr": q3 - q1,
            "consenso": (q3 - q1) <= umbral_iqr,
            "n": len(valores),
        })
    return resultado


def porcentaje_consenso(estadisticas: list[dict[str, Any]]) -> float:
    """Fracción (0-1) de ítems con consenso; se compara con umbral_consenso_global."""
    if not estadisticas:
        return 0.0
    return sum(1 for e in estadisticas if e["consenso"]) / len(estadisticas)


def _ejecutar(respuestas: list[Any], umbral_iqr: float = 1.0) -> str:
    por_item = estadisticas_ronda(respuestas, umbral_iqr)
    return json.dumps({"estadisticas": por_item,
                       "porcentaje_consenso": porcentaje_consenso(por_item)},
                      ensure_ascii=False)


# Mismo patrón que AnonymizerTool: BaseTool real si CrewAI está instalado.
try:
    from crewai.tools import BaseTool
except ModuleNotFoundError as error:
    if error.name != "crewai":
        raise

    class DelphiStatsTool:
        """Adaptador local para depurar sin CrewAI instalado."""

        name = "estadisticas_delphi"
        description = "Calcula mediana, Q1, Q3, IQR y consenso de cada ítem de una ronda."

        def run(self, respuestas: list[Any], umbral_iqr: float = 1.0) -> str:
            return _ejecutar(respuestas, umbral_iqr)

        _run = run
else:
    from pydantic import BaseModel, Field

    class DelphiStatsInput(BaseModel):
        respuestas: list[dict[str, Any]] = Field(description="Respuestas de los expertos de una sola ronda")
        umbral_iqr: float = Field(default=1.0, description="IQR máximo para declarar consenso")

    class DelphiStatsTool(BaseTool):
        name: str = "estadisticas_delphi"
        description: str = "Calcula mediana, Q1, Q3, IQR y consenso de cada ítem de una ronda."
        args_schema: type[BaseModel] = DelphiStatsInput

        def _run(self, respuestas: list[dict[str, Any]], umbral_iqr: float = 1.0) -> str:
            return _ejecutar(respuestas, umbral_iqr)
