"""RAG de la Ley 21.719, memoria institucional y Asesor normativo, sin red ni LLM."""
import json
import zlib

import numpy as np
import pytest

from backend.delphi.asesor import (BuscarAnalisisAnterioresTool, ConsultarLeyTool, GuardarFichaTool,
                                   asesor_simulado, preparar_ficha, verificar_ficha)
from backend.delphi.conocimiento import (DIR_CONOCIMIENTO, BaseConocimiento, IndiceVectorial, cita,
                                         documento_de_informe, documentos_ley)
from tests.test_engine import CONFIG, CONSENSO, _correr, _motor


def embedder_falso(textos):
    """Bolsa de palabras en 256 dimensiones: textos con palabras en común quedan cerca."""
    matriz = np.zeros((len(textos), 256), dtype=np.float32)
    for i, texto in enumerate(textos):
        for palabra in texto.lower().split():
            matriz[i, zlib.crc32(palabra.strip(".,:;()").encode()) % 256] += 1
    return matriz / np.maximum(np.linalg.norm(matriz, axis=1, keepdims=True), 1e-9)


CHUNKS = json.loads((DIR_CONOCIMIENTO / "ley_21719_chunks.json").read_text(encoding="utf-8"))


@pytest.fixture
def base(tmp_path):
    (tmp_path / "con").mkdir()
    IndiceVectorial.construir(documentos_ley(CHUNKS), embedder_falso).guardar(tmp_path / "con" / "indice_ley_21719")
    return BaseConocimiento(embedder_falso, tmp_path / "con", tmp_path / "mem")


def test_los_fragmentos_de_la_ep1_estan_y_se_citan_bien():
    assert len(CHUNKS) == 140
    art = next(c for c in CHUNKS if c["articulo"] == "16" and c.get("articulo_sufijo") == "bis")
    assert cita(art).startswith("Ley 19.628 art. 16 bis (Datos personales sensibles")
    assert "texto según la Ley 21.719" in cita(art)
    assert cita({"nivel1": "segundo", "ambito": "transitorio"}) == "Ley 21.719, artículo segundo transitorio"


def test_busqueda_semantica_y_respaldo_por_palabras(base):
    semantica = base.consultar_ley("datos personales sensibles relativos a la salud")
    assert semantica[0][2] == "semántica" and "16 bis" in semantica[0][1]["cita"]
    sin_red = BaseConocimiento(None, base._base_ley.parent, base._base_memoria.parent)
    palabras = sin_red.consultar_ley("datos personales sensibles relativos a la salud")
    assert palabras[0][2] == "palabras" and "16" in palabras[0][1]["cita"]
    assert all(d["articulo"] == "27" for _, d, _ in base.consultar_ley("transferencia", articulo="27"))


def test_memoria_institucional_recuerda_y_recupera(base):
    informe = _correr(_motor([CONSENSO]))[0]
    base.recordar(informe, "run-1")
    base.recordar(informe, "run-1")                                   # se reemplaza, no se duplica
    assert len(base.memoria.documentos) == 1
    recargada = BaseConocimiento(embedder_falso, base._base_ley.parent, base._base_memoria.parent)
    [(_, doc, modo)] = recargada.buscar_analisis(informe.proyecto.objetivo)
    assert doc["run_id"] == "run-1" and modo == "semántica" and doc["veredicto"] == informe.viabilidad.veredicto
    assert recargada.buscar_analisis("x", excluir_run="run-1") == []
    assert "Decisiones:" in documento_de_informe(informe, "run-1")["texto"]


def test_herramientas_registran_y_escriben(base, tmp_path):
    registro = []
    texto = ConsultarLeyTool(base, registro)._run("datos sensibles de salud", "el proyecto trata historias clínicas")
    assert "[Ley 19.628 art." in texto
    assert registro[0]["herramienta"] == "consultar_ley_21719" and registro[0]["motivo"].startswith("el proyecto")
    assert "no tiene análisis" in BuscarAnalisisAnterioresTool(base, registro)._run("clínicas", "buscar parecidos")
    destino = tmp_path / "run" / "ficha_contexto.md"
    guardar = GuardarFichaTool(registro, destino)
    assert "guardada" in guardar._run("## Ficha", "sí, datos de salud")
    assert destino.read_text(encoding="utf-8").startswith("## Ficha") and guardar.ficha == "## Ficha"
    assert [r["herramienta"] for r in registro] == ["consultar_ley_21719", "buscar_analisis_anteriores", "guardar_ficha"]


