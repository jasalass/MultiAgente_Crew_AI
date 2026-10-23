"""Contratos HTTP y coherencia del flujo demo, sin red ni claves de proveedores."""

from copy import deepcopy
from io import BytesIO
import json
import os
from statistics import median, quantiles
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from zipfile import ZipFile

from frontend.api_client import ApiClient, ApiError
from frontend.mocks import ejemplos_proyectos
from frontend.mocks.fixtures import NUCLEO


def config(indice=0, **cambios):
    resultado = {"proyecto": ejemplos_proyectos()[indice], "expertos": list(NUCLEO)}
    resultado.update(cambios)
    return resultado


def terminar(cliente, run_id):
    eventos = []
    for _ in range(100):
        nuevos = cliente.obtener_eventos(run_id, desde=eventos[-1]["seq"] if eventos else 0)
        eventos.extend(nuevos)
        if cliente.obtener_run(run_id)["estado"] == "finalizado":
            return eventos
    raise AssertionError("La ejecución demo no terminó.")


class TestMockApiClient(unittest.TestCase):
    def setUp(self):
        self.cliente = ApiClient(use_mocks=True)

    def test_seed_es_completo_y_auditable(self):
        estado = self.cliente.listar_runs()[0]
        self.assertEqual(estado["estado"], "finalizado")
        informe = self.cliente.obtener_informe(estado["run_id"])
        self.assertEqual(len(informe["decisiones"]), 3)
        self.assertEqual({d["estado"] for d in informe["decisiones"]}, {"firme", "condicionada", "abierta"})
        self.assertEqual(len(informe["adrs"]), 3)
        evaluaciones = [i for i in informe["cuestionario"]["items"] if i["tipo"] == "evaluacion"]
        self.assertEqual(len(evaluaciones), 9)
        self.assertTrue(2 <= len(informe["rondas"]) <= 3)
        self.assertEqual(len(informe["respuestas"]), len(informe["panel"]) * len(informe["rondas"]))
        self.assertGreaterEqual(len(informe["sesgo_por_modelo"]), 2)
        self.assertTrue(any("fictici" in a for a in informe["avisos"]))
        for respuesta in informe["respuestas"]:
            self.assertEqual(respuesta["rol"], informe["panel"][int(respuesta["experto_id"][1:]) - 1])
            self.assertIn("ficticio", respuesta["modelo"])
            self.assertEqual(len(respuesta["respuestas"]), len(informe["cuestionario"]["items"]))

    def test_estadisticas_derivan_de_las_respuestas(self):
        informe = self.cliente.obtener_informe(self.cliente.listar_runs()[0]["run_id"])
        for ronda in informe["rondas"]:
            for estadistica in ronda["estadisticas"]:
                puntajes = [item["puntaje"] for respuesta in informe["respuestas"] if respuesta["ronda"] == ronda["ronda"] for item in respuesta["respuestas"] if item["item_id"] == estadistica["item_id"]]
                q1, _, q3 = quantiles(puntajes, n=4, method="inclusive")
                self.assertEqual(estadistica["mediana"], median(puntajes))
                self.assertEqual(estadistica["iqr"], q3 - q1)
                self.assertEqual(estadistica["consenso"], q3 - q1 <= 1)
            self.assertEqual(ronda["porcentaje_consenso"], sum(e["consenso"] for e in ronda["estadisticas"]) / len(ronda["estadisticas"]))

    def test_run_creado_conserva_proyecto_y_panel_del_usuario(self):
        entrada = config(2, expertos=NUCLEO + ["ia", "gestion"], max_rondas=2)
        entrada["proyecto"]["nombre"] = "Mi marketplace ajustado"
        entrada["proyecto"]["decisiones_a_evaluar"] = ["Catálogo: propio vs gestionado"]
        run_id = self.cliente.crear_run(entrada)["run_id"]
        self.assertEqual(self.cliente.obtener_run(run_id)["estado"], "en_cola")
        terminar(self.cliente, run_id)
        informe = self.cliente.obtener_informe(run_id)
        self.assertEqual(informe["proyecto"], entrada["proyecto"])
        self.assertEqual(informe["panel"], entrada["expertos"])
        self.assertEqual(informe["cuestionario"]["decisiones"][0]["titulo"], "Catálogo: propio vs gestionado")
        self.assertEqual(informe["cuestionario"]["decisiones"][0]["alternativas"], ["propio", "gestionado"])
        self.assertEqual(len(informe["rondas"]), 2)
        self.assertLessEqual(informe["evaluacion_por_dimension"]["gestion"], 2)

    def test_polling_no_duplica_y_estado_no_avanza_por_lectura(self):
        run_id = self.cliente.crear_run(config())["run_id"]
        for _ in range(5):
            self.cliente.obtener_run(run_id)
            self.cliente.listar_runs()
        self.assertEqual(self.cliente.obtener_run(run_id)["estado"], "en_cola")
        eventos = terminar(self.cliente, run_id)
        self.assertEqual([e["seq"] for e in eventos], list(range(1, len(eventos) + 1)))
        self.assertEqual(eventos[0]["tipo"], "run_iniciado")
        self.assertEqual(eventos[-1]["tipo"], "run_finalizado")
        self.assertEqual(self.cliente.obtener_eventos(run_id, eventos[-1]["seq"]), [])
        self.assertEqual(self.cliente.obtener_eventos(run_id), eventos)
        respuestas = [e["payload"]["respuesta"] for e in eventos if e["tipo"] == "respuesta_experto"]
        self.assertEqual(respuestas, self.cliente.obtener_informe(run_id)["respuestas"])

    def test_cola_solo_tiene_un_run_activo(self):
        primero = self.cliente.crear_run(config())["run_id"]
        segundo = self.cliente.crear_run(config(1))["run_id"]
        self.assertEqual(self.cliente.obtener_eventos(segundo), [])
        self.assertEqual(self.cliente.obtener_run(primero)["estado"], "ejecutando")
        self.assertEqual(self.cliente.obtener_run(segundo)["estado"], "en_cola")
        terminar(self.cliente, primero)
        self.assertEqual(self.cliente.obtener_run(segundo)["estado"], "en_cola")
        self.assertTrue(self.cliente.obtener_eventos(segundo))
        self.assertEqual(self.cliente.obtener_run(segundo)["estado"], "ejecutando")

    def test_cancelacion_activa_y_en_cola(self):
        primero = self.cliente.crear_run(config())["run_id"]
        segundo = self.cliente.crear_run(config())["run_id"]
        eventos = self.cliente.obtener_eventos(primero)
        self.cliente.cancelar_run(primero)
        self.cliente.cancelar_run(segundo)
        self.assertEqual(self.cliente.obtener_run(primero)["estado"], "cancelado")
        self.assertEqual(self.cliente.obtener_eventos(primero, eventos[-1]["seq"])[0]["tipo"], "run_cancelado")
        self.assertEqual([e["tipo"] for e in self.cliente.obtener_eventos(segundo)], ["run_cancelado"])
        with self.assertRaises(ApiError) as contexto:
            self.cliente.obtener_informe(primero)
        self.assertEqual(contexto.exception.status_code, 409)

    def test_no_hay_informe_antes_de_terminar(self):
        run_id = self.cliente.crear_run(config())["run_id"]
        with self.assertRaises(ApiError):
            self.cliente.obtener_informe(run_id)
        with self.assertRaises(ApiError):
            self.cliente.descargar_adrs(run_id)

    def test_sesiones_y_datos_devuelto_estan_aislados(self):
        otro = ApiClient(use_mocks=True)
        entrada = config()
        run_id = self.cliente.crear_run(entrada)["run_id"]
        entrada["proyecto"]["nombre"] = "Modificado después de enviar"
        self.assertNotEqual(self.cliente.obtener_run(run_id)["config"]["proyecto"]["nombre"], entrada["proyecto"]["nombre"])
        with self.assertRaises(ApiError):
            otro.obtener_run(run_id)
        estados = self.cliente.listar_runs()
        estados[0]["config"]["proyecto"]["nombre"] = "No persistir"
        self.assertNotEqual(self.cliente.obtener_run(run_id)["config"]["proyecto"]["nombre"], "No persistir")

    def test_mono_y_auto_identificados_como_simulacion(self):
        mono_id = self.cliente.crear_run(config(asignacion_modelos="mono"))["run_id"]
        terminar(self.cliente, mono_id)
        mono = self.cliente.obtener_informe(mono_id)
        self.assertEqual(len({r["modelo"] for r in mono["respuestas"]}), 1)
        self.assertEqual(len(mono["rondas"]), 2)
        self.assertTrue(any("mono-modelo" in aviso for aviso in mono["avisos"]))
        self.assertTrue(any("causal" in aviso for aviso in mono["avisos"]))
        auto = self.cliente.obtener_informe("demo-clinica-finalizado")
        self.assertNotEqual(mono["decisiones"][0]["alternativa_recomendada"], auto["decisiones"][0]["alternativa_recomendada"])

    def test_seed_respeta_parejas_afines(self):
        for semilla in range(3):
            run_id = self.cliente.crear_run(config(expertos=list(reversed(NUCLEO + ["datos"])), asignacion_modelos="seed", seed=semilla))["run_id"]
            terminar(self.cliente, run_id)
            roles = {r["rol"]: r["modelo"] for r in self.cliente.obtener_informe(run_id)["respuestas"]}
            for a, b in (("arquitectura", "desarrollo"), ("cloud", "devops"), ("seguridad", "datos")):
                self.assertNotEqual(roles[a], roles[b])

    def test_rechaza_configuracion_invalida(self):
        for cambios in ({"expertos": NUCLEO + ["ia", "gestion", "ux"]}, {"expertos": NUCLEO[:-1]}, {"min_rondas": 3, "max_rondas": 2}, {"umbral_consenso_global": 80}, {"asignacion_modelos": "invalido"}, {"asignacion_modelos": "manual", "modelos_manual": {}}):
            with self.subTest(cambios=cambios), self.assertRaises(ApiError):
                self.cliente.crear_run(config(**cambios))
        mismos = {rol: self.cliente.listar_modelos()[0]["nombre"] for rol in NUCLEO}
        with self.assertRaises(ApiError):
            self.cliente.crear_run(config(asignacion_modelos="manual", modelos_manual=mismos))

    def test_parseo_local_conserva_plantilla(self):
        for proyecto in ejemplos_proyectos():
            self.assertEqual(self.cliente.parsear_proyecto(proyecto["texto_original"]), proyecto)
        with self.assertRaises(ApiError):
            self.cliente.parsear_proyecto("# Sin objetivo")
        with self.assertRaises(ApiError):
            self.cliente.parsear_proyecto("")

    def test_parseo_demo_ignora_comentarios_e_instrucciones_vacias(self):
        texto = "# Proyecto\n## Objetivo y contexto\n<!-- Instrucción\nen varias líneas -->\nReservar horas.\n## Requisitos funcionales\n-\n- Notificar\n"
        proyecto = self.cliente.parsear_proyecto(texto)
        self.assertEqual(proyecto["objetivo"], "Reservar horas.")
        self.assertEqual(proyecto["requisitos_funcionales"], ["Notificar"])
        self.assertEqual(proyecto["texto_original"], texto)
        with self.assertRaises(ApiError):
            self.cliente.parsear_proyecto("# Plantilla\n## Objetivo\n<!-- Describe aquí el objetivo -->\n")

    def test_viabilidad_deriva_de_sus_respuestas_y_se_exporta(self):
        for indice, esperado in enumerate(("viable", "viable_con_condiciones", "no_viable")):
            for modo in ("auto", "mono"):
                with self.subTest(proyecto=indice, modo=modo):
                    run_id = self.cliente.crear_run(config(indice, asignacion_modelos=modo))["run_id"]
                    terminar(self.cliente, run_id)
                    informe = self.cliente.obtener_informe(run_id)
                    viabilidad = informe["viabilidad"]
                    self.assertEqual(viabilidad["veredicto"], esperado)
                    estadistica = next(e for e in informe["rondas"][-1]["estadisticas"] if e["item_id"] == "VIA-E1")
                    for campo in ("mediana", "iqr", "consenso"):
                        self.assertEqual(viabilidad[campo], estadistica[campo])
                    md = self.cliente.obtener_informe(run_id, "md")
                    self.assertIn("## Viabilidad global", md)
                    self.assertIn(esperado, md)
        run_id = self.cliente.crear_run(config(0, umbral_iqr=0))["run_id"]
        terminar(self.cliente, run_id)
        self.assertEqual(self.cliente.obtener_informe(run_id)["viabilidad"]["veredicto"], "en_discusion")

    def test_exporta_markdown_y_zip_con_tres_adrs(self):
        run_id = "demo-clinica-finalizado"
        md = self.cliente.obtener_informe(run_id, "md")
        self.assertIn("Reservas de una red de clínicas", md)
        for seccion in ("Decisiones", "Riesgos", "Disensos", "Evolución", "Sesgo"):
            self.assertIn(seccion, md)
        with ZipFile(BytesIO(self.cliente.descargar_adrs(run_id))) as archivo:
            self.assertEqual(len(archivo.namelist()), 3)
            for nombre in archivo.namelist():
                self.assertNotIn("/", nombre)
                contenido = archivo.read(nombre).decode("utf-8")
                for seccion in ("Contexto", "Decisión", "Alternativas consideradas", "Consecuencias", "Estado", "Evidencia Delphi"):
                    self.assertIn(seccion, contenido)

    def test_identificador_inexistente_y_cursores_invalidos(self):
        with self.assertRaises(ApiError) as contexto:
            self.cliente.obtener_run("no-existe")
        self.assertEqual(contexto.exception.status_code, 404)
        for cursor in (-1, True, "1"):
            with self.assertRaises(ApiError):
                self.cliente.obtener_eventos("demo-clinica-finalizado", cursor)


