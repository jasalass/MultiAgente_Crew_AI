"""Estadística Delphi: funciones puras, sin LLM (README §1.2 y §1.5).

Mediana, cuartiles, IQR, consenso por ítem y global, estabilidad entre rondas y
la regla de recomendación firme / condicionada / abierta. tools.py, engine.py y
decisiones.py se apoyan en estas funciones para que los números sean reproducibles.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from statistics import median, quantiles
from typing import Literal

UMBRAL_IQR = 1.0            # consenso por ítem: IQR <= 1
UMBRAL_ESTABILIDAD = 0.5    # estabilidad: ninguna mediana se mueve 0,5 o más entre rondas

EstadoDecision = Literal["firme", "condicionada", "abierta"]
Veredicto = Literal["viable", "viable_con_condiciones", "no_viable", "en_discusion"]


def mediana(valores: list[float]) -> float:
    return float(median(valores))


def cuartiles(valores: list[float]) -> tuple[float, float]:
    """(Q1, Q3) por interpolación lineal inclusiva (igual que numpy por defecto)."""
    if len(valores) < 2:
        return float(valores[0]), float(valores[0])
    q1, _, q3 = quantiles(valores, n=4, method="inclusive")
    return float(q1), float(q3)


def iqr(valores: list[float]) -> float:
    q1, q3 = cuartiles(valores)
    return q3 - q1


def hay_consenso(valores: list[float], umbral_iqr: float = UMBRAL_IQR) -> bool:
    return iqr(valores) <= umbral_iqr


def porcentaje_consenso(consensos: Iterable[bool]) -> float:
    """Fracción (0-1) de ítems con consenso; se compara con umbral_consenso_global."""
    consensos = list(consensos)
    return sum(consensos) / len(consensos) if consensos else 0.0


def es_estable(actual: Mapping[str, float], previa: Mapping[str, float] | None,
               umbral: float = UMBRAL_ESTABILIDAD) -> bool:
    """True si ninguna mediana (item_id -> mediana) se movió `umbral` o más desde la ronda anterior."""
    if not previa:
        return False
    return all(abs(m - previa[i]) < umbral for i, m in actual.items() if i in previa)


def estado_decision(consenso: bool, mediana_mejor: float, margen: float) -> EstadoDecision:
    """Regla de recomendación de la mejor alternativa de una decisión.

    firme:        consenso, mediana >= 4 y supera en >= 1 punto a la segunda.
    condicionada: consenso, pero margen < 1 o mediana entre 3 y 4.
    abierta:      sin consenso, o consenso en una mediana < 3 (ninguna alternativa es adecuada).
    """
    if consenso and mediana_mejor >= 4 and margen >= 1:
        return "firme"
    if consenso and mediana_mejor >= 3:
        return "condicionada"
    return "abierta"


def veredicto_viabilidad(consenso: bool, mediana_final: float) -> Veredicto:
    """Viabilidad global del proyecto tal como está planteado (ítem VIA-E1, escala 1-5).

    en_discusion:           el panel no llegó a consenso.
    viable:                 consenso y mediana >= 4.
    viable_con_condiciones: consenso y mediana entre 3 y 4.
    no_viable:              consenso y mediana < 3.
    """
    if not consenso:
        return "en_discusion"
    if mediana_final >= 4:
        return "viable"
    if mediana_final >= 3:
        return "viable_con_condiciones"
    return "no_viable"
