"""Síntesis temática sin retransmitir texto identificable de los expertos.

No hay una expresión regular capaz de eliminar toda huella de un modelo. Por
eso esta implementación conservadora no devuelve citas ni paráfrasis libres:
proyecta justificaciones a un vocabulario técnico cerrado, agrupa por ítem y
postura (4–5 a favor, 1–2 en contra) y utiliza siempre las mismas plantillas.
Las valoraciones 3 son intermedias y no se presentan como apoyo ni rechazo.

Esto conserva temas y frecuencia, pero pierde matices, condiciones, cifras y
temas no reconocidos. No prueba anonimato estadístico: un panel pequeño o una
postura singular puede permitir inferencias. Los originales quedan en la
trazabilidad privada del motor, nunca en el feedback de esta herramienta.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import json
import re
import unicodedata
from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    elif hasattr(value, "dict") and callable(value.dict):
        value = value.dict()
    if not isinstance(value, Mapping):
        raise ValueError("Se esperaba un objeto de datos")
    return dict(value)


def _normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto.lower())
                   if not unicodedata.combining(c))


# No se copia ningún token del input a la prosa generada. Añadir un tema exige
# revisar tanto la detección como la etiqueta neutral que verán los expertos.
_TEMAS = (
    ("costo y presupuesto", r"\b(cost\w*|presupuest\w*|finops|tco|barat\w*|caro|cara)\b"),
    ("plazo y alcance de entrega", r"\b(plazo\w*|alcance|entrega\w*|meses|semanas|tiempo)\b"),
    ("experiencia y capacidad del equipo", r"\b(equipo|junior\w*|seniority|experiencia|capacidad del equipo)\b"),
    ("mantenibilidad y deuda técnica", r"\b(manten\w*|deuda|evolucion\w*|legib\w*)\b"),
    ("acoplamiento y límites de módulos", r"\b(acoplam\w*|modul\w*|responsabilidad\w*|dependencia\w*)\b"),
    ("distribución y coordinación de servicios", r"\b(microserv\w*|distribuid\w*|eventos|monolit\w*|serverless)\b"),
    ("escala y volumen", r"\b(escal\w*|volumen\w*|concurren\w*|crecimiento|carga)\b"),
    ("latencia y rendimiento", r"\b(latencia|rendimiento|performance|respuesta rapida|lent\w*)\b"),
    ("disponibilidad y continuidad", r"\b(disponib\w*|continuidad|caida\w*|slo|sla|confiab\w*)\b"),
    ("recuperación y respaldo", r"\b(recuper\w*|respaldo\w*|backup\w*|restaur\w*|desastre\w*|rto|rpo)\b"),
    ("operación y observabilidad", r"\b(oper\w*|observab\w*|monitoreo|alerta\w*|traza\w*|metricas)\b"),
    ("automatización y despliegue", r"\b(automat\w*|desplieg\w*|cicd|ci/cd|contenedor\w*|iac|rollback)\b"),
    ("seguridad y superficie de ataque", r"\b(seguridad|ataque\w*|vulnerab\w*|owasp|amenaza\w*)\b"),
    ("identidad y control de acceso", r"\b(autentic\w*|autoriz\w*|permiso\w*|acceso\w*|privilegio\w*|identidad)\b"),
    ("privacidad y protección de datos", r"\b(privacidad|personal\w*|cifrad\w*|sensibl\w*|proteccion)\b"),
    ("cumplimiento y residencia de datos", r"\b(cumplim\w*|normativ\w*|ley|regul\w*|residencia|region\w*)\b"),
    ("integridad y consistencia de datos", r"\b(integridad|consistencia|transacci\w*|invariante\w*|acid)\b"),
    ("almacenamiento y consultas", r"\b(sql|nosql|almacen\w*|base de datos|consult\w*|esquema\w*)\b"),
    ("migración e integración", r"\b(migr\w*|integr\w*|legad\w*|api\w*|etl)\b"),
    ("dependencia del proveedor", r"\b(proveedor\w*|lock-in|lock in|portabilidad|vendor)\b"),
    ("servicios gestionados", r"\b(gestionad\w*|paas|iaas)\b"),
    ("pruebas y criterios de aceptación", r"\b(prueba\w*|testing|regresion|aceptacion|cobertura|calidad)\b"),
    ("usabilidad y flujos de usuario", r"\b(usab\w*|usuario\w*|flujo\w*|interfaz|mobile|movil)\b"),
    ("accesibilidad", r"\b(accesib\w*|wcag|lector de pantalla|teclado)\b"),
    ("evaluación y confiabilidad de IA", r"\b(ia|llm\w*|alucin\w*|inferencia|modelo\w*|entrenamiento|rag|predic\w*)\b"),
)
_GENERICO = "adecuación global al proyecto; detalle fuera del vocabulario de síntesis"


def resumir_argumentos(textos: list[str], postura: str) -> list[str]:
    """Resume temas, sin atribuir ventajas concretas que el texto no demuestra.

    ``postura`` es ``favor`` o ``contra`` y debe provenir del puntaje; mencionar
    seguridad con puntaje 5 no permite inferir que el sistema ya sea seguro.
    """
    if postura not in {"favor", "contra"}:
        raise ValueError("La postura debe ser favor o contra")
    cuenta: Counter[str] = Counter()
    for texto in textos:
        if not isinstance(texto, str):
            raise ValueError("Las justificaciones deben ser texto")
        normalizado = _normalizar(texto)
        temas = [tema for tema, patron in _TEMAS if re.search(patron, normalizado)]
        cuenta.update(temas or [_GENERICO])
    prefijo = "Valoración favorable" if postura == "favor" else "Valoración desfavorable"
    # Orden lexical estable: la salida no depende del orden de los expertos.
    return [f"{prefijo}: {tema} ({cantidad} menciones)." for tema, cantidad in sorted(cuenta.items())]


def sanear_argumentos(textos: list[str], postura: str) -> list[str]:
    """Conserva síntesis cerradas ya generadas y resume cualquier prosa libre.

    Útil al construir feedback: una segunda pasada no pierde las frecuencias
    ya calculadas. No valida que esas frecuencias coincidan con la auditoría;
    esa comprobación corresponde al motor que conserva las respuestas.
    """
    if postura not in {"favor", "contra"}:
        raise ValueError("La postura debe ser favor o contra")
    prefijo = "Valoración favorable" if postura == "favor" else "Valoración desfavorable"
    permitidos = {tema for tema, _ in _TEMAS} | {_GENERICO}
    cerrados, libres = [], []
    for texto in textos:
        if not isinstance(texto, str):
            raise ValueError("Los argumentos deben ser texto")
        coincidencia = re.fullmatch(re.escape(prefijo) + r": (.+) \(([1-9][0-9]*) menciones\)\.", texto)
        if coincidencia and coincidencia[1] in permitidos:
            cerrados.append(texto)
        else:
            libres.append(texto)
    return sorted(set(cerrados + resumir_argumentos(libres, postura)))


def _validar_item_id(item_id: Any) -> str:
    # Identificadores estructurales, no un canal libre para nombres o modelos.
    # El contrato Item.id es str y los LLM pueden numerar con cero inicial o
    # usar sufijos en mayúsculas. Esas variantes ya atraviesan models/engine y
    # se conservan exactamente para unir estadísticas; no son prosa libre.
    if not isinstance(item_id, str) or not re.fullmatch(r"[A-Z]{2,12}-[ED][0-9]+(?:-[A-Za-z0-9]+)?", item_id):
        raise ValueError("item_id no cumple el formato del cuestionario (p. ej. ARQ-E1)")
    return item_id


def sintetizar_argumentos(respuestas: list[Any], cuestionario: Any = None) -> list[dict[str, Any]]:
    """Agrupa RespuestaExperto de UNA ronda por ítem (también alternativas).

    El llamador conserva mediana/Q1/Q3/IQR en stats.py y une ambas salidas por
    item_id. Si entrega cuestionario, se valida la pertenencia de cada ítem y
    también se incluyen los ítems aún sin respuestas con listas vacías.
    """
    if not isinstance(respuestas, (list, tuple)):
        raise ValueError("respuestas debe ser una lista")
    grupos: dict[str, dict[str, list[str]]] = {}
    if cuestionario is not None:
        items = _dict(cuestionario).get("items", [])
        for item in items:
            item_id = _validar_item_id(_dict(item).get("id"))
            if item_id in grupos:
                raise ValueError("El cuestionario tiene ítems duplicados")
            grupos[item_id] = {"favor": [], "contra": []}
    rondas = set()
    identidades = set()
    for valor in respuestas:
        respuesta = _dict(valor)
        if respuesta.get("ronda") is not None:
            rondas.add(respuesta["ronda"])
        identidad = respuesta.get("experto_id")
        if identidad is not None:
            if identidad in identidades:
                raise ValueError("Hay respuestas duplicadas del mismo experto")
            identidades.add(identidad)
        vistos = set()
        for valor_item in respuesta.get("respuestas", []):
            item = _dict(valor_item)
            item_id = _validar_item_id(item.get("item_id"))
            if item_id in vistos:
                raise ValueError("Hay una respuesta duplicada para el mismo ítem")
            vistos.add(item_id)
            if cuestionario is not None and item_id not in grupos:
                raise ValueError("La respuesta contiene un ítem fuera del cuestionario")
            puntaje = item.get("puntaje")
            if type(puntaje) is not int or not 1 <= puntaje <= 5:
                raise ValueError("El puntaje debe ser un entero entre 1 y 5")
            justificacion = item.get("justificacion")
            if not isinstance(justificacion, str) or not justificacion.strip():
                raise ValueError("Cada respuesta requiere una justificación")
            grupo = grupos.setdefault(item_id, {"favor": [], "contra": []})
            if puntaje >= 4:
                grupo["favor"].append(justificacion)
            elif puntaje <= 2:
                grupo["contra"].append(justificacion)
    if len(rondas) > 1:
        raise ValueError("El feedback debe resumir una sola ronda")
    return [{"item_id": item_id,
             "argumentos_a_favor": resumir_argumentos(grupos[item_id]["favor"], "favor"),
             "argumentos_en_contra": resumir_argumentos(grupos[item_id]["contra"], "contra")}
            for item_id in sorted(grupos)]


def _ejecutar(respuestas: list[Any], cuestionario: Any = None) -> str:
    return json.dumps(sintetizar_argumentos(respuestas, cuestionario), ensure_ascii=False)


# La demo y las funciones puras no requieren CrewAI ni Pydantic. Con CrewAI
# instalado se expone un BaseTool real según su API pública, con args_schema.
try:
    from crewai.tools import BaseTool
except ModuleNotFoundError as error:
    if error.name != "crewai":
        raise

    class AnonymizerTool:
        """Adaptador local para la demo; instalar CrewAI para usarlo en un Crew."""

        name = "anonimizar_argumentos"
        description = "Agrupa argumentos por ítem mediante síntesis temática sin autores ni modelos."

        def run(self, respuestas: list[Any], cuestionario: Any = None) -> str:
            return _ejecutar(respuestas, cuestionario)

        def _run(self, respuestas: list[Any], cuestionario: Any = None) -> str:
            return _ejecutar(respuestas, cuestionario)
else:
    from pydantic import BaseModel, Field

    class AnonymizerInput(BaseModel):
        respuestas: list[dict[str, Any]] = Field(description="Respuestas de los expertos de una sola ronda")
        cuestionario: dict[str, Any] | None = Field(default=None, description="Cuestionario para validar los ítems")

    class AnonymizerTool(BaseTool):
        name: str = "anonimizar_argumentos"
        description: str = "Agrupa argumentos por ítem mediante síntesis temática sin autores ni modelos."
        args_schema: type[BaseModel] = AnonymizerInput

        def _run(self, respuestas: list[dict[str, Any]], cuestionario: dict[str, Any] | None = None) -> str:
            return _ejecutar(respuestas, cuestionario)