class RespuestaHTTP:
    def __init__(self, contenido=b"[]", tipo="application/json"):
        self.contenido = contenido
        self.headers = {"Content-Type": tipo}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.contenido


class TestHttpApiClient(unittest.TestCase):
    def test_interruptor_y_url_desde_entorno(self):
        with patch.dict(os.environ, {"USE_MOCKS": "false", "API_BASE_URL": "http://example.test/api/"}):
            cliente = ApiClient()
            self.assertFalse(cliente.use_mocks)
            self.assertEqual(cliente.base_url, "http://example.test/api")
        with patch.dict(os.environ, {"USE_MOCKS": "true"}):
            self.assertTrue(ApiClient().use_mocks)

    @patch("frontend.api_client.urlopen")
    def test_rutas_metodos_y_payloads_del_contrato(self, abrir):
        abrir.return_value = RespuestaHTTP()
        cliente = ApiClient(False, "http://example.test", timeout=3)
        solicitudes = [
            (lambda: cliente.listar_modelos(), "GET", "/modelos", None),
            (lambda: cliente.listar_expertos(), "GET", "/expertos", None),
            (lambda: cliente.sugerir_panel({"nombre": "Árbol"}), "POST", "/panel/sugerir", {"nombre": "Árbol"}),
            (lambda: cliente.parsear_proyecto("# Clínica\nTexto"), "POST", "/proyectos/parsear", "# Clínica\nTexto"),
            (lambda: cliente.crear_run({"proyecto": {}}), "POST", "/runs", {"proyecto": {}}),
            (lambda: cliente.listar_runs(), "GET", "/runs", None),
            (lambda: cliente.obtener_run("a/b"), "GET", "/runs/a%2Fb", None),
            (lambda: cliente.obtener_eventos("id", 7), "GET", "/runs/id/eventos?desde=7", None),
            (lambda: cliente.cancelar_run("id"), "POST", "/runs/id/cancelar", None),
            (lambda: cliente.obtener_informe("id"), "GET", "/runs/id/informe?formato=json", None),
        ]
        for llamada, metodo, ruta, body in solicitudes:
            llamada()
            request = abrir.call_args.args[0]
            self.assertEqual(request.full_url, "http://example.test" + ruta)
            self.assertEqual(request.get_method(), metodo)
            self.assertEqual(json.loads(request.data.decode("utf-8")) if request.data else None, body)
            self.assertEqual(abrir.call_args.kwargs["timeout"], 3)

    @patch("frontend.api_client.urlopen")
    def test_md_y_zip_preservan_contenido(self, abrir):
        cliente = ApiClient(False)
        abrir.return_value = RespuestaHTTP("# Informe con acentos: clínica".encode(), "text/markdown; charset=utf-8")
        self.assertEqual(cliente.obtener_informe("id", "md"), "# Informe con acentos: clínica")
        abrir.return_value = RespuestaHTTP(b"PK\x00\x01", "application/zip")
        self.assertEqual(cliente.descargar_adrs("id"), b"PK\x00\x01")

    @patch("frontend.api_client.urlopen")
    def test_error_http_normalizado_con_detalle_validacion(self, abrir):
        abrir.side_effect = HTTPError("http://example.test", 422, "Unprocessable", {}, BytesIO(b'{"detail":[{"loc":["body","proyecto","nombre"],"msg":"required"}]}'))
        with self.assertRaises(ApiError) as contexto:
            ApiClient(False).crear_run({})
        self.assertEqual(contexto.exception.status_code, 422)
        self.assertIn("proyecto.nombre", str(contexto.exception))
        abrir.side_effect = HTTPError("http://example.test", 503, "Service unavailable", {}, BytesIO(b"<html>not JSON</html>"))
        with self.assertRaises(ApiError) as contexto:
            ApiClient(False).listar_runs()
        self.assertEqual(contexto.exception.status_code, 503)
        self.assertNotIn("<html>", str(contexto.exception))

    @patch("frontend.api_client.urlopen")
    def test_conexion_timeout_y_json_invalido(self, abrir):
        cliente = ApiClient(False)
        for error, esperado in ((URLError("Connection refused"), "conectar"), (TimeoutError(), "tardó"), (URLError(TimeoutError()), "tardó")):
            abrir.side_effect = error
            with self.assertRaises(ApiError) as contexto:
                cliente.listar_runs()
            self.assertIn(esperado, str(contexto.exception))
        abrir.side_effect = None
        abrir.return_value = RespuestaHTTP(b"<html>backend error</html>")
        with self.assertRaises(ApiError) as contexto:
            cliente.listar_runs()
        self.assertIn("formato inválido", str(contexto.exception))


if __name__ == "__main__":
    unittest.main()
