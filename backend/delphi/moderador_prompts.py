"""Prompts del Moderador Delphi (README §5, Pamela).

Tres momentos en los que el Moderador usa un LLM:
  1. Cuestionario: identificar las decisiones clave y generar los ítems.
  2. Feedback de ronda: explicar al panel, en lenguaje neutro, dónde hay
     acuerdo y desacuerdo.
  3. Propuesta de continuar: opinar si conviene otra ronda.

El LLM solo PROPONE. Los números los calcula tools.py y los límites de rondas
los impone engine.py. El feedback nunca incluye roles, autores ni modelos.
"""
from __future__ import annotations

import json
from typing import Any

DIMENSIONES = ("arquitectura", "infraestructura", "stack", "datos",
               "seguridad", "calidad", "operacion", "gestion")

ROLE = "Moderador Delphi"
GOAL = ("Conducir un panel anónimo de expertos de TI hacia decisiones de proyecto "
        "bien fundamentadas, sin opinar sobre el fondo ni revelar quién dijo qué.")
BACKSTORY = ("Facilitas paneles Delphi. Eres neutral: no tienes preferencia por ninguna "
             "tecnología. Tu trabajo es estructurar preguntas, delegar a cada experto por "
             "separado y devolver al grupo un resumen anónimo. Nunca calculas estadísticas "
             "a mano: usas la herramienta de estadísticas.")


def _json(valor: Any) -> str:
    if hasattr(valor, "model_dump"):
        valor = valor.model_dump()
    return json.dumps(valor, ensure_ascii=False, indent=2)


def construir_prompt_cuestionario(proyecto: Any, min_decisiones: int = 3, max_decisiones: int = 5,
                                  min_evaluaciones: int = 6, max_evaluaciones: int = 10) -> str:
    datos = proyecto.model_dump() if hasattr(proyecto, "model_dump") else dict(proyecto)
    previas = datos.get("decisiones_a_evaluar") or []
    instruccion_previas = (
        "El equipo ya considera estas decisiones; inclúyelas SIEMPRE con sus alternativas:\n- "
        + "\n- ".join(previas)) if previas else "El equipo no indicó decisiones: identifícalas tú."
    return f"""Eres el {ROLE}. Diseña el cuestionario Delphi para este proyecto.

PROYECTO:
{_json(datos)}

{instruccion_previas}

REGLAS:
- {min_decisiones} a {max_decisiones} decisiones clave, cada una con 2 a 4 alternativas REALISTAS
  para este proyecto (no inventes opciones absurdas para rellenar).
- {min_evaluaciones} a {max_evaluaciones} ítems de evaluación (viabilidad, riesgos, plazo, etc.),
  respondibles con Likert 1-5.
- Dimensiones permitidas: {", ".join(DIMENSIONES)}.
- Cada alternativa es un ítem de tipo "alternativa" y se puntúa por su adecuación al proyecto.
- Ids: evaluación "ARQ-E1"; decisión "ARQ-D1"; alternativa "ARQ-D1-a", "ARQ-D1-b"...
  (prefijo de 3 letras de la dimensión).
- Preguntas neutrales: no sugieras la respuesta correcta.

Responde SOLO un JSON con esta forma:
{{"decisiones": [{{"id": "ARQ-D1", "dimension": "arquitectura", "titulo": "...", "alternativas": ["...", "..."]}}],
 "items": [{{"id": "ARQ-E1", "dimension": "arquitectura", "tipo": "evaluacion", "pregunta": "...",
             "decision_id": null, "alternativa": null}},
           {{"id": "ARQ-D1-a", "dimension": "arquitectura", "tipo": "alternativa", "pregunta": "...",
             "decision_id": "ARQ-D1", "alternativa": "..."}}]}}"""


def construir_prompt_feedback(ronda: int, cuestionario: Any, estadisticas: list[dict[str, Any]],
                              argumentos: list[dict[str, Any]]) -> str:
    """Redacta el feedback que verán los expertos en la ronda siguiente."""
    return f"""Eres el {ROLE}. Termina la ronda {ronda}. Redacta el feedback para el panel.

CUESTIONARIO:
{_json(cuestionario)}

ESTADÍSTICAS DE LA RONDA (calculadas por la herramienta; no las modifiques):
{_json(estadisticas)}

ARGUMENTOS ANÓNIMOS:
{_json(argumentos)}

REGLAS:
- Señala en qué ítems hay consenso (IQR <= 1) y en cuáles no, y por qué se discrepa.
- NO menciones roles, autores, modelos ni cuántos expertos opinaron cada cosa.
- NO inventes cifras: usa solo las estadísticas entregadas.
- Máximo 150 palabras. Texto plano."""


def construir_prompt_continuar(ronda: int, max_rondas: int, porcentaje_consenso: float,
                               umbral_global: float) -> str:
    return f"""Eres el {ROLE}. Ronda {ronda} de un máximo de {max_rondas}.
Consenso actual: {porcentaje_consenso:.0%} de los ítems (objetivo: {umbral_global:.0%}).
¿Recomiendas otra ronda? Tu respuesta es solo una propuesta; el sistema aplica los límites.
Responde SOLO un JSON: {{"continuar": true|false, "motivo": "una frase"}}"""
