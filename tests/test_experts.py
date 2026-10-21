import unittest

from backend.delphi.experts import NUCLEO, get_experto, listar_expertos, sugerir_panel


class ProyectoSimilarAPydantic:
    def model_dump(self):
        return {"nombre": "Asistente", "objetivo": "RAG con LLM", "restricciones": ["3 meses", "equipo junior"]}


class ExpertsTests(unittest.TestCase):
    def test_catalogo_corresponde_al_contrato_y_tiene_prioridades_distintas(self):
        catalogo = listar_expertos()
        self.assertEqual(len(catalogo), 10)
        self.assertEqual({x["id"] for x in catalogo},
                         {"arquitectura", "cloud", "desarrollo", "seguridad", "devops", "datos", "qa", "ux", "gestion", "ia"})
        self.assertEqual(len(NUCLEO), 5)
        for experto in catalogo:
            self.assertEqual(set(experto), {"id", "nombre", "tipo", "role", "goal", "backstory", "dimensiones"})
            self.assertIn("Prioridad y sesgo explícito:", experto["backstory"])
            self.assertGreaterEqual(experto["backstory"].count("¿"), 3)
        self.assertEqual(len({x["goal"] for x in catalogo}), 10)

    def test_catalogo_no_comparte_estado_mutable(self):
        catalogo = listar_expertos()
        catalogo[0]["dimensiones"].clear()
        catalogo[0]["nombre"] = "alterado"
        self.assertNotEqual(get_experto("arquitectura")["nombre"], "alterado")
        self.assertTrue(get_experto("arquitectura")["dimensiones"])
        with self.assertRaises(ValueError):
            get_experto("inventado")

    def test_sin_senales_solo_nucleo_y_no_confunde_api_con_ia(self):
        panel = sugerir_panel({"objetivo": "API para procesos internos de oficina"})
        self.assertEqual([x["id"] for x in panel], list(NUCLEO))
        self.assertTrue(all(x["motivo"] for x in panel))

    def test_prioriza_ia_y_gestion_con_panel_limitado(self):
        proyecto = ProyectoSimilarAPydantic()
        panel = sugerir_panel(proyecto)
        self.assertEqual([x["id"] for x in panel[5:]], ["gestion", "ia"])
        self.assertEqual(len(panel), 7)
        self.assertEqual(panel, sugerir_panel(proyecto))

    def test_migracion_y_accesibilidad_tienen_motivos_especificos(self):
        panel = sugerir_panel({"objetivo": "Migración de ERP con millones de transacciones, WCAG y accesibilidad"})
        self.assertEqual({x["id"] for x in panel[5:]}, {"datos", "ux"})
        self.assertIn("migración", panel[5]["motivo"])

    def test_repetir_texto_no_modifica_la_prioridad(self):
        proyecto = {"objetivo": "LLM, migración de datos, app móvil"}
        panel = sugerir_panel(proyecto)
        proyecto["texto_original"] = (proyecto["objetivo"] + " ") * 30
        self.assertEqual(panel, sugerir_panel(proyecto))

    def test_ciclo_de_vida_no_implica_riesgo_vital(self):
        panel = sugerir_panel({"objetivo": "Gestionar el ciclo de vida del inventario"})
        self.assertNotIn("qa", {x["id"] for x in panel})
        panel = sugerir_panel({"objetivo": "Sistema de soporte vital"})
        self.assertIn("qa", {x["id"] for x in panel})

    def test_exclusion_explicita_de_ia_no_consume_un_cupo(self):
        for objetivo in ("Aplicación sin IA", "API que no utiliza inteligencia artificial", "Portal sin IA ni LLM"):
            with self.subTest(objetivo=objetivo):
                self.assertNotIn("ia", {x["id"] for x in sugerir_panel({"objetivo": objetivo})})
        panel = sugerir_panel({"objetivo": "Sin IA generativa; sí usamos machine learning"})
        self.assertIn("ia", {x["id"] for x in panel})

    def test_falta_de_experiencia_en_ia_es_una_senal_positiva(self):
        panel = sugerir_panel({"objetivo": "Equipo sin experiencia en IA implementa un asistente"})
        self.assertEqual({x["id"] for x in panel[5:]}, {"gestion", "ia"})


if __name__ == "__main__":
    unittest.main()
