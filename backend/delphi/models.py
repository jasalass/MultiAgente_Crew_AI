"""Contratos de README §4.1, transcritos tal cual.

Cambiar este archivo requiere el visto bueno de los tres (README §7);
tests/test_plataforma.py comprueba que los campos coincidan con el README.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Dimension = Literal["arquitectura", "infraestructura", "stack", "datos",
                    "seguridad", "calidad", "operacion", "gestion"]

class Proyecto(BaseModel):
    nombre: str
    objetivo: str
    usuarios_volumen: str = ""
    requisitos_funcionales: list[str] = []
    requisitos_no_funcionales: list[str] = []
    restricciones: list[str] = []          # presupuesto, plazo, tecnologías obligatorias, normativa
    equipo: str = ""
    integraciones: list[str] = []
    decisiones_a_evaluar: list[str] = []   # opcional: alternativas que el equipo ya considera
    texto_original: str                    # el .md completo

class Experto(BaseModel):
    id: str                                # "arquitectura", "cloud", ...
    nombre: str
    tipo: Literal["nucleo", "opcional"]
    role: str
    goal: str
    backstory: str
    dimensiones: list[Dimension]           # en qué dimensiones opina con más peso

class ConfigRun(BaseModel):                # lo que envía el frontend
    proyecto: Proyecto
    expertos: list[str]                    # ids; por defecto, sugerir_panel(proyecto)
    asignacion_modelos: Literal["auto", "seed", "manual", "mono"] = "auto"
    modelos_manual: dict[str, str] | None = None   # rol -> nombre de modelo
    seed: int | None = None
    min_rondas: int = 2
    max_rondas: int = 3
    umbral_iqr: float = 1.0
    umbral_consenso_global: float = 0.8

class Item(BaseModel):
    id: str                                # "ARQ-E1" (evaluación) o "ARQ-D1-a" (alternativa)
    dimension: Dimension
    tipo: Literal["evaluacion", "alternativa"]
    pregunta: str
    decision_id: str | None = None         # "ARQ-D1": agrupa las alternativas de una decisión
    alternativa: str | None = None         # "Monolito modular"

class Decision(BaseModel):
    id: str                                # "ARQ-D1"
    dimension: Dimension
    titulo: str                            # "Estilo de arquitectura"
    alternativas: list[str]

class Cuestionario(BaseModel):
    decisiones: list[Decision]
    items: list[Item]                      # evaluaciones + una alternativa por ítem

class RespuestaItem(BaseModel):
    item_id: str
    puntaje: int = Field(ge=1, le=5)
    justificacion: str

class RespuestaExperto(BaseModel):
    experto_id: str                        # "E1".."E7": anónimo hacia los demás expertos
    rol: str                               # solo para auditoría; NUNCA se muestra a otros expertos
    modelo: str                            # solo para auditoría y medición de sesgo
    ronda: int
    respuestas: list[RespuestaItem]
    riesgos_detectados: list[str] = []     # riesgos técnicos que el experto quiere señalar

class EstadisticaItem(BaseModel):
    item_id: str
    mediana: float
    q1: float
    q3: float
    iqr: float
    consenso: bool
    argumentos_a_favor: list[str]
    argumentos_en_contra: list[str]

class ResumenRonda(BaseModel):
    ronda: int
    estadisticas: list[EstadisticaItem]
    porcentaje_consenso: float
    continuar: bool
    motivo: str                            # "consenso", "estabilidad", "max_rondas", "moderador"

class DecisionRecomendada(BaseModel):
    decision_id: str
    titulo: str
    alternativa_recomendada: str | None    # None si queda abierta
    estado: Literal["firme", "condicionada", "abierta"]
    mediana: float
    iqr: float
    margen_vs_segunda: float
    condiciones: list[str]                 # p. ej. "revisar si se superan 10k usuarios concurrentes"
    poc_sugerida: str | None               # solo si queda abierta

class Riesgo(BaseModel):
    descripcion: str
    dimension: Dimension
    probabilidad: int = Field(ge=1, le=5)
    impacto: int = Field(ge=1, le=5)
    mitigacion: str
    menciones: int                         # cuántos expertos lo señalaron

class SesgoModelo(BaseModel):
    modelo: str
    puntaje_medio: float
    desviacion_vs_mediana_grupo: float
    preferencias: dict[str, float]         # alternativa -> desviación respecto del grupo

class ADR(BaseModel):
    numero: int
    titulo: str
    estado: Literal["aceptada", "condicionada", "abierta"]
    contexto: str
    decision: str
    alternativas_consideradas: list[str]
    consecuencias: list[str]
    evidencia_delphi: str                  # mediana, IQR, rondas y argumentos clave

class Viabilidad(BaseModel):              # veredicto global; lo calcula el código desde el ítem VIA-E1
    veredicto: Literal["viable", "viable_con_condiciones", "no_viable", "en_discusion"]
    mediana: float
    iqr: float
    consenso: bool
    explicacion: str

class InformeDelphi(BaseModel):
    proyecto: Proyecto
    panel: list[str]
    cuestionario: Cuestionario
    rondas: list[ResumenRonda]
    respuestas: list[RespuestaExperto]
    decisiones: list[DecisionRecomendada]
    evaluacion_por_dimension: dict[str, float]     # dimensión -> mediana final
    riesgos: list[Riesgo]
    disensos: list[str]
    recomendaciones: list[str]
    adrs: list[ADR]
    sesgo_por_modelo: list[SesgoModelo]
    avisos: list[str]                      # p. ej. "panel mono-modelo"
    viabilidad: Viabilidad | None = None   # ¿el proyecto, tal como está planteado, es viable?
    ficha_contexto: str | None = None      # ficha del Asesor normativo (Ley 21.719 + memoria institucional)

class EventoDelphi(BaseModel):             # lo que consume el frontend en vivo
    run_id: str
    seq: int                               # incremental, para pedir solo los eventos nuevos
    timestamp: datetime
    tipo: Literal["run_iniciado", "panel_confirmado", "contexto_preparado", "cuestionario_generado",
                  "ronda_iniciada", "respuesta_experto", "ronda_agregada",
                  "decision_moderador", "cambio_modelo", "run_finalizado",
                  "run_cancelado", "error"]
    ronda: int | None = None
    payload: dict

class EstadoRun(BaseModel):
    run_id: str
    estado: Literal["en_cola", "ejecutando", "finalizado", "cancelado", "error"]
    ronda_actual: int
    config: ConfigRun
    creado: datetime
    finalizado: datetime | None = None
