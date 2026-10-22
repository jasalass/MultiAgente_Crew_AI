"""PROVISIONAL: mínimo de estadística que necesita tools.py.

Juan es el dueño de este módulo (README §5). Al integrar, se reemplaza por su
versión; tools.py solo usa mediana, cuartiles, iqr y hay_consenso.
Son funciones puras, sin LLM.
"""
from __future__ import annotations

from statistics import median, quantiles


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


def hay_consenso(valores: list[float], umbral_iqr: float = 1.0) -> bool:
    return iqr(valores) <= umbral_iqr
