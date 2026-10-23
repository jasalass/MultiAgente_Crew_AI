"""API FastAPI del Panel Delphi (README §4.2).

    uvicorn backend.api.main:app --reload          # LLM reales según el .env
    DELPHI_SIMULADO=true uvicorn backend.api.main:app   # LLM falsos: demo sin keys

Ejecuta un análisis a la vez: los runs nuevos esperan en cola y un hilo trabajador los
corre con DelphiEngine. La cancelación es por bandera: el motor la revisa entre pasos.
Variables opcionales: DELPHI_OUTPUTS (carpeta de runs), DELPHI_PARALELO (expertos que responden
a la vez, 5 por defecto), DELPHI_PAUSA (segundos entre el inicio de un experto y el siguiente,
5 por defecto) y DELPHI_PAUSA_SIMULADO (latencia ficticia por experto).
"""
from __future__ import annotations

import logging
import os
import queue
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from backend.api.store import RunStore
from backend.delphi.config import RAIZ, ModelPool
from backend.delphi.engine import DelphiEngine, RunCancelado, RunError
from backend.delphi.experts import NUCLEO, listar_expertos, sugerir_panel
from backend.delphi.models import ConfigRun, EstadoRun, EventoDelphi, InformeDelphi, Proyecto
from backend.delphi.project_loader import parsear_markdown
from backend.delphi.simulado import crear_simulacion, pool_simulado

AVISO_SIMULADO = "Ejecución simulada: LLM falsos, los resultados son ficticios."


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def motor_real(pool: ModelPool, pausa: float, paralelo: int = 1) -> Callable[[ConfigRun], DelphiEngine]:
    def crear(config: ConfigRun) -> DelphiEngine:
        llm_para = pool.para_run(config)
        return DelphiEngine(llm_para, pausa_entre_expertos=pausa, paralelo=paralelo,
                            modelo_alternativo=pool.alternativo, avisos=pool.avisos)
    return crear


def motor_simulado(pool: ModelPool, pausa: float = 0.0) -> Callable[[ConfigRun], DelphiEngine]:
    def crear(config: ConfigRun) -> DelphiEngine:
        llm_para = pool.para_run(config)
        ejecutar, moderador = crear_simulacion(semilla=config.seed or 7, pausa=pausa)
        return DelphiEngine(llm_para, ejecutar, moderador, avisos=[AVISO_SIMULADO, *pool.avisos])
    return crear


