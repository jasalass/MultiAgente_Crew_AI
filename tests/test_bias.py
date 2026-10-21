"""Pruebas deterministas de medidas descriptivas y del control mono/auto."""

import csv
import json
from pathlib import Path
import tempfile
import unittest

from backend.delphi.bias import calcular_sesgo
from scripts.experimento_sesgo import comparar_informes, ejecutar_run, guardar_comparacion


def cuestionario():
    return {"decisiones": [], "items": [
        {"id": "E1", "tipo": "evaluacion", "dimension": "gestion", "pregunta": "Viabilidad"},
        {"id": "D1-a", "tipo": "alternativa", "dimension": "arquitectura",
         "pregunta": "Adecuación", "decision_id": "D1", "alternativa": "Monolito"},
    ]}


def respuesta(experto, modelo, puntos, ronda=1):
    return {"experto_id": experto, "modelo": modelo, "ronda": ronda, "rol": "auditoria",
            "respuestas": [{"item_id": item, "puntaje": puntaje, "justificacion": "Razón"}
                           for item, puntaje in puntos.items()]}


def informe(nombre="Proyecto", alternativas="Monolito", estado="firme"):
    return {"proyecto": {"nombre": nombre}, "cuestionario": cuestionario(),
            "rondas": [
                {"ronda": 1, "porcentaje_consenso": .5,
                 "estadisticas": [{"item_id": "E1", "iqr": 2}, {"item_id": "D1-a", "iqr": 1}]},
                {"ronda": 2, "porcentaje_consenso": .8,
                 "estadisticas": [{"item_id": "E1", "iqr": 1}, {"item_id": "D1-a", "iqr": .5}]},
            ], "decisiones": [{"decision_id": "D1", "titulo": "Estilo de arquitectura",
                               "alternativa_recomendada": alternativas, "estado": estado}]}


