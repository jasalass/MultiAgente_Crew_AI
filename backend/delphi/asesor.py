"""Asesor normativo: agente con herramientas de consulta, memoria y escritura (IL2.1 a IL2.3).

Corre ANTES de la ronda 1, en un Crew secuencial propio (como 3-multiagent_crewai_full.py):
decide si el proyecto trata datos personales, consulta la Ley 21.719 (RAG de la Evaluación
Parcial 1), busca análisis anteriores parecidos (memoria de largo plazo) y escribe una ficha de
contexto con citas. La ficha llega igual a todo el panel y se escribe antes de que nadie opine:
es material de referencia, no la opinión de otro experto, así que no rompe la independencia.

Las herramientas son BaseTool con estado, como SimulatedEmailTool de la clase: registran cada
uso para mostrar en vivo y en el informe qué consultó el agente y con qué resultado.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from backend.delphi.conocimiento import BaseConocimiento

MAX_ITER_ASESOR = 8
LARGO_FRAGMENTO = 700


def _resumen_proyecto(proyecto: Any) -> str:
    datos = proyecto.model_dump() if hasattr(proyecto, "model_dump") else dict(proyecto)
    datos.pop("texto_original", None)
    return json.dumps(datos, ensure_ascii=False, separators=(",", ":"))


# --- Herramientas --------------------------------------------------------------------
from crewai.tools import BaseTool  # noqa: E402  (CrewAI es obligatorio para el motor real)


# Esquemas: todos los parámetros son obligatorios y hay al menos dos. CrewAI declara las herramientas en
# modo estricto (un parámetro opcional que el modelo omite hace que Groq rechace la llamada) y, con un
# único parámetro, gpt-oss tiende a mandar texto suelto en vez de un objeto JSON. El `motivo` además deja
# trazado por qué el agente decidió usar cada herramienta.
MOTIVO = Field(description="En una frase, por qué haces esta consulta para ESTE proyecto.")


class ConsultaLeyInput(BaseModel):
    pregunta: str = Field(description="Qué se quiere saber de la ley, en lenguaje natural "
                                      "(p. ej. 'requisitos para tratar datos de salud').")
    motivo: str = MOTIVO


class ConsultarLeyTool(BaseTool):
    name: str = "consultar_ley_21719"
    description: str = ("Busca en la Ley 21.719 de protección de datos personales (Chile) los artículos más "
                        "relacionados con una pregunta. Devuelve fragmentos con su cita para referenciarlos.")
    args_schema: type[BaseModel] = ConsultaLeyInput
    _base: BaseConocimiento = PrivateAttr()
    _registro: list = PrivateAttr()

    def __init__(self, base: BaseConocimiento, registro: list, **datos):
        super().__init__(**datos)
        self._base, self._registro = base, registro

    def _run(self, pregunta: str, motivo: str = "") -> str:
        resultados = self._base.consultar_ley(pregunta)
        self._registro.append({"herramienta": self.name, "entrada": pregunta, "motivo": motivo,
                               "resultados": [d["cita"] for _, d, _ in resultados],
                               "modo": resultados[0][2] if resultados else "sin resultados"})
        if not resultados:
            return "No se encontraron artículos relacionados."
        return "\n\n".join(f"[{d['cita']}] (relevancia {s:.2f})\n{d['texto'][:LARGO_FRAGMENTO]}"
                           for s, d, _ in resultados)


class BusquedaMemoriaInput(BaseModel):
    descripcion: str = Field(description="Descripción breve del proyecto actual para encontrar análisis parecidos.")
    motivo: str = MOTIVO


class BuscarAnalisisAnterioresTool(BaseTool):
    name: str = "buscar_analisis_anteriores"
    description: str = ("Busca en la memoria institucional los análisis Delphi ya terminados más parecidos al "
                        "proyecto actual: su veredicto de viabilidad, decisiones y riesgos principales.")
    args_schema: type[BaseModel] = BusquedaMemoriaInput
    _base: BaseConocimiento = PrivateAttr()
    _registro: list = PrivateAttr()
    _excluir: str | None = PrivateAttr(default=None)

    def __init__(self, base: BaseConocimiento, registro: list, excluir_run: str | None = None, **datos):
        super().__init__(**datos)
        self._base, self._registro, self._excluir = base, registro, excluir_run

    def _run(self, descripcion: str, motivo: str = "") -> str:
        resultados = self._base.buscar_analisis(descripcion, excluir_run=self._excluir)
        self._registro.append({"herramienta": self.name, "entrada": descripcion, "motivo": motivo,
                               "resultados": [d["proyecto"] for _, d, _ in resultados],
                               "modo": resultados[0][2] if resultados else "sin resultados"})
        if not resultados:
            return "La memoria no tiene análisis anteriores parecidos."
        return "\n\n".join(f"Análisis anterior «{d['proyecto']}» (similitud {s:.2f}). Veredicto: {d['veredicto']}. "
                           f"Decisiones: {'; '.join(d['decisiones'])}. Riesgos: {'; '.join(d['riesgos'])}."
                           for s, d, _ in resultados)


class FichaInput(BaseModel):
    trata_datos_personales: str = Field(description="'sí' o 'no', y en pocas palabras cuáles datos y si son sensibles.")
    contenido: str = Field(description="La ficha de contexto completa, en Markdown, con las citas de artículos.")


class GuardarFichaTool(BaseTool):
    name: str = "guardar_ficha"
    description: str = ("Guarda la ficha de contexto final que recibirá todo el panel. Úsala una sola vez, al "
                        "terminar, con la ficha completa en Markdown.")
    args_schema: type[BaseModel] = FichaInput
    _registro: list = PrivateAttr()
    _destino: Path | None = PrivateAttr(default=None)
    ficha: str = ""

    def __init__(self, registro: list, destino: Path | None = None, **datos):
        super().__init__(**datos)
        self._registro, self._destino = registro, destino

    def _run(self, contenido: str, trata_datos_personales: str = "") -> str:
        self.ficha = contenido.strip()
        if self._destino is not None:
            self._destino.parent.mkdir(parents=True, exist_ok=True)
            self._destino.write_text(self.ficha + "\n", encoding="utf-8")
        self._registro.append({"herramienta": self.name, "entrada": f"{len(self.ficha)} caracteres",
                               "motivo": f"¿Trata datos personales? {trata_datos_personales}".strip(),
                               "resultados": [str(self._destino.name) if self._destino else "en memoria"],
                               "modo": "escritura"})
        return f"Ficha guardada ({len(self.ficha)} caracteres)."


# --- Agente y Crew -------------------------------------------------------------------

INVESTIGAR = """Investiga el contexto legal y la experiencia previa para este proyecto, que evaluará un panel Delphi de expertos de TI.

