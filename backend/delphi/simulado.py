"""Motor Delphi con LLM falsos y deterministas: el flujo completo sin keys ni red.

Lo usan la CLI (--mock), la API con DELPHI_SIMULADO=true y los tests. Las respuestas
son ficticias: sirven para probar contratos, eventos y persistencia, no para sacar
conclusiones sobre modelos.
"""
from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any

from backend.delphi.config import Bloque, ModelPool

CUESTIONARIO = {
    "decisiones": [{"id": "ARQ-D1", "dimension": "arquitectura", "titulo": "Estilo de arquitectura",
                    "alternativas": ["Monolito modular", "Microservicios"]},
                   {"id": "INF-D1", "dimension": "infraestructura", "titulo": "Proveedor cloud",
                    "alternativas": ["AWS", "Azure"]}],
    "items": [
        {"id": "ARQ-E1", "dimension": "arquitectura", "tipo": "evaluacion", "pregunta": "¿Es viable el plazo?"},
        {"id": "SEG-E1", "dimension": "seguridad", "tipo": "evaluacion", "pregunta": "¿Se protegen los datos personales?"},
        {"id": "ARQ-D1-a", "dimension": "arquitectura", "tipo": "alternativa", "pregunta": "¿Adecuada?",
         "decision_id": "ARQ-D1", "alternativa": "Monolito modular"},
        {"id": "ARQ-D1-b", "dimension": "arquitectura", "tipo": "alternativa", "pregunta": "¿Adecuada?",
         "decision_id": "ARQ-D1", "alternativa": "Microservicios"},
        {"id": "INF-D1-a", "dimension": "infraestructura", "tipo": "alternativa", "pregunta": "¿Adecuado?",
         "decision_id": "INF-D1", "alternativa": "AWS"},
        {"id": "INF-D1-b", "dimension": "infraestructura", "tipo": "alternativa", "pregunta": "¿Adecuado?",
         "decision_id": "INF-D1", "alternativa": "Azure"}]}
BASE = {"ARQ-E1": 4, "SEG-E1": 3, "ARQ-D1-a": 5, "ARQ-D1-b": 2, "INF-D1-a": 4, "INF-D1-b": 4,
        "VIA-E1": 3}                         # viabilidad global: la agrega el motor
JUSTIFICACIONES = ["Prioriza mantenibilidad y separación de responsabilidades.",
                   "Reduce la superficie de ataque y el costo operativo."]
RIESGOS = ["Plazo ajustado", "Fuga de datos personales", "Costos cloud fuera de control"]
MODELOS = (("simulado-a", "Familia A (simulada)"), ("simulado-b", "Familia B (simulada)"),
           ("simulado-c", "Familia C (simulada)"))


def crear_simulacion(semilla: int = 7, pausa: float = 0.0,
                     dormir: Callable[[float], None] = time.sleep) -> tuple[Callable[..., dict[str, str]], Callable[[str], str]]:
    """(ejecutar_ronda, llamar_moderador) falsos. `pausa` simula la latencia de cada experto."""
    azar = random.Random(semilla)

    def ejecutar(moderador_llm, expertos, llms, prompts, revisar_cancelacion=None, al_responder=None, **_):
        ronda_k = any("RETROALIMENTACIÓN" in p.upper() or "FEEDBACK" in p.upper() for p in prompts.values())
        ruido = 1 if ronda_k else 2          # la dispersión baja en rondas posteriores
        salida = {}
        for e in expertos:
            if revisar_cancelacion:
                revisar_cancelacion()
            if pausa:
                dormir(pausa)
            salida[e["id"]] = json.dumps({
                "respuestas": [{"item_id": i, "puntaje": max(1, min(5, v + azar.randint(-ruido, ruido))),
                                "justificacion": azar.choice(JUSTIFICACIONES)} for i, v in BASE.items()],
                "riesgos_detectados": azar.sample(RIESGOS, 2)})
            if al_responder:
                al_responder(e["id"], salida[e["id"]])
        return salida

    def moderador(prompt: str) -> str:
        if "Diseña el cuestionario" in prompt:
            return json.dumps(CUESTIONARIO)
        return '{"continuar": true, "motivo": "aún hay ítems sin consenso"}'

    return ejecutar, moderador


def pool_simulado() -> ModelPool:
    """ModelPool con tres modelos ficticios de familias distintas: mismas reglas de asignación."""
    bloques = [Bloque(nombre=modelo, modelo=modelo, base_url="http://simulado.local", api_key="",
                      familia=familia) for modelo, familia in MODELOS]
    moderador = Bloque(nombre="MODERADOR_SIMULADO", modelo="simulado-moderador",
                       base_url="http://simulado.local", api_key="", familia="Moderador (simulado)")
    return ModelPool(bloques, [moderador], fabrica=lambda b: SimpleNamespace(model=b.modelo))


def llm_por_experto(expertos: list[str], modo: str = "auto", seed: int | None = None,
                    manual: Mapping[str, str] | None = None) -> Callable[[str], Any]:
    """Atajo para la CLI: el get_llm de un pool simulado ya asignado."""
    pool = pool_simulado()
    pool.asignar(expertos, modo, seed, manual)
    return pool.get_llm
