"""Medidas descriptivas por modelo, sin llamadas a un LLM.

``calcular_sesgo(respuestas, cuestionario)`` acepta diccionarios y modelos
Pydantic y devuelve los campos exactos de ``SesgoModelo`` del README. Por cada
par experto/ítem se toma solo la respuesta de la ronda más reciente: volver a
contestar o cambiar de modelo no multiplica el peso de un experto.

La desviación compara cada puntuación con la mediana del MISMO ítem del panel.
Por eso no confunde que un modelo haya contestado preguntas más favorables con
una preferencia por sus alternativas. El resultado sigue siendo descriptivo:
rol, proyecto y modelo están confundidos si no se rota la asignación entre
ejecuciones. No demuestra sesgo causal de una familia de modelos.

Control reproducible de la interfaz (datos ficticios, sin keys)::

    python -m scripts.experimento_sesgo --mock

Control con los modelos y la API de Juan/Pamela en ejecución::

    python -m scripts.experimento_sesgo --api-url http://localhost:8000
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from numbers import Real
from statistics import fmean, median
from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    raise TypeError("Se esperaba un diccionario o un modelo Pydantic.")


def _texto(value: Any, campo: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{campo} debe ser un texto no vacío.")
    return value.strip()


def calcular_sesgo(
    respuestas: Iterable[Any], cuestionario: Any
) -> list[dict[str, Any]]:
    """Agrupa las puntuaciones vigentes por modelo y alternativa.

    ``puntaje_medio`` es la media de las puntuaciones vigentes del modelo.
    ``desviacion_vs_mediana_grupo`` es la media de sus diferencias contra las
    medianas de los ítems correspondientes (incluyendo al propio modelo).
    ``preferencias`` aplica esa misma operación solo a cada alternativa.
    Se mantienen los nombres de alternativas únicos; si el mismo nombre se
    repite en decisiones distintas, se añade su ``decision_id`` para evitar
    mezclar decisiones. Las cifras conservan su precisión, sin redondeo.

    Un payload repetido idéntico no altera los resultados. Dos puntuaciones o
    modelos incompatibles para el mismo experto/ítem/ronda son un error de
    datos, no dos votos. Los ítems desconocidos también producen ``ValueError``.
    """
    cuestionario = _dict(cuestionario)
    items: dict[str, dict[str, Any]] = {}
    alternativas: dict[str, set[str]] = defaultdict(set)
    for item_original in cuestionario.get("items", []):
        item = _dict(item_original)
        item_id = _texto(item.get("id"), "item.id")
        if item_id in items:
            raise ValueError(f"Ítem duplicado en el cuestionario: {item_id}.")
        items[item_id] = item
        if item.get("tipo") == "alternativa":
            nombre = _texto(item.get("alternativa"), "item.alternativa")
            decision = _texto(item.get("decision_id"), "item.decision_id")
            alternativas[nombre].add(decision)

    # clave -> (ronda, modelo, puntaje). Identidad estable incluso si se cambia
    # el modelo de un experto por fallback en una ronda posterior.
    ultimas: dict[tuple[str, str], tuple[int, str, int]] = {}
    observadas: dict[tuple[str, str, int], tuple[str, int]] = {}
    for original in respuestas:
        respuesta = _dict(original)
        experto = _texto(respuesta.get("experto_id"), "experto_id")
        modelo = _texto(respuesta.get("modelo"), "modelo")
        ronda = respuesta.get("ronda")
        if isinstance(ronda, bool) or not isinstance(ronda, int) or ronda < 1:
            raise ValueError("ronda debe ser un entero positivo.")
        for respuesta_item in respuesta.get("respuestas", []):
            ri = _dict(respuesta_item)
            item_id = _texto(ri.get("item_id"), "item_id")
            if item_id not in items:
                raise ValueError(f"Respuesta para un ítem desconocido: {item_id}.")
            puntaje = ri.get("puntaje")
            if (
                isinstance(puntaje, bool)
                or not isinstance(puntaje, Real)
                or not 1 <= puntaje <= 5
                or int(puntaje) != puntaje
            ):
                raise ValueError("puntaje debe ser un entero de la escala Likert 1–5.")
            valor = (modelo, int(puntaje))
            identidad = (experto, item_id, ronda)
            if identidad in observadas and observadas[identidad] != valor:
                raise ValueError(
                    f"Respuesta contradictoria para {experto}/{item_id}, ronda {ronda}."
                )
            observadas[identidad] = valor
            clave = (experto, item_id)
            if clave not in ultimas or ronda > ultimas[clave][0]:
                ultimas[clave] = (ronda, *valor)

    por_item: dict[str, list[int]] = defaultdict(list)
    for (_, item_id), (_, _, puntaje) in ultimas.items():
        por_item[item_id].append(puntaje)
    medianas = {item_id: median(valores) for item_id, valores in por_item.items()}
    puntuaciones: dict[str, list[int]] = defaultdict(list)
    desviaciones: dict[str, list[float]] = defaultdict(list)
    preferencias: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (_, item_id), (_, modelo, puntaje) in ultimas.items():
        delta = puntaje - medianas[item_id]
        puntuaciones[modelo].append(puntaje)
        desviaciones[modelo].append(delta)
        item = items[item_id]
        if item.get("tipo") == "alternativa":
            nombre = item["alternativa"].strip()
            etiqueta = (
                f"{item['decision_id'].strip()} · {nombre}"
                if len(alternativas[nombre]) > 1
                else nombre
            )
            preferencias[modelo][etiqueta].append(delta)

    return [
        {
            "modelo": modelo,
            "puntaje_medio": fmean(puntuaciones[modelo]),
            "desviacion_vs_mediana_grupo": fmean(desviaciones[modelo]),
            "preferencias": {
                etiqueta: fmean(valores)
                for etiqueta, valores in sorted(preferencias[modelo].items())
            },
        }
        for modelo in sorted(puntuaciones)
    ]
