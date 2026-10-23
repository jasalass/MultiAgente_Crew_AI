"""Frontend → HTTP → FastAPI → motor real → disco, con LLM falsos.

Un puerto local efímero evita depender de servidores previos. No utiliza keys
ni hace peticiones a proveedores de modelos.
"""
from io import BytesIO
from pathlib import Path
import socket
import threading
import time
from zipfile import ZipFile

import pytest
import uvicorn
from streamlit.testing.v1 import AppTest

from backend.api.main import ServicioDelphi, crear_app, motor_simulado
from backend.api.store import RunStore
from backend.delphi.experts import NUCLEO
from backend.delphi.models import InformeDelphi
from backend.delphi.project_loader import cargar_proyecto
from backend.delphi.simulado import pool_simulado
from frontend.api_client import ApiClient, ApiError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def api_viva(tmp_path_factory):
    pool = pool_simulado()
    servicio = ServicioDelphi(RunStore(tmp_path_factory.mktemp("delphi_http")),
                              pool, motor_simulado(pool, pausa=.01))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    puerto = listener.getsockname()[1]
    servidor = uvicorn.Server(uvicorn.Config(crear_app(servicio), log_level="error"))
    hilo = threading.Thread(target=servidor.run, kwargs={"sockets": [listener]}, daemon=True)
    hilo.start()
    limite = time.monotonic() + 15
    try:
        while not servidor.started and hilo.is_alive() and time.monotonic() < limite:
            time.sleep(.01)
        assert servidor.started, "La API de prueba no pudo iniciar."
        yield f"http://127.0.0.1:{puerto}", servicio
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5)
        listener.close()


def esperar(api, run_id, timeout=20):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        estado = api.obtener_run(run_id)
        if estado["estado"] in {"finalizado", "cancelado", "error"}:
            return estado
        time.sleep(.02)
    pytest.fail("La ejecución no terminó dentro del plazo de prueba.")


def configuracion(api, proyecto, modo="auto"):
    return dict(proyecto=proyecto, expertos=[e["id"] for e in api.sugerir_panel(proyecto)],
                asignacion_modelos=modo, min_rondas=2, max_rondas=3, seed=7)


def test_tres_proyectos_por_http_eventos_descargas_y_persistencia(api_viva):
    url, servicio = api_viva
    api = ApiClient(use_mocks=False, base_url=url)
    assert len(api.listar_expertos()) == 10
    assert len(api.listar_modelos()) == 3
    for ruta in sorted((ROOT / "data" / "proyectos").glob("*.md")):
        texto = ruta.read_text(encoding="utf-8")
        proyecto = api.parsear_proyecto(texto)
        assert proyecto["texto_original"] == texto
        run_id = api.crear_run(configuracion(api, proyecto))["run_id"]
        assert esperar(api, run_id)["estado"] == "finalizado"
        informe = api.obtener_informe(run_id)
        InformeDelphi.model_validate(informe)
        assert informe["viabilidad"] and any("simulada" in a.lower() for a in informe["avisos"])
        assert len(informe["rondas"]) >= 2
        eventos = api.obtener_eventos(run_id)
        assert [e["seq"] for e in eventos] == sorted({e["seq"] for e in eventos})
        assert eventos[-1]["tipo"] == "run_finalizado"
        assert api.obtener_eventos(run_id, desde=eventos[-1]["seq"]) == []
        assert len([e for e in eventos if e["tipo"] == "respuesta_experto"]) == len(informe["respuestas"])
        assert "viabilidad" in api.obtener_informe(run_id, "md").casefold()
        with ZipFile(BytesIO(api.descargar_adrs(run_id))) as adrs:
            assert len(adrs.namelist()) == len(informe["decisiones"])
            assert all("#" in adrs.read(n).decode("utf-8") for n in adrs.namelist())
        recuperado = RunStore(servicio.store._raiz).informe(run_id)
        assert recuperado.proyecto.nombre == proyecto["nombre"]


def test_cancelacion_y_error_de_formulario_por_http(api_viva):
    url, _ = api_viva
    api = ApiClient(use_mocks=False, base_url=url)
    proyecto = cargar_proyecto(ROOT / "data" / "proyectos" / "clinica_reservas.md").model_dump()
    config = configuracion(api, proyecto)
    invalida = {**config, "expertos": list(NUCLEO)[:-1]}
    with pytest.raises(ApiError) as error:
        api.crear_run(invalida)
    assert error.value.status_code == 422
    run_id = api.crear_run(config)["run_id"]
    api.cancelar_run(run_id)
    assert esperar(api, run_id)["estado"] == "cancelado"
    assert api.obtener_eventos(run_id)[-1]["tipo"] == "run_cancelado"
    with pytest.raises(ApiError) as error:
        api.obtener_informe(run_id)
    assert error.value.status_code == 409


def test_streamlit_con_api_real_de_principio_a_fin(api_viva, monkeypatch):
    url, _ = api_viva
    api = ApiClient(use_mocks=False, base_url=url)
    proyecto = cargar_proyecto(ROOT / "data" / "proyectos" / "clinica_reservas.md").model_dump()
    anterior = api.crear_run(configuracion(api, proyecto, modo="mono"))["run_id"]
    assert esperar(api, anterior)["estado"] == "finalizado"
    monkeypatch.setenv("USE_MOCKS", "false")
    monkeypatch.setenv("API_BASE_URL", url)
    app = AppTest.from_file(str(ROOT / "frontend" / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.session_state["api_client"].use_mocks is False
    app.button("iniciar_analisis").click().run()
    assert not app.exception
    run_id = app.session_state["active_run"]
    assert esperar(app.session_state["api_client"], run_id)["estado"] == "finalizado"
    app.switch_page("pages/2_En_vivo.py").run()
    assert not app.exception
    assert any("panel y cuestionario listos" in e.label for e in app.expander)
    assert any("con sus alternativas" in c.value for c in app.caption)
    assert not any("Rol:" in c.value for c in app.caption)
    app.toggle[0].set_value(True).run()
    assert not app.exception
    assert any("Rol:" in c.value for c in app.caption)
    app.switch_page("pages/3_Decisiones.py").run()
    assert not app.exception
    assert len(app.get("download_button")) == 3
    assert len(app.get("plotly_chart")) == 3
    assert any("viabilidad" in c.value.casefold() for c in app.caption)
    app.switch_page("pages/4_Historial.py").run()
    assert not app.exception
    assert any(d.label == "Segundo análisis" for d in app.selectbox)