def test_verificacion_anti_alucinacion():
    registro = [{"herramienta": "consultar_ley_21719", "resultados": [
        "Ley 19.628 art. 16 bis (Datos personales sensibles relativos a la salud), parte 1/3, texto según la Ley 21.719"]},
        {"herramienta": "buscar_analisis_anteriores", "resultados": []},
        {"herramienta": "guardar_ficha", "resultados": ["ficha"]}]
    buena = "- Salud [Ley 19.628 art. 16 bis (Datos personales sensibles relativos a la salud), parte 1/3]"
    assert verificar_ficha(buena, registro)[1] == []
    assert verificar_ficha("[Artículo 16 bis.- Datos sensibles…]", registro)[1] == []
    ficha, avisos = verificar_ficha(buena + "\n- Multas [Ley 19.628 art. 99 (Inventado)]\n[Artículo 77.- otro]", registro)
    assert "art. 99" in avisos[0] and "Artículo 77" in avisos[0] and "Verificación automática" in ficha
    sin_nada = verificar_ficha("Según un análisis anterior…", [])[1]
    assert any("no consultó la ley" in a for a in sin_nada) and any("no consultó la memoria" in a for a in sin_nada)


def test_el_asesor_es_un_crew_secuencial_de_dos_agentes_con_sus_herramientas(base, monkeypatch, tmp_path):
    """Sin LLM: se reemplaza kickoff por un agente "de mentira" que usa las herramientas como lo haría el real."""
    from crewai import LLM, Crew, Process
    vistos = {}

    def kickoff(self, *a, **k):
        vistos.update(proceso=self.process, roles=[ag.role for ag in self.agents],
                      contexto=self.tasks[1].context == [self.tasks[0]])
        investigador, redactor = (t.agent for t in self.tasks)
        herr = {h.name: h for ag in (investigador, redactor) for h in ag.tools}
        notas = herr["consultar_ley_21719"]._run("datos sensibles de salud", "datos de pacientes")
        herr["buscar_analisis_anteriores"]._run("reservas clínicas", "lecciones")
        primera = notas.split("]")[0] + "]"
        herr["guardar_ficha"]._run(f"## Obligaciones\n- Salud {primera}", "sí")
    monkeypatch.setattr(Crew, "kickoff", kickoff)
    llm = LLM(model="openai/gpt-oss-120b", api_key="no-se-usa", base_url="http://localhost")
    r = preparar_ficha(CONFIG.proyecto, llm, base, tmp_path / "ficha_contexto.md", "run-x")
    assert vistos == {"proceso": Process.sequential, "contexto": True,
                      "roles": ["Investigador normativo y de memoria institucional", "Redactor de la ficha de contexto"]}
    assert [c["herramienta"] for c in r["consultas"]] == ["consultar_ley_21719", "buscar_analisis_anteriores",
                                                          "guardar_ficha"]
    assert r["advertencias"] == [] and (tmp_path / "ficha_contexto.md").exists()


def test_el_motor_usa_la_ficha_del_asesor(base):
    prompts = []

    def ejecutar(moderador_llm, expertos, llms, prendas, **_):
        prompts.extend(prendas.values())
        from tests.test_engine import _salida
        return {e["id"]: _salida(CONSENSO[n]) for n, e in enumerate(expertos)}
    motor = _motor([CONSENSO])
    motor._ejecutar_ronda = ejecutar
    motor._asesor = asesor_simulado(base)
    informe, eventos = _correr(motor)
    evento = next(e for e in eventos if e.tipo == "contexto_preparado")
    assert [c["herramienta"] for c in evento.payload["consultas"]][:2] == ["consultar_ley_21719",
                                                                           "buscar_analisis_anteriores"]
    assert [e.tipo for e in eventos][:4] == ["run_iniciado", "panel_confirmado", "contexto_preparado",
                                             "cuestionario_generado"]
    assert informe.ficha_contexto and all("FICHA DE CONTEXTO" in p for p in prompts)


def test_si_el_asesor_falla_el_analisis_sigue():
    motor = _motor([CONSENSO])

    def falla(proyecto, run_id):
        raise RuntimeError("sin cuota")
    motor._asesor = falla
    informe, eventos = _correr(motor)
    assert informe.ficha_contexto is None and any("Asesor normativo no pudo" in a for a in informe.avisos)
    assert not any(e.tipo == "contexto_preparado" for e in eventos)


def test_los_adr_incluyen_el_contexto_normativo(base):
    motor = _motor([CONSENSO])
    motor._asesor = asesor_simulado(base)
    informe, _ = _correr(motor)
    assert all("Contexto normativo (Ley 21.719" in adr.contexto and "Ley 19.628" in adr.contexto for adr in informe.adrs)
    from backend.delphi.report import renderizar_informe
    assert "## Contexto normativo y memoria institucional" in renderizar_informe(informe)