class ServicioDelphi:
    """Cola de análisis: valida, encola, ejecuta de a uno y registra todo en el RunStore."""

    def __init__(self, store: RunStore, pool: ModelPool, crear_motor: Callable[[ConfigRun], DelphiEngine]):
        self.store, self.pool = store, pool
        self._crear_motor = crear_motor
        self._cola: queue.Queue[str] = queue.Queue()
        self._cancelados: set[str] = set()
        self._lock = threading.Lock()
        threading.Thread(target=self._trabajar, daemon=True, name="delphi-motor").start()

    # ----- peticiones -----
    def validar(self, config: ConfigRun) -> None:
        """Reglas Delphi del README §1.5 que Pydantic no expresa. Lanza ValueError."""
        validos = {e["id"] for e in listar_expertos()}
        panel = config.expertos
        if len(set(panel)) != len(panel) or not set(panel) <= validos:
            raise ValueError("El panel tiene expertos repetidos o desconocidos.")
        if not set(NUCLEO) <= set(panel) or not 5 <= len(panel) <= 7:
            raise ValueError("El panel debe incluir los cinco expertos del núcleo y hasta dos opcionales.")
        if not 2 <= config.min_rondas <= config.max_rondas <= 3:
            raise ValueError("Las rondas deben cumplir 2 ≤ mínimo ≤ máximo ≤ 3.")
        if not 0 <= config.umbral_iqr <= 4 or not 0 < config.umbral_consenso_global <= 1:
            raise ValueError("Revisa los umbrales: IQR entre 0 y 4, consenso global mayor que 0 y hasta 1.")
        self.pool.planificar(panel, config.asignacion_modelos, config.seed, config.modelos_manual)

    def crear(self, config: ConfigRun) -> EstadoRun:
        self.validar(config)
        estado = self.store.crear(config)
        self._cola.put(estado.run_id)
        return estado

    def cancelar(self, run_id: str) -> EstadoRun:
        estado = self.store.obtener(run_id)
        if estado.estado in ("en_cola", "ejecutando"):
            with self._lock:
                self._cancelados.add(run_id)
        if estado.estado == "en_cola":       # aún no empezó: se cancela aquí mismo
            self.store.registrar_evento(run_id, "run_cancelado", {"motivo": "Cancelado antes de empezar."})
            return self.store.actualizar(run_id, estado="cancelado", finalizado=_ahora())
        return estado

    def _cancelado(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._cancelados

    # ----- hilo trabajador -----
    def _trabajar(self) -> None:
        while True:
            run_id = self._cola.get()
            try:
                self._ejecutar(run_id)
            finally:
                self._cola.task_done()

    def esperar_cola(self) -> None:
        """Bloquea hasta que no queden runs pendientes (para tests y scripts)."""
        self._cola.join()

    def _ejecutar(self, run_id: str) -> None:
        estado = self.store.obtener(run_id)
        if estado.estado != "en_cola":
            return
        self.store.actualizar(run_id, estado="ejecutando")
        try:
            motor = self._crear_motor(estado.config)
            informe = motor.run(run_id, estado.config, self.store.agregar_evento,
                                lambda: self._cancelado(run_id))
            self.store.guardar_informe(run_id, informe)
            self.store.actualizar(run_id, estado="finalizado", finalizado=_ahora())
        except RunCancelado:
            self.store.actualizar(run_id, estado="cancelado", finalizado=_ahora())
        except Exception as error:
            if not isinstance(error, RunError):      # RunError ya emitió su evento
                self.store.registrar_evento(run_id, "error", {"mensaje": str(error)})
            self.store.actualizar(run_id, estado="error", finalizado=_ahora())


def _verdadero(nombre: str) -> bool:
    return os.getenv(nombre, "false").strip().lower() in {"1", "true", "yes", "si", "sí"}


def servicio_por_defecto() -> ServicioDelphi:
    registro = logging.getLogger("delphi")                 # qué experto responde y los reintentos
    registro.setLevel(logging.INFO)
    if not registro.handlers:                              # uvicorn no configura loggers ajenos
        manejador = logging.StreamHandler()
        manejador.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s", "%H:%M:%S"))
        registro.addHandler(manejador)
        registro.propagate = False                         # sin esto, uvicorn lo repite
    try:
        from dotenv import load_dotenv
        load_dotenv(RAIZ / ".env")
    except ModuleNotFoundError:
        pass
    store = RunStore(Path(os.getenv("DELPHI_OUTPUTS", RAIZ / "outputs" / "runs")))
    if _verdadero("DELPHI_SIMULADO"):
        pool = pool_simulado()
        return ServicioDelphi(store, pool, motor_simulado(pool, float(os.getenv("DELPHI_PAUSA_SIMULADO", "0.3"))))
    pool = ModelPool.desde_env()
    return ServicioDelphi(store, pool, motor_real(pool, float(os.getenv("DELPHI_PAUSA", "5")),
                                                  int(os.getenv("DELPHI_PARALELO", "5"))))


def crear_app(servicio: ServicioDelphi | None = None) -> FastAPI:
    @asynccontextmanager
    async def ciclo(app: FastAPI):
        if app.state.servicio is None:
            app.state.servicio = servicio_por_defecto()
        yield

    app = FastAPI(title="Panel Delphi API", version="1.0", lifespan=ciclo)
    app.state.servicio = servicio

    def srv(request: Request) -> ServicioDelphi:
        return request.app.state.servicio

    def run_o_404(request: Request, run_id: str) -> EstadoRun:
        try:
            return srv(request).store.obtener(run_id)
        except KeyError:
            raise HTTPException(404, "No se encontró la ejecución solicitada.") from None

    def finalizado(request: Request, run_id: str) -> None:
        if run_o_404(request, run_id).estado != "finalizado":
            raise HTTPException(409, "El informe estará disponible cuando la ejecución termine correctamente.")

    @app.get("/modelos")
    def modelos(request: Request) -> list[dict[str, str]]:
        return srv(request).pool.listar_modelos()

    @app.get("/expertos")
    def expertos() -> list[dict[str, Any]]:
        return listar_expertos()

    @app.post("/panel/sugerir")
    def panel_sugerido(proyecto: dict[str, Any] = Body(...)) -> list[dict[str, str]]:
        try:
            return sugerir_panel(proyecto)
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error)) from None

    @app.post("/proyectos/parsear")
    def parsear(texto: str = Body(..., media_type="application/json")) -> Proyecto:
        try:
            return parsear_markdown(texto)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.post("/runs")
    def crear_run(request: Request, config: ConfigRun) -> dict[str, str]:
        try:
            return {"run_id": srv(request).crear(config).run_id}
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get("/runs")
    def listar_runs(request: Request) -> list[EstadoRun]:
        return srv(request).store.listar()

    @app.get("/runs/{run_id}")
    def obtener_run(request: Request, run_id: str) -> EstadoRun:
        return run_o_404(request, run_id)

    @app.get("/runs/{run_id}/eventos")
    def eventos(request: Request, run_id: str, desde: int = 0) -> list[EventoDelphi]:
        run_o_404(request, run_id)
        return srv(request).store.eventos(run_id, desde)

    @app.post("/runs/{run_id}/cancelar")
    def cancelar(request: Request, run_id: str) -> EstadoRun:
        run_o_404(request, run_id)
        return srv(request).cancelar(run_id)

    @app.get("/runs/{run_id}/informe", response_model=None)
    def informe(request: Request, run_id: str,
                formato: Literal["json", "md"] = "json") -> InformeDelphi | PlainTextResponse:
        finalizado(request, run_id)
        if formato == "md":
            return PlainTextResponse(srv(request).store.informe_md(run_id), media_type="text/markdown; charset=utf-8")
        return srv(request).store.informe(run_id)

    @app.get("/runs/{run_id}/adr.zip")
    def adr_zip(request: Request, run_id: str) -> Response:
        finalizado(request, run_id)
        return Response(srv(request).store.adr_zip(run_id), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="adr-{run_id}.zip"'})

    return app


app = crear_app()
