"""API FastAPI + RunStore con el motor simulado: sin keys ni red."""
import io
import json
import threading
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import ServicioDelphi, crear_app, motor_simulado
from backend.api.store import RunStore
from backend.delphi.experts import NUCLEO
from backend.delphi.models import ConfigRun
from backend.delphi.simulado import pool_simulado
from frontend.api_client import ApiClient
from frontend.mocks import ejemplos_proyectos

RAIZ = Path(__file__).resolve().parents[1]


def _config(**extra):
    return {"proyecto": ejemplos_proyectos()[0], "expertos": list(NUCLEO), **extra}


@pytest.fixture
def servicio(tmp_path):
    pool = pool_simulado()
    return ServicioDelphi(RunStore(tmp_path), pool, motor_simulado(pool))


@pytest.fixture
def api(servicio):
    with TestClient(crear_app(servicio)) as cliente:
        yield cliente


def test_catalogos_parseo_y_sugerencia(api):
    assert {m["familia"] for m in api.get("/modelos").json()} >= {"Familia A (simulada)"}
    assert len(api.get("/expertos").json()) == 10
    texto = (RAIZ / "data" / "proyectos" / "marketplace_ia.md").read_text(encoding="utf-8")
    proyecto = api.post("/proyectos/parsear", json=texto).json()
    assert proyecto["nombre"] == "Marketplace con IA generativa" and proyecto["texto_original"] == texto
    assert {s["id"] for s in api.post("/panel/sugerir", json=proyecto).json()} >= set(NUCLEO)
    assert api.post("/proyectos/parsear", json="# Sin objetivo").status_code == 422


def test_run_completo_eventos_informe_y_adr(api, servicio):
    run_id = api.post("/runs", json=_config()).json()["run_id"]
    servicio.esperar_cola()
    estado = api.get(f"/runs/{run_id}").json()
    assert estado["estado"] == "finalizado" and estado["ronda_actual"] >= 2
    eventos = api.get(f"/runs/{run_id}/eventos").json()
    assert eventos[0]["tipo"] == "run_iniciado" and eventos[-1]["tipo"] == "run_finalizado"
    assert [e["seq"] for e in api.get(f"/runs/{run_id}/eventos", params={"desde": 3}).json()][0] == 4
    informe = api.get(f"/runs/{run_id}/informe").json()
    assert informe["decisiones"] and any("simulada" in a for a in informe["avisos"])
    md = api.get(f"/runs/{run_id}/informe", params={"formato": "md"})
    assert md.headers["content-type"].startswith("text/markdown") and informe["proyecto"]["nombre"] in md.text
    with zipfile.ZipFile(io.BytesIO(api.get(f"/runs/{run_id}/adr.zip").content)) as z:
        assert len(z.namelist()) == len(informe["adrs"]) and z.namelist()[0].startswith("ADR-001")
    assert [r["run_id"] for r in api.get("/runs").json()] == [run_id]


def test_errores_http(api):
    assert api.get("/runs/no-existe").status_code == 404
    assert api.post("/runs", json=_config(expertos=["arquitectura", "cloud"])).status_code == 422
    assert api.post("/runs", json=_config(min_rondas=3, max_rondas=2)).status_code == 422
    manual = {e: "simulado-a" for e in NUCLEO}               # roles afines con el mismo modelo
    assert api.post("/runs", json=_config(asignacion_modelos="manual", modelos_manual=manual)).status_code == 422


def test_cancelar_en_cola_y_durante_la_ejecucion(tmp_path):
    pool = pool_simulado()
    liberar, empezo = threading.Event(), threading.Event()
    base = motor_simulado(pool)

    def crear(config):                                     # el primer run se bloquea en su 1.ª ronda
        motor = base(config)
        ejecutar = motor._ejecutar_ronda

        def lento(*a, **k):
            empezo.set()
            liberar.wait(5)
            return ejecutar(*a, **k)
        motor._ejecutar_ronda = lento
        return motor
    servicio = ServicioDelphi(RunStore(tmp_path), pool, crear)
    with TestClient(crear_app(servicio)) as api:
        primero = api.post("/runs", json=_config()).json()["run_id"]
        segundo = api.post("/runs", json=_config()).json()["run_id"]
        assert empezo.wait(5)
        assert api.post(f"/runs/{segundo}/cancelar").json()["estado"] == "cancelado"
        api.post(f"/runs/{primero}/cancelar")
        liberar.set()
        servicio.esperar_cola()
        assert api.get(f"/runs/{primero}").json()["estado"] == "cancelado"
        assert api.get(f"/runs/{primero}/eventos").json()[-1]["tipo"] == "run_cancelado"
        assert api.get(f"/runs/{segundo}/informe").status_code == 409


