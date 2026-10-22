"""DelphiEngine: el bucle de rondas (README §4.3 y §5, Pamela).

Reparto de responsabilidades en cada ronda:
  - Los LLM de los expertos responden el cuestionario (vía un Crew jerárquico).
  - El CÓDIGO calcula mediana/IQR/consenso (tools.py) y resume los argumentos
    sin autor (anonymizer.py).
  - El CÓDIGO impone los límites (min/max rondas, consenso, estabilidad). El
    Moderador (LLM) solo propone si seguir cuando el código no lo decide.

Al terminar las rondas arma el InformeDelphi (decisiones.py, adr.py, bias.py).
"""
from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from backend.delphi import llm_io
from backend.delphi.adr import construir_adrs
from backend.delphi.anonymizer import sintetizar_argumentos
from backend.delphi.bias import calcular_sesgo
from backend.delphi.decisiones import consolidar_riesgos, resumen_final
from backend.delphi.experts import get_experto
from backend.delphi.models import (
    ConfigRun, Cuestionario, EstadisticaItem, EventoDelphi, InformeDelphi,
    RespuestaExperto, RespuestaItem, ResumenRonda, SesgoModelo,
)
from backend.delphi.moderador_prompts import construir_prompt_continuar, construir_prompt_cuestionario
from backend.delphi.prompts import construir_prompt_ronda_1, construir_prompt_ronda_k, guard_independencia
from backend.delphi.tools import estadisticas_ronda, porcentaje_consenso

UMBRAL_ESTABILIDAD = 0.5   # README §1.5: variación de la mediana < 0,5 entre rondas


class RunCancelado(Exception):
    """El usuario canceló; el evento run_cancelado ya fue emitido."""


class RunError(Exception):
    """Fallo irrecuperable; el evento error ya fue emitido."""


class _SalidaExperto(BaseModel):
    respuestas: list[RespuestaItem]
    riesgos_detectados: list[str] = []


class _Propuesta(BaseModel):
    continuar: bool
    motivo: str = ""


# --- Reglas de continuación: funciones puras, sin LLM -------------------------------

def mediana_estable(actual: list[EstadisticaItem], previa: list[EstadisticaItem] | None) -> bool:
    """True si ninguna mediana se movió 0,5 o más respecto de la ronda anterior."""
    if not previa:
        return False
    antes = {e.item_id: e.mediana for e in previa}
    return all(abs(e.mediana - antes[e.item_id]) < UMBRAL_ESTABILIDAD
               for e in actual if e.item_id in antes)


def decidir_continuar(ronda: int, config: ConfigRun, pct_consenso: float, estable: bool,
                      propuesta_moderador: bool | None) -> tuple[bool, str]:
    """Devuelve (continuar, motivo). El código manda; el Moderador solo desempata."""
    if ronda < config.min_rondas:
        return True, "min_rondas"
    if pct_consenso >= config.umbral_consenso_global:
        return False, "consenso"
    if estable:
        return False, "estabilidad"
    if ronda >= config.max_rondas:
        return False, "max_rondas"
    if propuesta_moderador is False:
        return False, "moderador"
    return True, "moderador"


# --- Ejecución real con CrewAI (se puede reemplazar al probar) ----------------------

def ejecutar_ronda_crewai(moderador_llm: Any, expertos: list[dict], llms: dict[str, Any],
                          prompts: dict[str, str], step_callback=None, task_callback=None) -> dict[str, str]:
    """Un Crew jerárquico: el Moderador delega a cada experto. Devuelve texto crudo por id."""
    from backend.delphi.crew import crear_crew_ronda, crear_moderador, crear_tarea_experto, crear_worker
    workers = {e["id"]: crear_worker(e, llms[e["id"]]) for e in expertos}
    tareas = {e["id"]: crear_tarea_experto(workers[e["id"]], prompts[e["id"]], e["role"]) for e in expertos}
    crew = crear_crew_ronda(crear_moderador(moderador_llm), list(workers.values()),
                            list(tareas.values()), step_callback, task_callback)
    crew.kickoff()
    return {eid: (t.output.raw if t.output else "") for eid, t in tareas.items()}


