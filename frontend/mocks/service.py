"""API simulada en memoria, aislada por sesión, con cola y progreso por polling."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import re
import unicodedata
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from frontend.api_client import ApiError
from .fixtures import (FECHA_DEMO, MODELOS, NUCLEO, adr_markdown, construir_eventos,
                       construir_informe, ejemplos_proyectos, informe_markdown)


def _normalizar(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))


class MockService:
    def __init__(self):
        self._runs = {}
        self._contador = 0
        self._activo = None
        config = self._config({"proyecto": ejemplos_proyectos()[0], "expertos": NUCLEO + ["datos", "ux"]})
        informe = construir_informe(config)
        run_id = "demo-clinica-finalizado"
        eventos = construir_eventos(run_id, informe)
        self._runs[run_id] = {"estado": {"run_id": run_id, "estado": "finalizado", "ronda_actual": len(informe["rondas"]),
                                        "config": config, "creado": FECHA_DEMO, "finalizado": eventos[-1]["timestamp"]},
                              "informe": informe, "eventos": eventos, "visibles": len(eventos)}

    @staticmethod
    def listar_modelos():
        return deepcopy(MODELOS)

    @staticmethod
    def listar_expertos():
        try:
            from backend.delphi.experts import listar_expertos
            expertos = listar_expertos()
            return [e.model_dump() if hasattr(e, "model_dump") else deepcopy(e) for e in expertos]
        except ImportError:
            # El modo demo también funciona antes de integrar el catálogo de Jenaro.
            nombres = {"arquitectura": "Arquitectura de Software", "cloud": "Cloud e Infraestructura", "desarrollo": "Desarrollo", "seguridad": "Ciberseguridad", "devops": "DevOps / SRE", "datos": "Datos", "qa": "QA / Testing", "ux": "UX/UI", "gestion": "Gestión de Proyecto", "ia": "IA/ML"}
            dimensiones = {"cloud": "infraestructura", "desarrollo": "stack", "devops": "operacion", "qa": "calidad", "ux": "calidad", "ia": "datos"}
            return [{"id": rol, "nombre": nombre, "tipo": "nucleo" if rol in NUCLEO else "opcional", "role": nombre,
                     "goal": f"Evaluar {nombre} en el contexto del proyecto.", "backstory": "Perfil de demostración local.",
                     "dimensiones": [dimensiones.get(rol, rol)]} for rol, nombre in nombres.items()]

    @staticmethod
    def sugerir_panel(proyecto):
        try:
            from backend.delphi.experts import sugerir_panel
            return deepcopy(sugerir_panel(proyecto))
        except ImportError:
            return [{"id": rol, "motivo": "Experto del núcleo fijo del panel."} for rol in NUCLEO]

    @staticmethod
    def parsear_proyecto(texto):
        secciones = {}
        actual = None
        nombre = "Proyecto"
        mapa = {"objetivo": "objetivo", "contexto": "objetivo", "usuarios": "usuarios_volumen", "requisitos funcionales": "requisitos_funcionales",
                "requisitos no funcionales": "requisitos_no_funcionales", "restricciones": "restricciones", "equipo": "equipo",
                "integraciones": "integraciones", "decisiones": "decisiones_a_evaluar"}
        limpio = re.sub(r"<!--.*?-->", "", texto, flags=re.DOTALL)
        for linea in limpio.splitlines():
            if re.match(r"^#\s+", linea):
                nombre = re.sub(r"^#\s+", "", linea).strip() or nombre
            elif re.match(r"^#{2,6}\s+", linea):
                titulo = _normalizar(re.sub(r"^#{2,6}\s+", "", linea))
                actual = next((destino for prefijo, destino in mapa.items() if titulo.startswith(prefijo)), None)
            elif actual:
                valor = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", linea).strip()
                if valor and valor not in "-*+":
                    secciones.setdefault(actual, []).append(valor)
        resultado = {"nombre": nombre, "objetivo": "\n".join(secciones.get("objetivo", [])), "usuarios_volumen": "\n".join(secciones.get("usuarios_volumen", [])),
                     "equipo": "\n".join(secciones.get("equipo", [])), "texto_original": texto}
        for clave in ("requisitos_funcionales", "requisitos_no_funcionales", "restricciones", "integraciones", "decisiones_a_evaluar"):
            resultado[clave] = secciones.get(clave, [])
        if not resultado["objetivo"].strip():
            raise ApiError("El proyecto importado debe incluir una sección 'Objetivo y contexto' con contenido.")
        return resultado

    def _config(self, config):
        if not isinstance(config, dict) or not isinstance(config.get("proyecto"), dict):
            raise ApiError("Se requiere la configuración con un proyecto válido.", 422)
        config = deepcopy(config)
        proyecto = config["proyecto"]
        for campo in ("nombre", "objetivo", "texto_original"):
            if not isinstance(proyecto.get(campo), str) or not proyecto[campo].strip():
                raise ApiError(f"Completa el campo del proyecto: {campo}.", 422)
        for campo in ("requisitos_funcionales", "requisitos_no_funcionales", "restricciones", "integraciones", "decisiones_a_evaluar"):
            proyecto.setdefault(campo, [])
            if not isinstance(proyecto[campo], list) or not all(isinstance(v, str) for v in proyecto[campo]):
                raise ApiError(f"El campo {campo} debe contener una lista de textos.", 422)
        for campo in ("usuarios_volumen", "equipo"):
            proyecto.setdefault(campo, "")
        panel = config.get("expertos")
        validos = {e["id"] for e in self.listar_expertos()}
        if not isinstance(panel, list) or not all(isinstance(v, str) for v in panel) or len(set(panel)) != len(panel) or not 5 <= len(panel) <= 7 or not set(NUCLEO).issubset(panel) or not set(panel).issubset(validos):
            raise ApiError("El panel debe incluir los cinco expertos del núcleo y hasta dos opcionales, sin repeticiones.", 422)
        for clave, valor in {"asignacion_modelos": "auto", "modelos_manual": None, "seed": None, "min_rondas": 2, "max_rondas": 3, "umbral_iqr": 1.0, "umbral_consenso_global": 0.8}.items():
            config.setdefault(clave, valor)
        if config["asignacion_modelos"] not in {"auto", "seed", "manual", "mono"}:
            raise ApiError("La asignación de modelos debe ser auto, seed, manual o mono.", 422)
        if any(not isinstance(config[k], int) or isinstance(config[k], bool) for k in ("min_rondas", "max_rondas")) or not 2 <= config["min_rondas"] <= config["max_rondas"] <= 3:
            raise ApiError("Las rondas deben cumplir 2 ≤ mínimo ≤ máximo ≤ 3.", 422)
        try:
            umbral_valido = 0 <= config["umbral_iqr"] <= 4 and 0 < config["umbral_consenso_global"] <= 1
        except TypeError:
            umbral_valido = False
        if not umbral_valido:
            raise ApiError("Revisa los umbrales de IQR (0 a 4) y consenso global (mayor que 0 y hasta 1).", 422)
        if config["seed"] is not None and (not isinstance(config["seed"], int) or isinstance(config["seed"], bool)):
            raise ApiError("La semilla debe ser un número entero.", 422)
        nombres = {m["nombre"] for m in MODELOS}
        if config["asignacion_modelos"] == "manual":
            manual = config.get("modelos_manual")
            if not isinstance(manual, dict) or set(manual) != set(panel) or not set(manual.values()).issubset(nombres):
                raise ApiError("Asigna un modelo demo disponible a cada experto del panel.", 422)
            if any(a in manual and b in manual and manual[a] == manual[b] for a, b in (("arquitectura", "desarrollo"), ("cloud", "devops"), ("seguridad", "datos"))):
                raise ApiError("Los roles afines deben usar modelos distintos.", 422)
        if config["asignacion_modelos"] == "mono" and config.get("modelos_manual"):
            manual = config["modelos_manual"]
            if not isinstance(manual, dict) or len(set(manual.values())) != 1 or not set(manual.values()).issubset(nombres):
                raise ApiError("El control mono debe usar un único modelo demo disponible.", 422)
        return config

    def crear_run(self, config):
        config = self._config(config)
        informe = construir_informe(config)
        self._contador += 1
        run_id = f"demo-{self._contador:04d}"
        creado = datetime.now(timezone.utc).isoformat()
        self._runs[run_id] = {"estado": {"run_id": run_id, "estado": "en_cola", "ronda_actual": 0, "config": config, "creado": creado, "finalizado": None},
                              "informe": informe, "eventos": construir_eventos(run_id, informe, creado), "visibles": 0}
        return {"run_id": run_id}

    def _buscar(self, run_id):
        if run_id not in self._runs:
            raise ApiError("No se encontró la ejecución solicitada.", 404)
        return self._runs[run_id]

    def listar_runs(self):
        return deepcopy([r["estado"] for r in reversed(list(self._runs.values()))])

    def obtener_run(self, run_id):
        return deepcopy(self._buscar(run_id)["estado"])

    def obtener_eventos(self, run_id, desde=0):
        registro = self._buscar(run_id)
        if self._activo is None:
            siguiente = next((identificador for identificador, run in self._runs.items() if run["estado"]["estado"] == "en_cola"), None)
            self._activo = siguiente
            if siguiente:
                self._runs[siguiente]["estado"]["estado"] = "ejecutando"
        if run_id == self._activo:
            registro["visibles"] = min(registro["visibles"] + 3, len(registro["eventos"]))
            for evento in registro["eventos"][:registro["visibles"]]:
                if evento["ronda"] is not None:
                    registro["estado"]["ronda_actual"] = evento["ronda"]
            if registro["visibles"] == len(registro["eventos"]):
                registro["estado"]["estado"] = "finalizado"
                registro["estado"]["finalizado"] = registro["eventos"][-1]["timestamp"]
                self._activo = None
        return deepcopy([e for e in registro["eventos"][:registro["visibles"]] if e["seq"] > desde])

    def cancelar_run(self, run_id):
        registro = self._buscar(run_id)
        if registro["estado"]["estado"] in {"en_cola", "ejecutando"}:
            registro["eventos"] = registro["eventos"][:registro["visibles"]]
            timestamp = datetime.now(timezone.utc).isoformat()
            registro["eventos"].append({"run_id": run_id, "seq": len(registro["eventos"]) + 1, "timestamp": timestamp, "tipo": "run_cancelado", "ronda": registro["estado"]["ronda_actual"] or None, "payload": {"motivo": "Cancelación solicitada por el usuario.", "simulado": True}})
            registro["visibles"] = len(registro["eventos"])
            registro["estado"].update(estado="cancelado", finalizado=timestamp)
            if self._activo == run_id:
                self._activo = None
        return deepcopy(registro["estado"])

    def obtener_informe(self, run_id, formato="json"):
        registro = self._buscar(run_id)
        if registro["estado"]["estado"] != "finalizado":
            raise ApiError("El informe estará disponible cuando la ejecución termine correctamente.", 409)
        return deepcopy(registro["informe"]) if formato == "json" else informe_markdown(registro["informe"])

    def descargar_adrs(self, run_id):
        informe = self.obtener_informe(run_id)
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archivo:
            for adr in informe["adrs"]:
                slug = re.sub(r"[^a-z0-9]+", "-", _normalizar(adr["titulo"])).strip("-")[:60] or "decision"
                entrada = ZipInfo(f"ADR-{adr['numero']:03d}-{slug}.md", date_time=(2026, 10, 21, 9, 0, 0))
                entrada.compress_type = ZIP_DEFLATED
                archivo.writestr(entrada, adr_markdown(adr).encode("utf-8"))
        return buffer.getvalue()
