import copy
import json
import unittest

from backend.delphi.anonymizer import AnonymizerTool, sanear_argumentos, sintetizar_argumentos


def respuesta(id="E1", puntaje=4, texto="Costo bajo y mantenibilidad", ronda=1):
    return {"experto_id": id, "rol": "arquitectura", "modelo": "Gemini-Jenaro-privado", "ronda": ronda,
            "respuestas": [{"item_id": "ARQ-D1-a", "puntaje": puntaje, "justificacion": texto}],
            "riesgos_detectados": ["Este riesgo no se retransmite como argumento"]}


class AnonymizerTests(unittest.TestCase):
    def test_resume_temas_y_frecuencia_por_postura_sin_perder_disenso(self):
        valores = [respuesta(), respuesta("E2", 5, "Permite bajar costo y presupuesto"),
                   respuesta("E3", 1, "La latencia y el despliegue fallan"), respuesta("E4", 3, "Opinión intermedia")]
        antes = copy.deepcopy(valores)
        resultado = sintetizar_argumentos(valores)[0]
        self.assertTrue(any("costo y presupuesto (2 menciones)" in x for x in resultado["argumentos_a_favor"]))
        self.assertTrue(any("latencia y rendimiento" in x for x in resultado["argumentos_en_contra"]))
        self.assertNotIn("Opinión intermedia", str(resultado))
        self.assertEqual(valores, antes)

    def test_no_filtra_autor_rol_modelo_firma_estilo_ni_texto_desconocido(self):
        texto = "Soy Jenaro, arquitecto, Gemini-Jenaro-privado. ✨ Como E1 recomiendo por sostenibilidad única, firma mariposa."
        resultado = json.dumps(sintetizar_argumentos([respuesta(texto=texto)]), ensure_ascii=False)
        for secreto in ("Jenaro", "arquitecto", "Gemini", "E1", "✨", "mariposa", "sostenibilidad única"):
            self.assertNotIn(secreto, resultado)
        self.assertIn("vocabulario", resultado)

    def test_orden_de_expertos_no_revela_la_identidad(self):
        valores = [respuesta("E1", texto="Costo y plazo"), respuesta("E2", texto="Seguridad y pruebas")]
        self.assertEqual(sintetizar_argumentos(valores), sintetizar_argumentos(list(reversed(valores))))

    def test_cuestionario_valida_pertenencia_e_incluye_items_vacios(self):
        cuestionario = {"items": [{"id": "ARQ-D1-a"}, {"id": "SEG-E1"}]}
        resultado = sintetizar_argumentos([respuesta()], cuestionario)
        self.assertEqual(resultado[1], {"item_id": "SEG-E1", "argumentos_a_favor": [], "argumentos_en_contra": []})
        with self.assertRaises(ValueError):
            sintetizar_argumentos([respuesta()], {"items": [{"id": "SEG-E1"}]})

    def test_rechaza_rondas_mezcladas_y_duplicados(self):
        with self.assertRaises(ValueError):
            sintetizar_argumentos([respuesta(), respuesta("E2", ronda=2)])
        with self.assertRaises(ValueError):
            sintetizar_argumentos([respuesta(), respuesta()])
        valor = respuesta()
        valor["respuestas"] *= 2
        with self.assertRaises(ValueError):
            sintetizar_argumentos([valor])

    def test_valida_puntaje_y_canal_de_identificador(self):
        for puntaje in (0, 6, 2.5, True, "4"):
            with self.subTest(puntaje=puntaje), self.assertRaises(ValueError):
                sintetizar_argumentos([respuesta(puntaje=puntaje)])
        valor = respuesta()
        valor["respuestas"][0]["item_id"] = "Soy-Jenaro"
        with self.assertRaises(ValueError):
            sintetizar_argumentos([valor])

    def test_saneamiento_es_idempotente_y_conserva_frecuencia(self):
        argumentos = sintetizar_argumentos([respuesta(), respuesta("E2")])[0]["argumentos_a_favor"]
        self.assertEqual(sanear_argumentos(argumentos, "favor"), argumentos)
        self.assertTrue(any("2 menciones" in x for x in argumentos))
        self.assertNotIn("Jenaro", str(sanear_argumentos(["Jenaro dice que es barato"], "favor")))

    def test_tool_devuelve_json_compatible_sin_llamadas_llm(self):
        resultado = json.loads(AnonymizerTool().run(respuestas=[respuesta()]))
        self.assertEqual(resultado, sintetizar_argumentos([respuesta()]))

    def test_ids_estructurados_aceptados_por_modelos_y_motor_no_fallan_al_agregar(self):
        from backend.delphi.engine import DelphiEngine, acotar_cuestionario, asegurar_item_viabilidad
        from backend.delphi.experts import get_experto
        from backend.delphi.models import ConfigRun, Cuestionario, Proyecto, RespuestaExperto

        proyecto = Proyecto(nombre="P", objetivo="O", texto_original="# P")
        cuestionario = asegurar_item_viabilidad(acotar_cuestionario(Cuestionario.model_validate({
            "decisiones": [{"id": "ARQ-D01", "dimension": "arquitectura", "titulo": "Estilo", "alternativas": ["Modular"]}],
            "items": [{"id": "ARQ-E01", "tipo": "evaluacion", "dimension": "arquitectura", "pregunta": "¿Viable?"},
                      {"id": "ARQ-D01-A", "tipo": "alternativa", "dimension": "arquitectura", "pregunta": "¿Adecuado?",
                       "decision_id": "ARQ-D01", "alternativa": "Modular"}]})))
        motor = DelphiEngine(lambda _: None)
        prompt = motor._prompt_experto(get_experto("arquitectura"), proyecto, cuestionario, 1, None, None)
        self.assertIn("ARQ-E01", prompt)
        propia = RespuestaExperto(experto_id="E1", rol="arquitectura", modelo="local", ronda=1,
                                 respuestas=[{"item_id": i.id, "puntaje": 4, "justificacion": "Costo y alcance"}
                                             for i in cuestionario.items])
        estadisticas, pct = motor._agregar([propia], cuestionario, ConfigRun(proyecto=proyecto, expertos=["arquitectura"]))
        self.assertEqual({x.item_id for x in estadisticas}, {"ARQ-E01", "ARQ-D01-A", "VIA-E1"})
        self.assertEqual(pct, 1)
        feedback = {"ronda": 1, "porcentaje_consenso": pct, "estadisticas": [x.model_dump() for x in estadisticas]}
        siguiente = motor._prompt_experto(get_experto("arquitectura"), proyecto, cuestionario, 2, propia, feedback)
        self.assertIn("ARQ-D01-A", siguiente)
        self.assertNotIn('"modelo"', siguiente)


if __name__ == "__main__":
    unittest.main()