class DelphiEngine:
    def __init__(self, llm_para: Callable[[str], Any],
                 ejecutar_ronda: Callable[..., dict[str, str]] = ejecutar_ronda_crewai,
                 llamar_moderador: Callable[[str], str] | None = None):
        """llm_para(id) -> LLM; será ModelPool.get_llm. Usa "moderador" para el Moderador."""
        self._llm_para = llm_para
        self._ejecutar_ronda = ejecutar_ronda
        self._llamar_moderador = llamar_moderador or (lambda prompt: str(self._llm_para("moderador").call(prompt)))

    # ----- eventos -----
    def _emitir(self, tipo: str, payload: dict, ronda: int | None = None) -> None:
        self._on_event(EventoDelphi(run_id=self._run_id, seq=next(self._seq),
                                    timestamp=datetime.now(timezone.utc), tipo=tipo,
                                    ronda=ronda, payload=payload))

    def _revisar_cancelacion(self) -> None:
        if self._should_cancel():
            self._emitir("run_cancelado", {})
            raise RunCancelado()

    # ----- ejecución -----
    def run(self, run_id: str, config: ConfigRun, on_event: Callable[[EventoDelphi], None],
            should_cancel: Callable[[], bool]) -> InformeDelphi:
        self._run_id, self._on_event, self._should_cancel = run_id, on_event, should_cancel
        self._seq = itertools.count(1)
        try:
            return self._run(config)
        except (RunCancelado, RunError):
            raise
        except Exception as error:
            self._emitir("error", {"mensaje": str(error)})
            raise RunError(str(error)) from error

    def _run(self, config: ConfigRun) -> InformeDelphi:
        expertos = [get_experto(i) for i in config.expertos]
        llms = {e["id"]: self._llm_para(e["id"]) for e in expertos}
        anon = {e["id"]: f"E{n}" for n, e in enumerate(expertos, 1)}   # E1..En
        proyecto = config.proyecto

        self._emitir("run_iniciado", {"proyecto": proyecto.nombre})
        self._emitir("panel_confirmado", {"panel": config.expertos})

        self._revisar_cancelacion()
        cuestionario = llm_io.llamar_y_validar(
            self._llamar_moderador, construir_prompt_cuestionario(proyecto), Cuestionario)
        self._emitir("cuestionario_generado", cuestionario.model_dump())

        rondas: list[ResumenRonda] = []
        respuestas: list[RespuestaExperto] = []
        previas: dict[str, RespuestaExperto] = {}
        feedback: dict | None = None
        estadisticas_previas: list[EstadisticaItem] | None = None

        for ronda in range(1, config.max_rondas + 1):
            self._revisar_cancelacion()
            self._emitir("ronda_iniciada", {}, ronda)

            prompts = {e["id"]: self._prompt_experto(e, proyecto, cuestionario, ronda,
                                                     previas.get(e["id"]), feedback)
                       for e in expertos}
            crudo = self._ejecutar_ronda(self._llm_para("moderador"), expertos, llms, prompts)

            actuales: list[RespuestaExperto] = []
            for e in expertos:
                salida = self._validar_salida(crudo.get(e["id"], ""), e["id"], cuestionario)
                r = RespuestaExperto(experto_id=anon[e["id"]], rol=e["id"],
                                     modelo=str(getattr(llms[e["id"]], "model", "desconocido")),
                                     ronda=ronda, respuestas=salida.respuestas,
                                     riesgos_detectados=salida.riesgos_detectados)
                actuales.append(r)
                previas[e["id"]] = r
                self._emitir("respuesta_experto", r.model_dump(), ronda)
            respuestas.extend(actuales)

            estadisticas, pct = self._agregar(actuales, cuestionario, config)
            estable = mediana_estable(estadisticas, estadisticas_previas)

            # Solo se consulta al Moderador cuando el código no puede decidir solo.
            propuesta = None
            if config.min_rondas <= ronda < config.max_rondas \
                    and pct < config.umbral_consenso_global and not estable:
                propuesta = self._proponer(ronda, config, pct)
            continuar, motivo = decidir_continuar(ronda, config, pct, estable, propuesta)

            rondas.append(ResumenRonda(ronda=ronda, estadisticas=estadisticas,
                                       porcentaje_consenso=pct, continuar=continuar, motivo=motivo))
            self._emitir("ronda_agregada", {"porcentaje_consenso": pct,
                                            "estadisticas": [e.model_dump() for e in estadisticas]}, ronda)
            self._emitir("decision_moderador", {"continuar": continuar, "motivo": motivo,
                                                "propuesta_moderador": propuesta}, ronda)
            if not continuar:
                break
            feedback = {"ronda": ronda, "porcentaje_consenso": pct,
                        "estadisticas": [e.model_dump() for e in estadisticas]}
            estadisticas_previas = estadisticas

        decisiones, por_dimension, disensos, recomendaciones = resumen_final(cuestionario, rondas)
        riesgos = consolidar_riesgos(respuestas, self._llamar_moderador, len(expertos))
        sesgo = [SesgoModelo(**s) for s in calcular_sesgo(respuestas, cuestionario)]
        avisos = []
        if len({r.modelo for r in respuestas}) < 2:
            avisos.append("panel mono-modelo: riesgo de falso consenso")
        informe = InformeDelphi(
            proyecto=proyecto, panel=config.expertos, cuestionario=cuestionario, rondas=rondas,
            respuestas=respuestas, decisiones=decisiones, evaluacion_por_dimension=por_dimension,
            riesgos=riesgos, disensos=disensos, recomendaciones=recomendaciones,
            adrs=construir_adrs(proyecto, cuestionario, rondas, decisiones),
            sesgo_por_modelo=sesgo, avisos=avisos)
        self._emitir("run_finalizado", {"rondas": len(rondas)})
        return informe

    # ----- piezas -----
    def _prompt_experto(self, experto: dict, proyecto: Any, cuestionario: Cuestionario, ronda: int,
                        anterior: RespuestaExperto | None, feedback: dict | None) -> str:
        contexto: dict[str, Any] = {"proyecto": proyecto.model_dump(),
                                    "cuestionario": cuestionario.model_dump(), "ronda": ronda}
        if ronda > 1:
            contexto["respuesta_anterior"] = {
                "respuestas": [r.model_dump() for r in anterior.respuestas],
                "riesgos_detectados": anterior.riesgos_detectados}
            contexto["feedback"] = feedback
        guard_independencia(contexto)      # lanza ValueError si se filtra algo ajeno
        if ronda == 1:
            return construir_prompt_ronda_1(experto, contexto["proyecto"], contexto["cuestionario"])
        return construir_prompt_ronda_k(experto, contexto["proyecto"], contexto["cuestionario"],
                                        contexto["respuesta_anterior"], feedback, ronda)

    def _validar_salida(self, texto: str, experto_id: str, cuestionario: Cuestionario) -> _SalidaExperto:
        try:
            salida = llm_io.validar(texto, _SalidaExperto)
        except Exception as error:
            raise ValueError(f"Respuesta inválida del experto «{experto_id}»: {error}") from error
        esperados = sorted(i.id for i in cuestionario.items)
        if sorted(r.item_id for r in salida.respuestas) != esperados:
            raise ValueError(f"El experto «{experto_id}» no respondió exactamente los ítems del cuestionario")
        return salida

    def _agregar(self, respuestas: list[RespuestaExperto], cuestionario: Cuestionario,
                 config: ConfigRun) -> tuple[list[EstadisticaItem], float]:
        numeros = estadisticas_ronda(respuestas, config.umbral_iqr)
        argumentos = {a["item_id"]: a for a in sintetizar_argumentos(respuestas, cuestionario)}
        items = [EstadisticaItem(
            **{k: v for k, v in n.items() if k != "n"},
            argumentos_a_favor=argumentos[n["item_id"]]["argumentos_a_favor"],
            argumentos_en_contra=argumentos[n["item_id"]]["argumentos_en_contra"]) for n in numeros]
        return items, porcentaje_consenso(numeros)

    def _proponer(self, ronda: int, config: ConfigRun, pct: float) -> bool | None:
        """Pregunta al Moderador; si falla, no bloquea: devuelve None (seguir)."""
        try:
            p = llm_io.llamar_y_validar(self._llamar_moderador, construir_prompt_continuar(
                ronda, config.max_rondas, pct, config.umbral_consenso_global), _Propuesta)
            return p.continuar
        except Exception:
            return None