def test_el_historial_sobrevive_al_reinicio(tmp_path):
    store = RunStore(tmp_path)
    estado = store.crear(ConfigRun(**_config()))
    store.actualizar(estado.run_id, estado="ejecutando")
    recargado = RunStore(tmp_path)                          # el servidor se cayó a mitad del run
    assert recargado.obtener(estado.run_id).estado == "error"
    assert recargado.eventos(estado.run_id)[-1].tipo == "error"
    assert json.loads((tmp_path / estado.run_id / "estado.json").read_text(encoding="utf-8"))["estado"] == "error"


def test_el_cliente_del_frontend_funciona_contra_la_api_real(api, servicio, monkeypatch):
    """El ApiClient de Jenaro (urllib) contra la API, enrutado al TestClient."""
    from urllib.error import HTTPError

    class Respuesta(io.BytesIO):
        def __init__(self, r):
            super().__init__(r.content)
            self.headers = r.headers

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def urlopen(request, timeout):
        ruta = request.full_url.removeprefix("http://api")
        r = api.request(request.get_method(), ruta, content=request.data, headers=dict(request.header_items()))
        if r.status_code >= 400:
            raise HTTPError(request.full_url, r.status_code, "error", r.headers, io.BytesIO(r.content))
        return Respuesta(r)
    monkeypatch.setattr("frontend.api_client.urlopen", urlopen)
    cliente = ApiClient(use_mocks=False, base_url="http://api")
    proyecto = cliente.parsear_proyecto((RAIZ / "data" / "proyectos" / "clinica_reservas.md").read_text(encoding="utf-8"))
    panel = [s["id"] for s in cliente.sugerir_panel(proyecto)]
    run_id = cliente.crear_run({"proyecto": proyecto, "expertos": panel, "asignacion_modelos": "mono"})["run_id"]
    servicio.esperar_cola()
    assert cliente.obtener_run(run_id)["estado"] == "finalizado"
    assert cliente.obtener_eventos(run_id, desde=0)
    informe = cliente.obtener_informe(run_id)
    assert "panel mono-modelo: riesgo de falso consenso" in informe["avisos"]
    assert cliente.obtener_informe(run_id, formato="md").startswith("#")
    assert cliente.descargar_adrs(run_id)[:2] == b"PK"


def test_asesor_y_memoria_de_largo_plazo_en_la_api(tmp_path):
    """Dos análisis seguidos: el segundo encuentra al primero en la memoria institucional."""
    from backend.delphi.asesor import asesor_simulado
    from backend.delphi.conocimiento import BaseConocimiento
    base = BaseConocimiento(None, dir_memoria=tmp_path / "memoria")          # índice real de la ley, por palabras
    pool = pool_simulado()
    servicio = ServicioDelphi(RunStore(tmp_path / "runs"), pool, motor_simulado(pool, asesor=asesor_simulado(base)), base)
    with TestClient(crear_app(servicio)) as api:
        primero = api.post("/runs", json=_config()).json()["run_id"]
        servicio.esperar_cola()
        segundo = api.post("/runs", json=_config()).json()["run_id"]
        servicio.esperar_cola()
        eventos = api.get(f"/runs/{segundo}/eventos").json()
        contexto = next(e for e in eventos if e["tipo"] == "contexto_preparado")["payload"]
        memoria = next(c for c in contexto["consultas"] if c["herramienta"] == "buscar_analisis_anteriores")
        assert memoria["resultados"] == [ejemplos_proyectos()[0]["nombre"]]     # recordó el primer análisis
        assert "Ley 19.628" in api.get(f"/runs/{segundo}/informe").json()["ficha_contexto"]
        assert len(base.memoria.documentos) == 2 and primero != segundo
