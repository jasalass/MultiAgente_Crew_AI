"""Verifica formularios y navegación de la demo, sin APIs ni credenciales."""
from pathlib import Path
import pytest
from frontend.validation import proyecto_a_markdown, validar_config

ROOT = Path(__file__).resolve().parents[1]


def config_valida():
    return {"proyecto": {"nombre": "Reservas", "objetivo": "Reservar horas", "texto_original": "# Reservas"},
            "expertos": ["arquitectura", "cloud", "desarrollo", "seguridad", "devops"],
            "asignacion_modelos": "auto", "min_rondas": 2, "max_rondas": 3,
            "umbral_iqr": 1., "umbral_consenso_global": .8}


def test_config_valida_y_nucleo_obligatorio():
    config = config_valida()
    assert validar_config(config) == []
    config["expertos"] = ["arquitectura", "cloud", "desarrollo", "seguridad", "datos"]
    assert any("núcleo" in e for e in validar_config(config))


def test_modelos_afines_y_control_mono():
    config = config_valida()
    modelos = [{"nombre": "a", "familia": "a"}, {"nombre": "b", "familia": "b"}]
    config.update(asignacion_modelos="manual", modelos_manual={r: "a" for r in config["expertos"]})
    assert any("distintos" in e for e in validar_config(config, modelos))
    config["asignacion_modelos"] = "mono"
    assert validar_config(config, modelos) == []
    config["modelos_manual"]["cloud"] = "desconocido"
    assert any("disponible" in e for e in validar_config(config, modelos))


def test_reglas_y_plantilla():
    config = config_valida()
    config.update(min_rondas=3, max_rondas=2, umbral_consenso_global=0)
    assert len(validar_config(config)) == 2
    texto = proyecto_a_markdown({"nombre": "Portal", "objetivo": "Atender usuarios", "restricciones": ["6 meses"]})
    assert "# Portal" in texto and "## Restricciones\n\n- 6 meses" in texto


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("USE_MOCKS", "true")
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(str(ROOT / "frontend" / "app.py"), default_timeout=30).run()


def test_formulario_y_ejecucion_demo(app):
    assert not app.exception
    app.button("iniciar_analisis").click().run()
    assert not app.exception
    assert app.session_state["active_run"]
    # Cada polling avanza un paso de la simulación; las reruns conservan el cliente.
    for _ in range(80):
        app.run()
        estado = app.session_state["api_client"].obtener_run(app.session_state["active_run"])
        if estado["estado"] == "finalizado":
            break
    assert estado["estado"] == "finalizado"
    app.switch_page("pages/3_Decisiones.py").run()
    assert not app.exception
    assert len(app.get("download_button")) == 3
    assert len(app.get("plotly_chart")) == 3


def test_historial_sin_error(app):
    app.switch_page("pages/4_Historial.py").run()
    assert not app.exception
    assert len(app.dataframe) >= 1


def test_resultados_y_auditoria(app):
    app.switch_page("pages/3_Decisiones.py").run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 3
    app.switch_page("pages/2_En_vivo.py").run()
    assert not app.exception
    assert app.toggle[0].value is False
    assert not any("Rol:" in c.value for c in app.caption)
    app.toggle[0].set_value(True).run()
    assert not app.exception
    assert any("Rol:" in c.value for c in app.caption)


def test_nuevo_run_seleccionado_tras_visitar_en_vivo(app):
    app.switch_page("pages/2_En_vivo.py").run()
    assert app.selectbox[0].value == "demo-clinica-finalizado"
    app.switch_page("pages/1_Nuevo.py").run()
    original = next(t for t in app.text_area if t.label == "Documento completo del proyecto")
    texto = original.value + "\n\n## Contexto adicional\nConservar este detalle."
    original.set_value(texto).run()
    app.button("iniciar_analisis").click().run()
    assert not app.exception
    activo = app.session_state["active_run"]
    assert app.selectbox[0].value == activo
    assert app.session_state["api_client"].obtener_run(activo)["config"]["proyecto"]["texto_original"] == texto
