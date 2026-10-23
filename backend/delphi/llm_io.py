"""Extracción y validación de JSON de un LLM, con un reintento (README §4.3).

Lo usan los expertos (engine.py) y el Moderador (cuestionario, continuar, riesgos).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def extraer_json(texto: str) -> str:
    """Quita el razonamiento (<think> o <thought>, según el modelo) y las cercas ```.

    Devuelve el primer objeto JSON balanceado.
    """
    texto = re.sub(r"<(think|thought)>.*?</\1>", "", texto, flags=re.DOTALL)
    texto = re.sub(r"```(?:json)?", "", texto)
    inicio = texto.find("{")
    if inicio < 0:
        raise ValueError("La respuesta no contiene un objeto JSON")
    profundidad, en_cadena, escape = 0, False, False
    for i in range(inicio, len(texto)):
        c = texto[i]
        if en_cadena:
            if escape:                       # el carácter anterior fue \: este no cuenta
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                en_cadena = False
        elif c == '"':
            en_cadena = True
        elif c == "{":
            profundidad += 1
        elif c == "}":
            profundidad -= 1
            if profundidad == 0:
                return texto[inicio:i + 1]
    raise ValueError("JSON incompleto en la respuesta")


def validar(texto: str, modelo: type[T]) -> T:
    return modelo.model_validate(json.loads(extraer_json(texto)))


def llamar_y_validar(llamar: Callable[[str], str], prompt: str, modelo: type[T]) -> T:
    """Llama al LLM; si el JSON no valida, reintenta UNA vez incluyendo el error."""
    texto = llamar(prompt)
    try:
        return validar(texto, modelo)
    except (ValueError, ValidationError) as error:
        texto = llamar(f"{prompt}\n\nTu respuesta anterior no fue válida: {error}\n"
                       "Corrígela y responde SOLO el JSON.")
        return validar(texto, modelo)