class BiasTests(unittest.TestCase):
    def test_matched_item_medians_do_not_compare_different_questions(self):
        datos = [respuesta("a", "m1", {"E1": 1, "D1-a": 5}),
                 respuesta("b", "m2", {"E1": 3, "D1-a": 3}),
                 respuesta("c", "m3", {"E1": 5, "D1-a": 1})]
        resultados = {fila["modelo"]: fila for fila in calcular_sesgo(datos, cuestionario())}
        self.assertEqual(resultados["m1"]["puntaje_medio"], 3)
        self.assertEqual(resultados["m1"]["desviacion_vs_mediana_grupo"], 0)
        self.assertEqual(resultados["m1"]["preferencias"], {"Monolito": 2})
        self.assertEqual(resultados["m3"]["preferencias"], {"Monolito": -2})

    def test_incomplete_questionnaires_use_median_of_corresponding_item(self):
        datos = [respuesta("a", "m1", {"E1": 1}), respuesta("b", "m1", {"E1": 3}),
                 respuesta("c", "m2", {"D1-a": 5})]
        resultados = {fila["modelo"]: fila for fila in calcular_sesgo(datos, cuestionario())}
        self.assertEqual(resultados["m1"]["desviacion_vs_mediana_grupo"], 0)
        self.assertEqual(resultados["m2"]["desviacion_vs_mediana_grupo"], 0)

    def test_repeated_rounds_do_not_weight_a_model_more_and_fallback_is_latest(self):
        anterior = respuesta("a", "viejo", {"E1": 1, "D1-a": 1})
        nueva = respuesta("a", "nuevo", {"E1": 5}, ronda=2)
        otro = respuesta("b", "otro", {"E1": 3, "D1-a": 3})
        resultado = calcular_sesgo([nueva, anterior, otro, anterior], cuestionario())
        resultados = {fila["modelo"]: fila for fila in resultado}
        # Solo E1 tiene reemplazo; se conserva D1-a de la ronda anterior.
        self.assertEqual(resultados["nuevo"]["puntaje_medio"], 5)
        self.assertEqual(resultados["nuevo"]["desviacion_vs_mediana_grupo"], 1)
        self.assertEqual(resultados["viejo"]["puntaje_medio"], 1)
        self.assertEqual(resultados["viejo"]["preferencias"], {"Monolito": -1})

    def test_later_rounds_and_duplicate_payloads_preserve_equal_expert_weights(self):
        rondas = [respuesta("a", "m1", {"E1": 1}, ronda=1),
                  respuesta("a", "m1", {"E1": 2}, ronda=2),
                  respuesta("a", "m1", {"E1": 5}, ronda=3),
                  respuesta("b", "m2", {"E1": 1}, ronda=1)]
        final = [rondas[2], rondas[3]]
        self.assertEqual(calcular_sesgo(rondas + rondas, cuestionario()),
                         calcular_sesgo(final, cuestionario()))

    def test_identical_alternative_names_in_distinct_decisions_are_not_merged(self):
        preguntas = cuestionario()
        preguntas["items"].append({"id": "D2-a", "tipo": "alternativa", "decision_id": "D2",
                                   "alternativa": "Monolito"})
        datos = [respuesta("a", "m1", {"D1-a": 5, "D2-a": 1}),
                 respuesta("b", "m2", {"D1-a": 1, "D2-a": 5})]
        resultado = calcular_sesgo(datos, preguntas)[0]
        self.assertEqual(resultado["preferencias"], {"D1 · Monolito": 2, "D2 · Monolito": -2})

    def test_supports_pydantic_style_objects_and_exact_contract_fields(self):
        class Modelo:
            def __init__(self, datos):
                self.datos = datos

            def model_dump(self):
                return self.datos
        datos = [Modelo(respuesta("a", "m1", {"E1": 4}))]
        resultado = calcular_sesgo(datos, Modelo(cuestionario()))[0]
        self.assertEqual(set(resultado), {"modelo", "puntaje_medio",
                                         "desviacion_vs_mediana_grupo", "preferencias"})
        self.assertEqual(resultado["preferencias"], {})
        self.assertEqual(calcular_sesgo([], cuestionario()), [])

    def test_rejects_contradictory_duplicate_round_unknown_item_and_invalid_likert(self):
        with self.assertRaisesRegex(ValueError, "contradictoria"):
            calcular_sesgo([respuesta("a", "m1", {"E1": 1}), respuesta("a", "m1", {"E1": 5})],
                           cuestionario())
        with self.assertRaisesRegex(ValueError, "desconocido"):
            calcular_sesgo([respuesta("a", "m1", {"no_existe": 1})], cuestionario())
        for puntaje in (0, 6, 2.5, True, "3", float("nan")):
            with self.subTest(puntaje=puntaje), self.assertRaises(ValueError):
                calcular_sesgo([respuesta("a", "m1", {"E1": puntaje})], cuestionario())


