"""Resultados del Delphi a partir de la última ronda (README §1.2 y §5, Pamela).

Funciones puras, salvo `consolidar_riesgos`, que usa al Moderador con un
respaldo determinista. La clasificación firme / condicionada / abierta la
decide el código, nunca el LLM.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from statistics import median

from pydantic import BaseModel, Field

from backend.delphi import llm_io
from backend.delphi.models import (
    Cuestionario, Decision, DecisionRecomendada, EstadisticaItem,
    RespuestaExperto, Riesgo, ResumenRonda,
)

DIMENSIONES = ("arquitectura", "infraestructura", "stack", "datos",
               "seguridad", "calidad", "operacion", "gestion")


# --- Regla de recomendación (§1.2) ---------------------------------------------------

def clasificar_decision(decision: Decision, cuestionario: Cuestionario,
                        estadisticas: dict[str, EstadisticaItem]) -> DecisionRecomendada:
    """Elige la mejor alternativa y la clasifica.

    firme:        consenso (IQR <= umbral), mediana >= 4 y supera en >= 1 a la segunda.
    condicionada: consenso, pero margen < 1 o mediana == 3.
    abierta:      sin consenso en la mejor, o consenso en una mediana <= 2 (ninguna
                  alternativa resulta adecuada): hay que resolver con una PoC o spike.
    """
    candidatas = [(i.alternativa, estadisticas[i.id]) for i in cuestionario.items
                  if i.decision_id == decision.id and i.id in estadisticas]
    if not candidatas:
        raise ValueError(f"La decisión {decision.id} no tiene alternativas con respuestas")
    # Mayor mediana; a igualdad, menor IQR (más consenso).
    candidatas.sort(key=lambda c: (-c[1].mediana, c[1].iqr))
    mejor_nombre, mejor = candidatas[0]
    margen = mejor.mediana - candidatas[1][1].mediana if len(candidatas) > 1 else mejor.mediana
    segunda = candidatas[1][0] if len(candidatas) > 1 else None

    if mejor.consenso and mejor.mediana >= 4 and margen >= 1:
        estado, condiciones, poc = "firme", [], None
    elif mejor.consenso and mejor.mediana >= 3:
        estado, poc = "condicionada", None
        condiciones = []
        if margen < 1 and segunda:
            condiciones.append(f"La ventaja sobre «{segunda}» es de {margen:g} punto(s): "
                               "revisar la decisión en un hito definido.")
        if mejor.mediana == 3:
            condiciones.append("La adecuación es solo intermedia (mediana 3): "
                               "validar los supuestos antes de comprometerse.")
    else:
        estado, condiciones = "abierta", []
        rivales = " vs ".join(f"«{n}»" for n, _ in candidatas[:2])
        poc = f"PoC o spike comparando {rivales} antes de decidir."
    return DecisionRecomendada(
        decision_id=decision.id, titulo=decision.titulo,
        alternativa_recomendada=None if estado == "abierta" else mejor_nombre,
        estado=estado, mediana=mejor.mediana, iqr=mejor.iqr, margen_vs_segunda=margen,
        condiciones=condiciones, poc_sugerida=poc)


def recomendar_decisiones(cuestionario: Cuestionario, ultima: ResumenRonda) -> list[DecisionRecomendada]:
    por_item = {e.item_id: e for e in ultima.estadisticas}
    return [clasificar_decision(d, cuestionario, por_item) for d in cuestionario.decisiones]


# --- Evaluación, disensos y recomendaciones -----------------------------------------

def evaluacion_por_dimension(cuestionario: Cuestionario, ultima: ResumenRonda) -> dict[str, float]:
    """Mediana final de los ítems de evaluación de cada dimensión."""
    por_item = {e.item_id: e.mediana for e in ultima.estadisticas}
    grupos: dict[str, list[float]] = defaultdict(list)
    for item in cuestionario.items:
        if item.tipo == "evaluacion" and item.id in por_item:
            grupos[item.dimension].append(por_item[item.id])
    return {dim: float(median(v)) for dim, v in grupos.items()}


def detectar_disensos(cuestionario: Cuestionario, ultima: ResumenRonda) -> list[str]:
    """Ítems que terminaron sin consenso, con su IQR final."""
    textos = {i.id: (f"{i.pregunta} — «{i.alternativa}»" if i.alternativa else i.pregunta)
              for i in cuestionario.items}
    return [f"{textos.get(e.item_id, e.item_id)}: sin consenso (IQR {e.iqr:g}, mediana {e.mediana:g})"
            for e in ultima.estadisticas if not e.consenso]


def generar_recomendaciones(decisiones: list[DecisionRecomendada]) -> list[str]:
    salida = []
    for d in decisiones:
        if d.estado == "firme":
            salida.append(f"Adoptar «{d.alternativa_recomendada}» para «{d.titulo}».")
        elif d.estado == "condicionada":
            salida.append(f"Adoptar «{d.alternativa_recomendada}» para «{d.titulo}» con condiciones: "
                          + " ".join(d.condiciones))
        else:
            salida.append(f"«{d.titulo}» sigue abierta. {d.poc_sugerida}")
    return salida


# --- Riesgos --------------------------------------------------------------------------

class _RiesgosLLM(BaseModel):
    riesgos: list[Riesgo] = Field(default_factory=list)


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", sin_tildes.lower()).strip()


def _riesgos_respaldo(menciones: dict[str, int]) -> list[Riesgo]:
    """Sin LLM: agrupa por texto idéntico normalizado. Probabilidad según menciones."""
    maximo = max(menciones.values(), default=1)
    return [Riesgo(descripcion=texto, dimension="gestion",
                   probabilidad=max(1, min(5, round(5 * n / maximo))), impacto=3,
                   mitigacion="Evaluar con el equipo y definir una acción de mitigación.", menciones=n)
            for texto, n in sorted(menciones.items(), key=lambda kv: -kv[1])]


def consolidar_riesgos(respuestas: list[RespuestaExperto], llamar_moderador: Callable[[str], str],
                       n_expertos: int) -> list[Riesgo]:
    """Une los riesgos duplicados de la última ronda y estima probabilidad e impacto.

    El Moderador agrupa y estima; si falla o devuelve algo inválido, se usa el
    respaldo determinista. Las `menciones` se recalculan en el código a partir
    de los textos originales: el LLM no puede inflarlas.
    """
    ultima = max((r.ronda for r in respuestas), default=0)
    textos = [t.strip() for r in respuestas if r.ronda == ultima for t in r.riesgos_detectados if t.strip()]
    if not textos:
        return []
    conteo: dict[str, int] = defaultdict(int)
    for t in textos:
        conteo[t] += 1
    prompt = (
        "Eres el Moderador Delphi. Estos son riesgos técnicos señalados por el panel (puede haber "
        "duplicados con otras palabras). Agrúpalos, y para cada grupo da una descripción, la dimensión "
        f"({', '.join(DIMENSIONES)}), probabilidad 1-5, impacto 1-5 y una mitigación concreta.\n\n"
        f"RIESGOS:\n{json.dumps(sorted(set(textos)), ensure_ascii=False, indent=2)}\n\n"
        'Responde SOLO un JSON: {"riesgos": [{"descripcion": "...", "dimension": "seguridad", '
        '"probabilidad": 3, "impacto": 4, "mitigacion": "...", "menciones": 1}]}')
    try:
        grupos = llm_io.llamar_y_validar(llamar_moderador, prompt, _RiesgosLLM).riesgos
        if not grupos:
            raise ValueError("sin riesgos")
    except Exception:
        return _riesgos_respaldo(conteo)
    # Menciones reales: cuántos textos originales comparten palabras con la descripción del grupo.
    def menciones(grupo: Riesgo) -> int:
        palabras = {w for w in _normalizar(grupo.descripcion).split() if len(w) > 3}
        return sum(1 for t in textos if palabras & {w for w in _normalizar(t).split() if len(w) > 3}) or 1
    resultado = [g.model_copy(update={"menciones": min(menciones(g), n_expertos)}) for g in grupos]
    return sorted(resultado, key=lambda r: (-r.probabilidad * r.impacto, -r.menciones))


def resumen_final(cuestionario: Cuestionario, rondas: list[ResumenRonda]):
    """Atajo para el motor: decisiones, evaluación, disensos y recomendaciones."""
    ultima = rondas[-1]
    decisiones = recomendar_decisiones(cuestionario, ultima)
    return (decisiones, evaluacion_por_dimension(cuestionario, ultima),
            detectar_disensos(cuestionario, ultima), generar_recomendaciones(decisiones))
