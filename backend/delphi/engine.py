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
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from backend.delphi import llm_io, stats
from backend.delphi.adr import construir_adrs
from backend.delphi.anonymizer import sintetizar_argumentos
from backend.delphi.asignacion import AFINES
from backend.delphi.bias import calcular_sesgo
from backend.delphi.decisiones import ITEM_VIABILIDAD, consolidar_riesgos, evaluar_viabilidad, resumen_final
from backend.delphi.experts import get_experto
from backend.delphi.models import (
    ConfigRun, Cuestionario, EstadisticaItem, EventoDelphi, InformeDelphi, Item,
    RespuestaExperto, RespuestaItem, ResumenRonda, SesgoModelo,
)
from backend.delphi.moderador_prompts import construir_prompt_continuar, construir_prompt_cuestionario
from backend.delphi.prompts import construir_prompt_ronda_1, construir_prompt_ronda_k, guard_independencia
from backend.delphi.tools import estadisticas_ronda, porcentaje_consenso

log = logging.getLogger("delphi")

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
    return stats.es_estable({e.item_id: e.mediana for e in actual},
                            {e.item_id: e.mediana for e in previa} if previa else None)


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

def acotar_cuestionario(cuestionario: Cuestionario, max_decisiones: int = 5,
                        max_evaluaciones: int = 10) -> Cuestionario:
    """README §1.5: 3 a 5 decisiones clave y 6 a 10 ítems de evaluación.

    El LLM a veces genera más. El exceso se recorta en el código, porque cada ítem alarga la
    respuesta de todos los expertos en todas las rondas (y los planes gratuitos limitan tokens).
    También a veces vincula una pregunta de evaluación a una decisión: se desvincula, porque
    solo los ítems de tipo "alternativa" compiten dentro de una decisión.
    """
    cuestionario = cuestionario.model_copy(update={"items": [
        i.model_copy(update={"decision_id": None, "alternativa": None}) if i.tipo == "evaluacion" else i
        for i in cuestionario.items]})
    decisiones = cuestionario.decisiones[:max_decisiones]
    vigentes = {d.id for d in decisiones}
    evaluaciones = {i.id for i in cuestionario.items if i.tipo == "evaluacion"}
    conservar = set(sorted(evaluaciones, key=[i.id for i in cuestionario.items].index)[:max_evaluaciones])
    conservar |= {i.id for i in cuestionario.items if i.tipo == "alternativa" and i.decision_id in vigentes}
    return Cuestionario(decisiones=decisiones, items=[i for i in cuestionario.items if i.id in conservar])


PREGUNTA_VIABILIDAD = ("Viabilidad global: ¿qué tan viable es el proyecto TAL COMO ESTÁ PLANTEADO, considerando "
                       "alcance, plazo, equipo y presupuesto? (1 = inviable, 3 = viable solo con cambios "
                       "importantes, 5 = plenamente viable)")


def asegurar_item_viabilidad(cuestionario: Cuestionario) -> Cuestionario:
    """Agrega siempre la pregunta de viabilidad global (VIA-E1), de la que sale el veredicto del informe.

    La agrega el código y no el Moderador: así el veredicto existe en todos los análisis.
    """
    if any(i.id == ITEM_VIABILIDAD for i in cuestionario.items):
        return cuestionario
    item = Item(id=ITEM_VIABILIDAD, dimension="gestion", tipo="evaluacion", pregunta=PREGUNTA_VIABILIDAD)
    return cuestionario.model_copy(update={"items": [*cuestionario.items, item]})


def bloque_ficha(ficha: str | None) -> str:
    """La ficha del Asesor, agregada después del contexto que valida guard_independencia.

    Es igual para todo el panel y se escribe antes de la ronda 1 (nadie opinó todavía): es
    material de referencia verificable, no la opinión de otro experto.
    """
    if not ficha:
        return ""
    return ("\n\nFICHA DE CONTEXTO (preparada por el Asesor normativo antes de la ronda 1, igual para todo el "
            "panel; es material de referencia verificable, no la opinión de otro experto):\n" + ficha)


