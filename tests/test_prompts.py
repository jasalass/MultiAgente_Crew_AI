import copy
import json
import unittest

from backend.delphi.prompts import construir_prompt_ronda_1, construir_prompt_ronda_k, guard_independencia


PROYECTO = {"nombre": "Reservas", "objetivo": "Reservar atención", "texto_original": "# Reservas"}
CUESTIONARIO = {"decisiones": [], "items": [
    {"id": "ARQ-E1", "dimension": "arquitectura", "tipo": "evaluacion", "pregunta": "¿Es viable?"}]}
ANTERIOR = {"experto_id": "E1", "rol": "arquitectura", "modelo": "MODELO_PRIVADO", "ronda": 1,
            "respuestas": [{"item_id": "ARQ-E1", "puntaje": 2, "justificacion": "Falta presupuesto"}],
            "riesgos_detectados": ["Equipo insuficiente"]}
FEEDBACK = {"ronda": 1, "estadisticas": [{"item_id": "ARQ-E1", "mediana": 4, "q1": 3, "q3": 4,
            "iqr": 1, "consenso": True, "argumentos_a_favor": ["Pamela con Gemini afirma que el costo es bajo"],
            "argumentos_en_contra": []}], "porcentaje_consenso": 1, "motivo": "Juan con Qwen pide seguir"}


def contexto_del_prompt(prompt):
    return json.loads(prompt.split("CONTEXTO AUTORIZADO (JSON):\n")[1].split("\n\nDevuelve SOLO JSON")[0])


class PromptsTests(unittest.TestCase):
    def test_ronda_inicial_solo_proyecto_y_cuestionario(self):
        prompt = construir_prompt_ronda_1("arquitectura", PROYECTO, CUESTIONARIO)
        contexto = contexto_del_prompt(prompt)
        self.assertEqual(set(contexto), {"proyecto", "cuestionario", "ronda"})
        self.assertIn("riesgos_detectados", prompt)
        self.assertIn("1 a 3 frases", prompt)
        self.assertTrue(guard_independencia(contexto))

    def test_ronda_posterior_conserva_solo_respuesta_propia_y_feedback_neutral(self):
        prompt = construir_prompt_ronda_k("arquitectura", PROYECTO, CUESTIONARIO, ANTERIOR, FEEDBACK)
        contexto = contexto_del_prompt(prompt)
        self.assertEqual(contexto["ronda"], 2)
        self.assertEqual(contexto["respuesta_anterior"]["respuestas"], ANTERIOR["respuestas"])
        for secreto in ("MODELO_PRIVADO", "Gemini", "Pamela", "Juan", "Qwen", '"experto_id"', '"rol"', '"modelo"'):
            self.assertNotIn(secreto, prompt)
        self.assertIn("fuera del intervalo inclusivo [Q1, Q3]", prompt)
        self.assertIn("mantienes o cambias", prompt)
        self.assertIn("costo y presupuesto", prompt)
        self.assertTrue(guard_independencia(contexto))

    def test_guard_rechaza_contexto_compartido_aunque_este_anidado(self):
        contexto = contexto_del_prompt(construir_prompt_ronda_1("arquitectura", PROYECTO, CUESTIONARIO))
        for clave in ("panel", "respuestas", "modelos", "context"):
            alterado = copy.deepcopy(contexto)
            alterado[clave] = []
            with self.subTest(clave=clave), self.assertRaises(ValueError):
                guard_independencia(alterado)
        alterado = copy.deepcopy(contexto)
        alterado["cuestionario"]["items"][0]["modelo"] = "secreto"
        with self.assertRaises(ValueError):
            guard_independencia(alterado)
        alterado = copy.deepcopy(contexto)
        alterado["proyecto"]["objetivo"] = {"modelo": "secreto"}
        with self.assertRaises(ValueError):
            guard_independencia(alterado)

    def test_rechaza_respuesta_de_otro_rol_o_ronda_incoherente(self):
        anterior = copy.deepcopy(ANTERIOR)
        anterior["rol"] = "seguridad"
        with self.assertRaises(ValueError):
            construir_prompt_ronda_k("arquitectura", PROYECTO, CUESTIONARIO, anterior, FEEDBACK)
        with self.assertRaises(ValueError):
            construir_prompt_ronda_k("arquitectura", PROYECTO, CUESTIONARIO, ANTERIOR, FEEDBACK, ronda=3)

    def test_rechaza_feedback_que_incluya_metadatos_individuales(self):
        feedback = copy.deepcopy(FEEDBACK)
        feedback["estadisticas"][0]["rol"] = "seguridad"
        with self.assertRaises(ValueError):
            construir_prompt_ronda_k("arquitectura", PROYECTO, CUESTIONARIO, ANTERIOR, feedback)

    def test_rechaza_feedback_incompleto_y_cuartiles_incoherentes(self):
        feedback = copy.deepcopy(FEEDBACK)
        feedback["estadisticas"] = []
        with self.assertRaises(ValueError):
            construir_prompt_ronda_k("arquitectura", PROYECTO, CUESTIONARIO, ANTERIOR, feedback)
        feedback = copy.deepcopy(FEEDBACK)
        feedback["estadisticas"][0]["iqr"] = 9
        with self.assertRaises(ValueError):
            construir_prompt_ronda_k("arquitectura", PROYECTO, CUESTIONARIO, ANTERIOR, feedback)

    def test_no_modifica_entradas(self):
        valores = copy.deepcopy((PROYECTO, CUESTIONARIO, ANTERIOR, FEEDBACK))
        construir_prompt_ronda_k("arquitectura", *valores)
        self.assertEqual(valores, (PROYECTO, CUESTIONARIO, ANTERIOR, FEEDBACK))


if __name__ == "__main__":
    unittest.main()
