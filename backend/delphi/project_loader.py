"""Plantilla de proyecto (README §1.6) en Markdown -> Proyecto.

Las secciones se reconocen por el inicio del título, sin tildes ni mayúsculas, así que
"## Decisiones a evaluar (opc.)" y "## Objetivo" también valen. Las secciones de lista
toman un elemento por línea (con o sin viñeta). Los comentarios <!-- --> se ignoran:
la plantilla los usa para las instrucciones de cada sección.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from backend.delphi.models import Proyecto

SECCIONES = (("objetivo", "objetivo"), ("contexto", "objetivo"), ("usuarios", "usuarios_volumen"),
             ("requisitos funcionales", "requisitos_funcionales"),
             ("requisitos no funcionales", "requisitos_no_funcionales"),
             ("restricciones", "restricciones"), ("equipo", "equipo"),
             ("integraciones", "integraciones"), ("decisiones", "decisiones_a_evaluar"))
LISTAS = {"requisitos_funcionales", "requisitos_no_funcionales", "restricciones", "integraciones",
          "decisiones_a_evaluar"}
_VINETA = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).strip()


def parsear_markdown(texto: str, nombre_por_defecto: str = "Proyecto") -> Proyecto:
    """Convierte el Markdown de la plantilla en Proyecto; exige el objetivo."""
    limpio = re.sub(r"<!--.*?-->", "", texto, flags=re.DOTALL)
    campos: dict[str, list[str]] = {}
    nombre = nombre_por_defecto
    actual: str | None = None
    for linea in limpio.splitlines():
        if re.match(r"^#\s+", linea):
            nombre = linea.lstrip("#").strip() or nombre
        elif re.match(r"^#{2,6}\s+", linea):
            titulo = _normalizar(linea.lstrip("#"))
            actual = next((campo for prefijo, campo in SECCIONES if titulo.startswith(prefijo)), None)
        elif actual and (valor := _VINETA.sub("", linea).strip()) and valor not in "-*+":
            campos.setdefault(actual, []).append(valor)
    datos: dict = {"nombre": nombre, "texto_original": texto}
    for campo, lineas in campos.items():
        datos[campo] = lineas if campo in LISTAS else "\n".join(lineas)
    if not datos.get("objetivo", "").strip():
        raise ValueError("El proyecto debe incluir la sección «Objetivo y contexto» con contenido.")
    return Proyecto(**datos)


def cargar_proyecto(ruta: Path) -> Proyecto:
    return parsear_markdown(Path(ruta).read_text(encoding="utf-8-sig"), Path(ruta).stem)