def con_contexto_normativo(adrs: list, ficha: str | None) -> list:
    """Agrega al contexto de cada ADR las obligaciones legales de la ficha del Asesor (con sus citas)."""
    seccion = re.search(r"##\s*Obligaciones legales relevantes\s*\n(.*?)(?=\n##|\Z)", ficha or "", re.DOTALL)
    if not seccion or not seccion.group(1).strip():
        return adrs
    extra = "\n\nContexto normativo (Ley 21.719, según la ficha del Asesor):\n" + seccion.group(1).strip()
    return [a.model_copy(update={"contexto": a.contexto + extra}) for a in adrs]


def elegir_moderador(moderadores: Any, n: int) -> Any:
    """Rota entre varios LLM de Moderador (o devuelve el único que haya)."""
    if isinstance(moderadores, (list, tuple)):
        return moderadores[n % len(moderadores)]
    return moderadores


def _es_limite_de_tasa(error: Exception) -> bool:
    """Falla pasajera: esperar y reintentar sirve. Un 413 (petición mayor que el tope) no.

    Incluye el 429 (límite de tasa) y los errores del servidor del proveedor (500, 502, 503,
    "internal", "overloaded", "unavailable"), que en los planes gratuitos aparecen de vez en cuando.
    """
    texto = str(error).lower()
    return any(s in texto for s in ("429", "rate limit", "rate_limit", "error code: 500", "error code: 502",
                                    "error code: 503", "internal error", "overloaded", "unavailable"))


def _modelo_no_disponible(error: Exception) -> bool:
    """Reintentar no sirve: el modelo no existe o fue retirado (p. ej. una variante :free que terminó),
    o cada petición supera su límite por minuto ("request too large", como Qwen con 1000 OTPM)."""
    texto = str(error).lower()
    return any(s in texto for s in ("404", "not found", "does not exist", "retired", "decommissioned",
                                    "request too large"))


def _modelo(llm: Any) -> str:
    return str(getattr(llm, "model", "desconocido"))


def _culpa_del_moderador(error: Exception, moderadores: Any) -> bool:
    """El límite lo alcanzó el Moderador si el error nombra su modelo: cambiar al experto no sirve."""
    lista = moderadores if isinstance(moderadores, (list, tuple)) else [moderadores]
    nombres = set()
    for m in lista:                    # CrewAI puede conservar o quitar el prefijo "openai/"
        modelo = _modelo(m).lower()
        nombres |= {modelo, modelo.removeprefix("openai/")}
    texto = str(error).lower()
    return any(nombre in texto for nombre in nombres - {"desconocido", ""})


def con_reintentos(accion: Callable[[], Any], intentos: int = 3, espera: float = 30.0,
                   dormir: Callable[[float], None] = time.sleep) -> Any:
    """Reintenta ante límites de tasa con espera progresiva (30 s, 60 s, ...) y lo deja en el log."""
    for n in range(intentos):
        try:
            return accion()
        except Exception as error:
            if n == intentos - 1 or not _es_limite_de_tasa(error) or _modelo_no_disponible(error):
                raise
            log.warning("Límite de tasa: espero %.0f s y reintento (%d/%d). %s",
                        espera * 2 ** n, n + 2, intentos, str(error)[:160])
            dormir(espera * 2 ** n)