PROYECTO:
{proyecto}

PLAN (decide tú qué consultas hacer; adapta el plan al proyecto):
1. Decide si el proyecto trata datos personales (de clientes, pacientes, empleados, usuarios...) y si alguno es sensible (salud, financieros, biométricos, de menores).
2. Si trata datos personales, usa consultar_ley_21719 de 2 a 4 veces, con preguntas específicas a ESTE proyecto (por ejemplo: datos sensibles de salud, consentimiento, medidas de seguridad, transferencia internacional a la nube, sanciones). Si no trata datos personales, haz a lo sumo una consulta para confirmarlo.
3. Usa buscar_analisis_anteriores una vez para encontrar proyectos parecidos ya analizados.

REGLAS: no inventes. Copia cada cita exactamente como la entrega la herramienta, entre corchetes. Si una herramienta falla o no devuelve nada, anótalo así. Menciona análisis anteriores solo si buscar_analisis_anteriores los devolvió."""

REDACTAR = """Con las notas de la investigación anterior, redacta la FICHA DE CONTEXTO para el panel y guárdala con guardar_ficha (es obligatorio: tu trabajo consiste en llamar a esa herramienta).

Secciones de la ficha, en Markdown:
## ¿Trata datos personales?  (sí/no, cuáles y si son sensibles)
## Obligaciones legales relevantes  (cada una con su cita exacta entre corchetes, tal como aparece en las notas)
## Lecciones de análisis anteriores  (solo las que aparecen en las notas; si no hay, "No hay análisis parecidos")
## Puntos que el panel debería considerar  (preguntas abiertas, sin recomendar alternativas técnicas)

