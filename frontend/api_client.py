"""Cliente HTTP de README §4.2 y modo demo independiente de FastAPI y de claves LLM.

La aplicación debe conservar una instancia de ApiClient en st.session_state: así
cada sesión tiene su propia cola y sus propias ejecuciones ficticias.
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    """Error de API legible para el usuario, sin detalles de transporte internos."""

    def __init__(self, mensaje: str, status_code: int | None = None):
        super().__init__(mensaje)
        self.status_code = status_code


def _jsonable(valor: Any):
    if hasattr(valor, "model_dump"):
        return valor.model_dump(mode="json")
    if isinstance(valor, dict):
        return {clave: _jsonable(contenido) for clave, contenido in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_jsonable(contenido) for contenido in valor]
    return valor


class ApiClient:
    def __init__(self, use_mocks: bool | None = None, base_url: str | None = None, *, timeout: float = 15.0):
        if use_mocks is None:
            valor = os.getenv("USE_MOCKS", "true").strip().lower()
            if valor not in {"1", "true", "yes", "si", "sí", "0", "false", "no"}:
                raise ApiError("USE_MOCKS debe ser true o false.")
            use_mocks = valor in {"1", "true", "yes", "si", "sí"}
        if not isinstance(use_mocks, bool):
            raise ApiError("use_mocks debe ser un valor booleano.")
        self.use_mocks = use_mocks
        self.base_url = (base_url or os.getenv("API_BASE_URL", "http://localhost:8000")).rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ApiError("API_BASE_URL debe comenzar con http:// o https://.")
        if timeout <= 0:
            raise ApiError("El tiempo de espera de la API debe ser mayor que cero.")
        self.timeout = timeout
        self._mock = None
        if use_mocks:
            from frontend.mocks.service import MockService
            self._mock = MockService()

    def _request(self, metodo, ruta, body=None, *, formato="json"):
        datos = json.dumps(_jsonable(body), ensure_ascii=False).encode("utf-8") if body is not None else None
        request = Request(self.base_url + ruta, data=datos, method=metodo,
                          headers={"Accept": "application/json" if formato == "json" else "text/markdown" if formato == "md" else "application/zip",
                                   **({"Content-Type": "application/json; charset=utf-8"} if datos is not None else {})})
        try:
            with urlopen(request, timeout=self.timeout) as respuesta:
                contenido = respuesta.read()
                content_type = respuesta.headers.get("Content-Type", "")
        except HTTPError as error:
            mensajes = {400: "La API rechazó la solicitud.", 401: "La API requiere autenticación.", 403: "La API no permite esta operación.",
                        404: "No se encontró el recurso solicitado.", 409: "La operación no está disponible en el estado actual.",
                        422: "La API rechazó los datos: revisa los campos enviados.", 429: "La API alcanzó su límite de solicitudes. Intenta nuevamente más tarde."}
            mensaje = mensajes.get(error.code, "La API no pudo completar la solicitud.")
            try:
                detalle = json.loads(error.read().decode("utf-8")).get("detail")
                if isinstance(detalle, str) and detalle.strip():
                    mensaje += " " + detalle[:500]
                elif isinstance(detalle, list):
                    campos = [".".join(str(p) for p in d.get("loc", []) if p != "body") for d in detalle if isinstance(d, dict)]
                    if campos:
                        mensaje += " Campos: " + ", ".join(campos[:8]) + "."
            except (ValueError, UnicodeError, AttributeError):
                pass
            raise ApiError(mensaje, error.code) from None
        except (TimeoutError, socket.timeout):
            raise ApiError("La API tardó demasiado en responder. Revisa el estado antes de reintentar la operación.") from None
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise ApiError("La API tardó demasiado en responder. Revisa el estado antes de reintentar la operación.") from None
            raise ApiError("No se pudo conectar con la API. Comprueba API_BASE_URL y que el backend esté iniciado.") from None
        except OSError:
            raise ApiError("Se interrumpió la conexión con la API. Revisa el estado antes de reintentar la operación.") from None
        if formato == "bytes":
            return contenido
        try:
            texto = contenido.decode("utf-8-sig")
            if formato == "md":
                return json.loads(texto) if "application/json" in content_type else texto
            return json.loads(texto) if texto.strip() else None
        except (ValueError, UnicodeError):
            raise ApiError("La API devolvió una respuesta con formato inválido.") from None

    @staticmethod
    def _ruta_run(run_id):
        if not isinstance(run_id, str) or not run_id.strip():
            raise ApiError("Selecciona una ejecución válida.")
        return "/runs/" + quote(run_id, safe="")

    def listar_modelos(self):
        return self._mock.listar_modelos() if self.use_mocks else self._request("GET", "/modelos")

    def listar_expertos(self):
        return self._mock.listar_expertos() if self.use_mocks else self._request("GET", "/expertos")

    def sugerir_panel(self, proyecto):
        proyecto = _jsonable(proyecto)
        return self._mock.sugerir_panel(proyecto) if self.use_mocks else self._request("POST", "/panel/sugerir", proyecto)

    def parsear_proyecto(self, texto):
        """En demo usa un parser local explícito; producción delega el Markdown a la API.

        El body JSON es la cadena Markdown (README §4.2), no un Proyecto parcial.
        """
        if not isinstance(texto, str) or not texto.strip():
            raise ApiError("El archivo de proyecto está vacío.")
        return self._mock.parsear_proyecto(texto) if self.use_mocks else self._request("POST", "/proyectos/parsear", texto)

    def crear_run(self, config):
        config = _jsonable(config)
        return self._mock.crear_run(config) if self.use_mocks else self._request("POST", "/runs", config)

    def listar_runs(self):
        return self._mock.listar_runs() if self.use_mocks else self._request("GET", "/runs")

    def obtener_run(self, run_id):
        ruta = self._ruta_run(run_id)
        return self._mock.obtener_run(run_id) if self.use_mocks else self._request("GET", ruta)

    def obtener_eventos(self, run_id, desde=0):
        """Devuelve exclusivamente eventos con seq > desde; consultar avanza la demo."""
        ruta = self._ruta_run(run_id)
        if not isinstance(desde, int) or isinstance(desde, bool) or desde < 0:
            raise ApiError("El cursor de eventos debe ser un entero mayor o igual que cero.")
        return self._mock.obtener_eventos(run_id, desde) if self.use_mocks else self._request("GET", ruta + "/eventos?" + urlencode({"desde": desde}))

    def cancelar_run(self, run_id):
        ruta = self._ruta_run(run_id)
        return self._mock.cancelar_run(run_id) if self.use_mocks else self._request("POST", ruta + "/cancelar")

    def obtener_informe(self, run_id, formato="json"):
        ruta = self._ruta_run(run_id)
        if formato not in {"json", "md"}:
            raise ApiError("El formato del informe debe ser json o md.")
        return self._mock.obtener_informe(run_id, formato) if self.use_mocks else self._request("GET", ruta + "/informe?" + urlencode({"formato": formato}), formato=formato)

    def descargar_adrs(self, run_id):
        ruta = self._ruta_run(run_id)
        return self._mock.descargar_adrs(run_id) if self.use_mocks else self._request("GET", ruta + "/adr.zip", formato="bytes")
