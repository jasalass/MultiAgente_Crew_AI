"""RunStore: estado, eventos e informe de cada run en outputs/runs/<run_id>/ (README §1.7).

  estado.json    EstadoRun (incluye la ConfigRun)
  eventos.jsonl  un EventoDelphi por línea, en el orden en que llegan
  informe.*, adr/, rondas.json   al finalizar (report.guardar_resultados)

Al iniciar se cargan los runs del disco para el historial. Un run que quedó en cola o
ejecutándose cuando se detuvo el servidor se marca como error: su hilo ya no existe.
Thread-safe: la API escribe desde el hilo del motor y lee desde las peticiones HTTP.
"""
from __future__ import annotations

import io
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from backend.delphi.models import ConfigRun, EstadoRun, EventoDelphi, InformeDelphi
from backend.delphi.report import guardar_resultados

ACTIVOS = {"en_cola", "ejecutando"}


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class RunStore:
    def __init__(self, raiz: Path):
        self._raiz = Path(raiz)
        self._raiz.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._estados: dict[str, EstadoRun] = {}
        self._eventos: dict[str, list[EventoDelphi]] = {}
        self._cargar()

    def _dir(self, run_id: str) -> Path:
        return self._raiz / run_id

    def _cargar(self) -> None:
        for archivo in sorted(self._raiz.glob("*/estado.json")):
            try:
                estado = EstadoRun.model_validate_json(archivo.read_text(encoding="utf-8"))
            except ValueError:
                continue                                  # carpeta ajena o corrupta: se ignora
            ruta = archivo.parent / "eventos.jsonl"
            lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []
            self._eventos[estado.run_id] = [EventoDelphi.model_validate_json(l) for l in lineas if l.strip()]
            self._estados[estado.run_id] = estado
            if estado.estado in ACTIVOS:
                self.registrar_evento(estado.run_id, "error",
                                     {"mensaje": "El servidor se detuvo durante la ejecución."})
                self.actualizar(estado.run_id, estado="error", finalizado=_ahora())

    def _guardar_estado(self, estado: EstadoRun) -> None:
        directorio = self._dir(estado.run_id)
        directorio.mkdir(parents=True, exist_ok=True)
        (directorio / "estado.json").write_text(estado.model_dump_json(indent=2), encoding="utf-8")

    # ----- runs -----
    def crear(self, config: ConfigRun) -> EstadoRun:
        with self._lock:
            run_id = f"{_ahora():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
            estado = EstadoRun(run_id=run_id, estado="en_cola", ronda_actual=0, config=config, creado=_ahora())
            self._estados[run_id], self._eventos[run_id] = estado, []
            self._guardar_estado(estado)
            return estado

    def obtener(self, run_id: str) -> EstadoRun:
        with self._lock:
            if run_id not in self._estados:
                raise KeyError(run_id)
            return self._estados[run_id]

    def listar(self) -> list[EstadoRun]:
        """Historial, del más reciente al más antiguo."""
        with self._lock:
            return sorted(self._estados.values(), key=lambda e: e.creado, reverse=True)

    def actualizar(self, run_id: str, **campos) -> EstadoRun:
        with self._lock:
            estado = self.obtener(run_id).model_copy(update=campos)
            self._estados[run_id] = estado
            self._guardar_estado(estado)
            return estado

    # ----- eventos -----
    def agregar_evento(self, evento: EventoDelphi) -> None:
        with self._lock:
            self._eventos[evento.run_id].append(evento)
            with open(self._dir(evento.run_id) / "eventos.jsonl", "a", encoding="utf-8") as archivo:
                archivo.write(evento.model_dump_json() + "\n")
            if evento.ronda is not None:
                self.actualizar(evento.run_id, ronda_actual=evento.ronda)

    def registrar_evento(self, run_id: str, tipo: str, payload: dict) -> None:
        """Evento generado por la API (no por el motor), con el siguiente seq."""
        with self._lock:
            seq = max((e.seq for e in self._eventos.get(run_id, [])), default=0) + 1
            self.agregar_evento(EventoDelphi(run_id=run_id, seq=seq, timestamp=_ahora(), tipo=tipo,
                                             ronda=None, payload=payload))

    def eventos(self, run_id: str, desde: int = 0) -> list[EventoDelphi]:
        """Eventos con seq > desde (cursor exclusivo)."""
        with self._lock:
            self.obtener(run_id)
            return [e for e in self._eventos[run_id] if e.seq > desde]

    # ----- resultados -----
    def guardar_informe(self, run_id: str, informe: InformeDelphi) -> None:
        guardar_resultados(self._dir(run_id), informe)

    def informe(self, run_id: str) -> InformeDelphi:
        return InformeDelphi.model_validate_json((self._dir(run_id) / "informe.json").read_text(encoding="utf-8"))

    def informe_md(self, run_id: str) -> str:
        return (self._dir(run_id) / "informe.md").read_text(encoding="utf-8")

    def adr_zip(self, run_id: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archivo:
            for ruta in sorted((self._dir(run_id) / "adr").glob("*.md")):
                archivo.write(ruta, ruta.name)
        return buffer.getvalue()