def ejecutar_ronda_crewai(moderadores: Any, expertos: list[dict], llms: dict[str, Any],
                          prompts: dict[str, str], step_callback=None, task_callback=None,
                          pausa: float = 0.0, inicio: int = 0,
                          dormir: Callable[[float], None] = time.sleep,
                          revisar_cancelacion: Callable[[], None] | None = None,
                          cambiar_modelo: Callable[[str, str], Any] | None = None,
                          al_responder: Callable[[str, str], None] | None = None,
                          paralelo: int = 1) -> dict[str, str]:
    """Un Crew jerárquico POR experto: el Moderador delega en él. Devuelve texto crudo por id.

    Con un solo Crew para todo el panel, el Moderador acumula en su contexto la respuesta de
    cada experto y rebasa el límite de tokens por minuto de los planes gratuitos. Un Crew por
    experto mantiene su historial corto y permite repartir el tráfico entre varios modelos de
    Moderador (`moderadores` puede ser una lista; se rota desde `inicio`, que el motor avanza
    entre rondas, y en cada reintento se pasa a la key siguiente).

    Con `paralelo` > 1 hasta ese número de expertos responde a la vez (cada uno en su Crew, así
    que siguen sin verse entre sí): la ronda dura lo que tarda el más lento y no la suma.
    `pausa` separa el inicio de un experto y el siguiente, para repartir el tráfico por minuto.

    El texto devuelto es la salida del EXPERTO, no la respuesta final del Moderador (crew.py).
    Antes de lanzar cada experto se llama a `revisar_cancelacion`; los que ya están respondiendo
    terminan. Si un 429 persiste o el modelo ya no existe, y no es culpa del Moderador,
    `cambiar_modelo(id, motivo)` da otro LLM para ese experto; `llms` se actualiza en el lugar
    para que el motor registre el modelo que de verdad respondió. `al_responder(id, texto)` avisa
    apenas responde cada experto (desde el hilo que llamó), para mostrarlo en vivo.
    """
    from backend.delphi.crew import crear_crew_ronda, crear_moderador, crear_tarea_experto, crear_worker

    def responder(n: int, e: dict) -> str:
        log.info("Experto %s (%s): delegando…", e["id"], _modelo(llms[e["id"]]))

        def correr(intentos=itertools.count()):
            worker = crear_worker(e, llms[e["id"]])      # Crew y tarea nuevos en cada intento
            tarea = crear_tarea_experto(worker, prompts[e["id"]], e["role"])
            moderador = crear_moderador(elegir_moderador(moderadores, inicio + n + next(intentos)))
            crear_crew_ronda(moderador, [worker], [tarea], step_callback, task_callback).kickoff()
            if worker.error is not None:
                raise worker.error                       # CrewAI lo había convertido en texto
            return worker.salida or ""                   # "" si el Moderador no delegó
        while True:                                     # un modelo de respaldo tras otro, mientras haya
            try:
                texto = con_reintentos(correr, dormir=dormir)
                break
            except Exception as error:
                nuevo = None
                caido = _modelo_no_disponible(error)
                if (cambiar_modelo and (caido or _es_limite_de_tasa(error))
                        and not _culpa_del_moderador(error, moderadores)):
                    nuevo = cambiar_modelo(e["id"], "modelo no disponible" if caido else "límite de tasa persistente")
                if nuevo is None:
                    raise
                llms[e["id"]] = nuevo
        log.info("Experto %s: respondió.", e["id"])
        return texto

    salida: dict[str, str] = {}
    if paralelo <= 1:
        for n, e in enumerate(expertos):
            if revisar_cancelacion:
                revisar_cancelacion()
            salida[e["id"]] = responder(n, e)
            if al_responder:
                al_responder(e["id"], salida[e["id"]])
            if pausa:
                dormir(pausa)
        return salida

    with ThreadPoolExecutor(max_workers=paralelo, thread_name_prefix="experto") as hilos:
        pendientes = {}
        for n, e in enumerate(expertos):
            if revisar_cancelacion:
                revisar_cancelacion()                    # al salir del with se espera a los ya lanzados
            pendientes[hilos.submit(responder, n, e)] = e["id"]
            if pausa and n < len(expertos) - 1:
                dormir(pausa)
        for listo in as_completed(pendientes):
            salida[pendientes[listo]] = listo.result()
            if al_responder:
                al_responder(pendientes[listo], salida[pendientes[listo]])
    return salida


def _proyecto_para_experto(proyecto: Any) -> dict[str, Any]:
    """Datos del proyecto sin repetir contenido en el prompt.

    `texto_original` duplica los campos ya extraídos (casi el doble de tokens por experto). Solo
    se conserva si el parser no extrajo nada más allá del nombre y el objetivo.
    """
    datos = proyecto.model_dump()
    estructurados = [k for k, v in datos.items() if k not in ("nombre", "objetivo", "texto_original") and v]
    if estructurados:
        datos.pop("texto_original", None)
    return datos