REGLAS: usa solo lo que está en las notas; no agregues artículos ni análisis. Sé neutral. Máximo 350 palabras."""


def crear_asesor(llm: Any, herramientas: list) -> Any:
    """Investigador normativo: consulta la ley y la memoria institucional."""
    from crewai import Agent
    return Agent(
        role="Investigador normativo y de memoria institucional",
        goal="Reunir el contexto legal y la experiencia previa relevante para el proyecto, con citas verificables.",
        backstory=("Eres analista de cumplimiento y gestión del conocimiento. Conoces la Ley 21.719 de protección de "
                   "datos personales y llevas el registro de los análisis anteriores del comité. No opinas sobre "
                   "tecnologías: reúnes contexto verificable para que los expertos decidan."),
        llm=llm, tools=herramientas, allow_delegation=False, max_iter=MAX_ITER_ASESOR, memory=False, verbose=False,
    )


def crear_redactor(llm: Any, herramientas: list) -> Any:
    """Redactor de la ficha: la escribe a partir de las notas y la guarda con su herramienta."""
    from crewai import Agent
    return Agent(
        role="Redactor de la ficha de contexto",
        goal="Escribir una ficha breve, neutral y con citas exactas, y guardarla para el panel.",
        backstory=("Eres editor técnico. Transformas notas de investigación en una ficha clara para un comité de "
                   "expertos, sin agregar nada que no esté en las notas."),
        llm=llm, tools=herramientas, allow_delegation=False, max_iter=4, memory=False, verbose=False,
    )


def preparar_ficha(proyecto: Any, llm: Any, base: BaseConocimiento, destino: Path | None = None,
                   run_id: str | None = None, llm_redactor: Any | None = None) -> dict:
    """Crew secuencial de dos agentes (como 3-multiagent_crewai_full.py): investigar → redactar y guardar.

    La segunda tarea recibe la primera con context=[investigar]. `llm_redactor` permite usar otra key
    para el Redactor (Groq limita tokens por minuto). Devuelve {"ficha", "consultas", "advertencias"}.
    """
    from crewai import Crew, Process, Task
    registro: list[dict] = []
    guardar = GuardarFichaTool(registro, destino)
    investigador = crear_asesor(llm, [ConsultarLeyTool(base, registro),
                                      BuscarAnalisisAnterioresTool(base, registro, run_id)])
    redactor = crear_redactor(llm_redactor or llm, [guardar])
    investigar = Task(description=INVESTIGAR.format(proyecto=_resumen_proyecto(proyecto)),
                      expected_output=("Notas: si trata datos personales y cuáles; las obligaciones legales con su "
                                       "cita exacta; los análisis anteriores encontrados (o 'ninguno')."),
                      agent=investigador)
    redactar = Task(description=REDACTAR, context=[investigar], agent=redactor,
                    expected_output="Confirmación de que la ficha quedó guardada con guardar_ficha.")
    Crew(agents=[investigador, redactor], tasks=[investigar, redactar], process=Process.sequential,
         memory=False, verbose=False).kickoff()
    ficha = guardar.ficha or (redactar.output.raw if redactar.output else "")   # si no la guardó, su respuesta
    ficha, advertencias = verificar_ficha(ficha.strip(), registro)
    return {"ficha": ficha, "consultas": registro, "advertencias": advertencias}


def _numero_articulo(texto: str) -> str:
    """'16 bis' / '16bis' / '16' -> forma comparable."""
    return re.sub(r"\s+", " ", texto.strip().lower())


def _normalizar_cita(texto: str) -> str:
    """Sin caracteres invisibles ni espacios especiales: los LLM a veces escriben \\u202f o \\u200b en las citas."""
    texto = unicodedata.normalize("NFKC", texto).replace("​", "").replace("⁠", "")
    return re.sub(r"[ \t]+", " ", texto)


def verificar_ficha(ficha: str, registro: list[dict]) -> tuple[str, list[str]]:
    """Control anti-alucinación hecho por código, no por el LLM.

    - Toda cita entre corchetes debe estar entre las que devolvió consultar_ley_21719.
    - Si no se consultó la memoria, la ficha no puede presentar "lecciones" como reales.
    - Si no se guardó con guardar_ficha, se avisa (la ficha es la respuesta final del agente).
    Lo que no se puede verificar se marca en la propia ficha y vuelve como advertencia.
    """
    validas = {_normalizar_cita(c) for r in registro if r["herramienta"] == "consultar_ley_21719"
               for c in r["resultados"]}
    articulos_validos = {_numero_articulo(m) for v in validas for m in re.findall(r"art\. ([0-9]+(?: [a-z]+)?)", v)}
    advertencias, inventadas = [], []
    for cita_ficha in dict.fromkeys(re.findall(r"\[([^\[\]]+)\]", _normalizar_cita(ficha))):
        if not re.search(r"(?i)\b(ley|art)", cita_ficha):
            continue                                           # corchetes que no son citas legales
        # Vale si es la cita devuelta (el modelo suele recortar "…, texto según la Ley 21.719") …
        if any(v.startswith(cita_ficha.strip().rstrip(" .,")) for v in validas):
            continue
        # … o si todos los artículos que nombra, en cualquier formato, fueron devueltos por la búsqueda.
        numeros = [_numero_articulo(" ".join(p for p in m if p)) for m in
                   re.findall(r"(?i)art(?:[íi]culo|\.)?\s*([0-9]+)\s*[°º]?\s*(bis|ter|quater|quinquies|sexies)?", cita_ficha)]
        if numeros and all(n in articulos_validos for n in numeros):
            continue
        inventadas.append(cita_ficha.strip()[:90])
    if inventadas:
        advertencias.append(f"{len(inventadas)} cita(s) de la ficha no vienen de la búsqueda en la ley: "
                            + "; ".join(inventadas[:3]))
    if not any(r["herramienta"] == "consultar_ley_21719" for r in registro):
        advertencias.append("El Asesor no consultó la ley: las obligaciones legales de la ficha no están verificadas.")
    if not any(r["herramienta"] == "buscar_analisis_anteriores" for r in registro) and "análisis" in ficha.lower():
        advertencias.append("El Asesor no consultó la memoria: las lecciones de análisis anteriores no están verificadas.")
    if not any(r["herramienta"] == "guardar_ficha" for r in registro):
        advertencias.append("El Asesor no guardó la ficha con su herramienta; se usó su respuesta final.")
    if advertencias:
        ficha += "\n\n> ⚠️ **Verificación automática:** " + " ".join(advertencias)
    return ficha, advertencias


def asesor_simulado(base: BaseConocimiento) -> Callable[[Any, str], dict]:
    """Sin LLM: consultas fijas sobre el índice real (por palabras si no hay embeddings). Para demo y tests."""
    def preparar(proyecto: Any, run_id: str) -> dict:
        registro: list[dict] = []
        ley = ConsultarLeyTool(base, registro)._run("tratamiento de datos personales sensibles y medidas de seguridad")
        memoria = BuscarAnalisisAnterioresTool(base, registro, run_id)._run(
            proyecto.objetivo if hasattr(proyecto, "objetivo") else str(proyecto))
        citas = registro[0]["resultados"][:3]
        ficha = ("## ¿Trata datos personales?\nFicha simulada: se asume que sí.\n\n"
                 "## Obligaciones legales relevantes\n" + "\n".join(f"- [{c}]" for c in citas) + "\n\n"
                 "## Lecciones de análisis anteriores\n" + (memoria.split("\n\n")[0] if registro[1]["resultados"]
                                                           else "No hay análisis parecidos.") + "\n\n"
                 "## Puntos que el panel debería considerar\n- ¿Dónde se guardan los datos personales y quién accede?")
        GuardarFichaTool(registro)._run(ficha)
        return {"ficha": ficha, "consultas": registro}
    return preparar