class ComparacionTests(unittest.TestCase):
    def test_mean_first_round_iqr_and_first_actual_consensus(self):
        mono, auto = informe(), informe()
        mono["rondas"][1]["porcentaje_consenso"] = .79
        mono["rondas"][1]["motivo"] = "estabilidad"
        resultado = comparar_informes(mono, auto)
        self.assertEqual(resultado["iqr_ronda1_mono"], 1.5)
        self.assertIsNone(resultado["rondas_hasta_consenso_mono"])
        self.assertEqual(resultado["rondas_hasta_consenso_auto"], 2)
        self.assertTrue(resultado["cuestionarios_equivalentes"])

    def test_choice_state_and_unpaired_decisions_are_separate(self):
        mono, auto = informe(), informe(alternativas="Serverless", estado="condicionada")
        auto["decisiones"].append({"decision_id": "D2", "titulo": "Base de datos",
                                   "alternativa_recomendada": "SQL", "estado": "firme"})
        resultado = comparar_informes(mono, auto)
        self.assertEqual(resultado["cambios_alternativa"], 1)
        self.assertEqual(resultado["cambios_estado"], 1)
        self.assertEqual(resultado["decisiones_sin_pareja"], 1)
        self.assertEqual(len(resultado["cambios"]), 2)
        auto["decisiones"][0]["alternativa_recomendada"] = "Monolito"
        resultado = comparar_informes(mono, auto)
        self.assertEqual(resultado["cambios_alternativa"], 0)
        self.assertEqual(resultado["cambios_estado"], 1)

    def test_changed_questions_are_flagged_even_with_identical_ids(self):
        mono, auto = informe(), informe()
        auto["cuestionario"]["items"][0]["pregunta"] = "Disponibilidad"
        self.assertFalse(comparar_informes(mono, auto)["cuestionarios_equivalentes"])
        auto["rondas"] = []
        resultado = comparar_informes(mono, auto)
        self.assertIsNone(resultado["iqr_ronda1_auto"])
        self.assertIsNone(resultado["rondas_hasta_consenso_auto"])

    def test_decision_ids_are_not_assumed_semantic_identifiers(self):
        mono, auto = informe(), informe()
        auto["decisiones"][0]["decision_id"] = "OTRA-ID"
        auto["decisiones"][0]["titulo"] = " ESTILO  DE ARQUITECTURA "
        resultado = comparar_informes(mono, auto)
        self.assertEqual(resultado["cambios"], [])
        self.assertEqual(resultado["decisiones_sin_pareja"], 0)

    def test_simulated_exports_are_marked_in_all_artifacts_and_keep_zero(self):
        comparacion = {**comparar_informes(informe(), informe()), "run_mono": "m", "run_auto": "a"}
        comparacion["iqr_ronda1_mono"] = 0.0
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta)
            guardar_comparacion([comparacion], destino, mock=True, evidencias=[])
            markdown = (destino / "comparacion.md").read_text(encoding="utf-8")
            self.assertIn("DATOS SIMULADOS", markdown)
            self.assertIn("0.000", markdown)
            with (destino / "comparacion.csv").open(encoding="utf-8-sig", newline="") as archivo:
                fila = next(csv.DictReader(archivo))
            self.assertIn("SIMULADO", fila["origen"])
            self.assertEqual(fila["cambios_alternativa"], "0")
            evidencia = json.loads((destino / "ejecuciones.json").read_text(encoding="utf-8"))
            self.assertIn("SIMULADO", evidencia["origen"])

    def test_rejects_different_projects_and_ambiguous_decision_titles(self):
        with self.assertRaisesRegex(ValueError, "mismo proyecto"):
            comparar_informes(informe(), informe(nombre="Otro proyecto"))
        ambiguo = informe()
        ambiguo["decisiones"] *= 2
        with self.assertRaisesRegex(ValueError, "ambigua"):
            comparar_informes(ambiguo, informe())


class ClienteFalso:
    def __init__(self, estados):
        self.estados = iter(estados)
        self.cancelados = []
        self.desde = []

    def crear_run(self, config):
        return {"run_id": "prueba"}

    def obtener_eventos(self, run_id, desde=0):
        self.desde.append(desde)
        return [{"seq": len(self.desde), "tipo": "ronda_agregada", "payload": {}}]

    def obtener_run(self, run_id):
        return {"estado": next(self.estados)}

    def obtener_informe(self, run_id, formato="json"):
        return informe()

    def cancelar_run(self, run_id):
        self.cancelados.append(run_id)


class PollingTests(unittest.TestCase):
    def test_polling_advances_event_cursor_until_completed(self):
        cliente = ClienteFalso(["en_cola", "ejecutando", "finalizado"])
        run_id, resultado = ejecutar_run(cliente, {}, intervalo=0)
        self.assertEqual(run_id, "prueba")
        self.assertEqual(resultado["proyecto"]["nombre"], "Proyecto")
        self.assertEqual(cliente.desde, [0, 1, 2])

    def test_error_and_cancel_stop_instead_of_waiting_forever(self):
        for estado in ("error", "cancelado"):
            cliente = ClienteFalso([estado])
            with self.subTest(estado=estado), self.assertRaisesRegex(RuntimeError, estado):
                ejecutar_run(cliente, {}, intervalo=0)
            self.assertEqual(len(cliente.desde), 1)

    def test_timeout_requests_cancellation_without_real_waits(self):
        cliente = ClienteFalso(["ejecutando"])
        tiempo = [0.0]

        def esperar(segundos):
            tiempo[0] += segundos

        with self.assertRaisesRegex(TimeoutError, "cancelación solicitada"):
            ejecutar_run(cliente, {}, timeout=1, intervalo=1,
                         reloj=lambda: tiempo[0], esperar=esperar)
        self.assertEqual(cliente.cancelados, ["prueba"])


if __name__ == "__main__":
    unittest.main()
