"""Asignación de modelos a expertos con rotación y restricción de roles afines.

Provisional: la regla vive en ModelPool (Juan, README §3). Aquí es una función pura
para poder probarla y reutilizarla.

  - Reparto equilibrado: cada paso elige el modelo menos usado.
  - Roles afines (README §1.5) nunca comparten modelo: Arquitectura–Desarrollo,
    Cloud–DevOps y Seguridad–Datos (si hay al menos 2 modelos).
  - `rotacion` desplaza el orden de preferencia: ejecuciones distintas dan asignaciones
    distintas, así el sesgo del rol no queda atado siempre al mismo modelo.
"""
from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")

AFINES = (("arquitectura", "desarrollo"), ("cloud", "devops"), ("seguridad", "datos"))
_PAREJA = {a: b for a, b in AFINES} | {b: a for a, b in AFINES}


def asignar_modelos(expertos: list[str], modelos: list[T], rotacion: int = 0) -> dict[str, T]:
    if not modelos:
        raise ValueError("Se necesita al menos un modelo")
    m = len(modelos)
    orden = [(rotacion + k) % m for k in range(m)]          # preferencia rotada (índices)
    usos = [0] * m
    elegido: dict[str, int] = {}
    for experto in expertos:
        prohibido = elegido.get(_PAREJA.get(experto, ""), None) if m > 1 else None
        candidatos = [i for i in orden if i != prohibido]
        mejor = min(candidatos, key=lambda i: (usos[i], orden.index(i)))
        elegido[experto] = mejor
        usos[mejor] += 1
    return {e: modelos[i] for e, i in elegido.items()}