class DelphiEngine:
    def __init__(self, llm_para: Callable[[str], Any],
                 ejecutar_ronda: Callable[..., dict[str, str]] = ejecutar_ronda_crewai,
                 llamar_moderador: Callable[[str], str] | None = None,
                 pausa_entre_expertos: float = 0.0,
                 modelo_alternativo: Callable[[str], Any] | None = None,
                 avisos: list[str] | None = None,
                 paralelo: int = 1,
                 asesor: Callable[[Any, str], dict] | None = None):
        """llm_para(id) -> LLM (ModelPool.get_llm). "moderador" da el LLM o la lista de LLM del Moderador.

        modelo_alternativo(id) -> otro LLM para ese experto ante un 429 persistente
        (ModelPool.alternativo), o None si no hay. `avisos` se agregan al informe.
        `paralelo`: cuántos expertos responden a la vez en cada ronda (1 = de a uno).
        `asesor(proyecto, run_id)` -> {"ficha", "consultas"}: el Asesor normativo (asesor.py), que
        consulta la Ley 21.719 y la memoria institucional antes de la ronda 1. None = sin ficha.
        """
        self._llm_para = llm_para
        self._ejecutar_ronda = ejecutar_ronda
        self._pausa = pausa_entre_expertos
        self._paralelo = paralelo
        self._asesor = asesor
        self._ficha: str | None = None
        self._candado = threading.Lock()   # seq y emisión juntos: con expertos en paralelo
        self._modelo_alternativo = modelo_alternativo
        self._avisos = list(avisos or [])
        self._turno = 0   # sigue la rotación de Moderadores entre rondas
        self._llamar_moderador = llamar_moderador or self._moderador_directo
        self._llamar_puntual = llamar_moderador or self._puntual_directo

    def _moderador_directo(self, prompt: str) -> str:
        """Llamada sin Crew (continuar y respaldo de las puntuales). Cada reintento usa la key siguiente."""
        intentos = itertools.count(self._turno)
        return con_reintentos(lambda: str(elegir_moderador(self._llm_para("moderador"), next(intentos)).call(prompt)))

    def _puntual_directo(self, prompt: str) -> str:
        """Llamadas únicas de alto valor (cuestionario y riesgos) con el LLM "puntual", si lo hay.

        Es un modelo bueno pero lento o con pocas peticiones al día (p. ej. Nemotron gratuito):
        se intenta una sola vez y, si falla, la llamada la hace el Moderador y queda un aviso.
        """
        try:
            puntuales = self._llm_para("puntual")
        except KeyError:
            puntuales = None
        if puntuales:
            llm = elegir_moderador(puntuales, 0)
            try:
                return str(llm.call(prompt))
            except Exception as error:
                self._avisos.append(f"La llamada puntual a {_modelo(llm)} falló ({type(error).__name__}); "
                                    "la hizo el Moderador.")
        return self._moderador_directo(prompt)

    # ----- eventos -----
    def _emitir(self, tipo: str, payload: dict, ronda: int | None = None) -> None:
        # Bajo candado: si dos hilos emitieran a la vez, el evento N+1 podría llegar antes que el N
        # y el frontend, que pide "los posteriores a N", se saltaría uno.
        with self._candado:
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
        self._emitir("panel_confirmado", {"panel": config.expertos,
                                          "modelos": {i: _modelo(llm) for i, llm in llms.items()}})

        self._ficha = self._preparar_contexto(proyecto)
        self._revisar_cancelacion()
        cuestionario = asegurar_item_viabilidad(acotar_cuestionario(llm_io.llamar_y_validar(
            self._llamar_puntual, construir_prompt_cuestionario(proyecto) + bloque_ficha(self._ficha), Cuestionario)))
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
            procesadas: dict[str, RespuestaExperto] = {}

            def procesar(experto_id: str, texto: str, ronda: int = ronda) -> None:
                """Valida la respuesta de UN experto y emite respuesta_experto en el momento.

                Si sigue inválida tras el reintento, se le pregunta con otro modelo (cambio_modelo):
                un modelo gratuito que se equivoca una vez no debe abortar todo el análisis.
                """
                while True:                     # un modelo de respaldo tras otro, mientras haya
                    try:
                        salida = self._salida_con_reintento(texto, experto_id, prompts[experto_id],
                                                            llms[experto_id], cuestionario)
                        break
                    except Exception as error:  # inválida otra vez, o el reintento chocó con la cuota
                        motivo = "respuesta inválida" if isinstance(error, ValueError) else "límite de tasa persistente"
                        nuevo = self._cambiar_modelo(experto_id, ronda, llms, motivo)
                        if nuevo is None or not hasattr(nuevo, "call"):
                            raise
                        llms[experto_id] = nuevo
                        try:
                            texto = str(con_reintentos(lambda: nuevo.call(prompts[experto_id])))
                        except Exception:
                            texto = ""          # también falló: la validación pasa al siguiente modelo
                r = RespuestaExperto(experto_id=anon[experto_id], rol=experto_id, modelo=_modelo(llms[experto_id]),
                                     ronda=ronda, respuestas=salida.respuestas,
                                     riesgos_detectados=salida.riesgos_detectados)
                procesadas[experto_id] = r
                self._emitir("respuesta_experto", r.model_dump(), ronda)

            crudo = self._ejecutar_ronda(
                self._llm_para("moderador"), expertos, llms, prompts, pausa=self._pausa, inicio=self._turno, paralelo=self._paralelo,
                revisar_cancelacion=self._revisar_cancelacion, al_responder=procesar,
                cambiar_modelo=lambda experto_id, motivo, ronda=ronda: self._cambiar_modelo(
                    experto_id, ronda, llms, motivo))
            self._turno += len(expertos)
            for e in expertos:            # ejecutores que no avisan por experto (tests, simulaciones)
                if e["id"] not in procesadas:
                    procesar(e["id"], crudo.get(e["id"], ""))

            actuales = [procesadas[e["id"]] for e in expertos]
            for r in actuales:
                previas[r.rol] = r
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
        riesgos = consolidar_riesgos(respuestas, self._llamar_puntual, len(expertos))
        sesgo = [SesgoModelo(**s) for s in calcular_sesgo(respuestas, cuestionario)]
        informe = InformeDelphi(
            proyecto=proyecto, panel=config.expertos, cuestionario=cuestionario, rondas=rondas,
            respuestas=respuestas, decisiones=decisiones, evaluacion_por_dimension=por_dimension,
            riesgos=riesgos, disensos=disensos, recomendaciones=recomendaciones,
            adrs=con_contexto_normativo(construir_adrs(proyecto, cuestionario, rondas, decisiones), self._ficha),
            sesgo_por_modelo=sesgo, avisos=self._avisos_finales(respuestas),
            viabilidad=evaluar_viabilidad(rondas[-1], decisiones, riesgos), ficha_contexto=self._ficha)
        self._emitir("run_finalizado", {"rondas": len(rondas)})
        return informe

    def _avisos_finales(self, respuestas: list[RespuestaExperto]) -> list[str]:
        """Avisos del ModelPool más los que se ven en los modelos que respondieron de verdad."""
        avisos = list(self._avisos)
        if len({r.modelo for r in respuestas}) < 2:
            avisos.append("panel mono-modelo: riesgo de falso consenso")
            return avisos
        ultima = max(r.ronda for r in respuestas)
        modelo = {r.rol: r.modelo for r in respuestas if r.ronda == ultima}
        for a, b in AFINES:          # puede pasar tras un cambio de modelo o en modo manual
            if a in modelo and b in modelo and modelo[a] == modelo[b]:
                avisos.append(f"Los roles afines {a} y {b} terminaron con el mismo modelo ({modelo[a]}).")
        return avisos

    def _cambiar_modelo(self, experto_id: str, ronda: int, llms: dict[str, Any],
                        motivo: str = "límite de tasa persistente") -> Any:
        """Pide otro modelo para el experto (429 persistente o modelo caído) y emite cambio_modelo."""
        if self._modelo_alternativo is None:
            return None
        caido = motivo == "modelo no disponible"
        nuevo = self._modelo_alternativo(experto_id, caido=True) if caido else self._modelo_alternativo(experto_id)
        if nuevo is not None:
            self._emitir("cambio_modelo", {"experto": experto_id, "anterior": _modelo(llms[experto_id]),
                                           "nuevo": _modelo(nuevo), "motivo": motivo}, ronda)
        return nuevo

    # ----- piezas -----
    def _preparar_contexto(self, proyecto: Any) -> str | None:
        """Corre el Asesor normativo y emite contexto_preparado. Si falla, se sigue sin ficha."""
        if self._asesor is None:
            return None
        self._revisar_cancelacion()
        try:
            contexto = self._asesor(proyecto, self._run_id)
        except Exception as error:
            log.warning("El Asesor normativo falló: %s", error)
            self._avisos.append(f"El Asesor normativo no pudo preparar la ficha ({type(error).__name__}); "
                                "el panel trabajó sin ella.")
            return None
        self._emitir("contexto_preparado", {"ficha": contexto.get("ficha", ""),
                                            "consultas": contexto.get("consultas", []),
                                            "advertencias": contexto.get("advertencias", [])})
        self._avisos += [f"Asesor normativo: {a}" for a in contexto.get("advertencias", [])]
        return contexto.get("ficha") or None

    def _prompt_experto(self, experto: dict, proyecto: Any, cuestionario: Cuestionario, ronda: int,
                        anterior: RespuestaExperto | None, feedback: dict | None) -> str:
        contexto: dict[str, Any] = {"proyecto": _proyecto_para_experto(proyecto),
                                    "cuestionario": cuestionario.model_dump(), "ronda": ronda}
        if ronda > 1:
            contexto["respuesta_anterior"] = {
                "respuestas": [r.model_dump() for r in anterior.respuestas],
                "riesgos_detectados": anterior.riesgos_detectados}
            contexto["feedback"] = feedback
        guard_independencia(contexto)      # lanza ValueError si se filtra algo ajeno
        if ronda == 1:
            prompt = construir_prompt_ronda_1(experto, contexto["proyecto"], contexto["cuestionario"])
        else:
            prompt = construir_prompt_ronda_k(experto, contexto["proyecto"], contexto["cuestionario"],
                                              contexto["respuesta_anterior"], feedback, ronda)
        return prompt + bloque_ficha(self._ficha)

    def _salida_con_reintento(self, texto: str, experto_id: str, prompt: str, llm: Any,
                              cuestionario: Cuestionario) -> _SalidaExperto:
        """Valida la respuesta del experto; si falla, un único reintento con el error (README §4.3).

        Pasa con modelos pequeños que omiten ítems (p. ej. contestan solo las evaluaciones y se saltan
        las alternativas). El reintento llama directo al LLM del experto, con el mismo prompt: no
        añade información de otros expertos, así que no rompe la independencia.
        """
        try:
            return self._validar_salida(texto, experto_id, cuestionario)
        except ValueError as error:
            log.warning("Respuesta inválida de %s (%s): %s | inicio: %r | fin: %r", experto_id, _modelo(llm),
                        error, texto[:120], texto[-120:])
            if not hasattr(llm, "call"):
                raise
            esperados = ", ".join(sorted(i.id for i in cuestionario.items))
            segundo = str(con_reintentos(lambda: llm.call(
                f"{prompt}\n\nTu respuesta anterior no fue válida: {error}\n"
                f"Responde de nuevo SOLO el JSON y con TODOS estos item_id, exactamente una vez cada uno: {esperados}.")))
            return self._validar_salida(segundo, experto_id, cuestionario)

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
