"""Corre el motor Delphi sin API ni frontend, para depurarlo (README §5, Pamela).

    python -m backend.cli data/proyectos/clinica_reservas.md            # LLM reales (.env)
    python -m backend.cli data/proyectos/clinica_reservas.md --mock     # sin keys ni red

Provisional: `cargar_proyecto` y `llms_desde_env` serán reemplazados por
project_loader.py y ModelPool (Juan). Escribe outputs/runs/<run_id>/ con
informe.md, adr/, rondas.json y eventos.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from backend.delphi.adr import escribir_adrs
from backend.delphi.engine import DelphiEngine, RunCancelado, RunError
from backend.delphi.experts import NUCLEO
from backend.delphi.models import ConfigRun, Proyecto
from backend.delphi.report import renderizar_informe

RAIZ = Path(__file__).resolve().parents[1]
SECCIONES = {"objetivo y contexto": "objetivo", "usuarios y volumen": "usuarios_volumen",
             "requisitos funcionales": "requisitos_funcionales",
             "requisitos no funcionales": "requisitos_no_funcionales", "restricciones": "restricciones",
             "equipo": "equipo", "integraciones": "integraciones", "decisiones a evaluar": "decisiones_a_evaluar"}
LISTAS = {"requisitos_funcionales", "requisitos_no_funcionales", "restricciones", "integraciones",
          "decisiones_a_evaluar"}


def cargar_proyecto(ruta: Path) -> Proyecto:
    """Parser mínimo de la plantilla del README §1.6."""
    texto = ruta.read_text(encoding="utf-8")
    campos: dict = {"nombre": ruta.stem, "texto_original": texto}
    actual = None
    for linea in texto.splitlines():
        if linea.startswith("# "):
            campos["nombre"] = linea[2:].strip()
        elif linea.startswith("## "):
            clave = re.sub(r"\(.*?\)", "", linea[3:]).strip().lower()
            actual = SECCIONES.get(clave)
        elif actual and linea.strip():
            if actual in LISTAS:
                campos.setdefault(actual, []).append(linea.strip().lstrip("-*0123456789. ").strip())
            else:
                campos[actual] = (campos.get(actual, "") + " " + linea.strip()).strip()
    campos.setdefault("objetivo", campos["nombre"])
    return Proyecto(**campos)


# --- LLM reales: un bloque LLM_*_<NOMBRE> del .env por modelo --------------------------

def llms_desde_env(expertos: list[str]):
    from crewai import LLM
    try:
        from dotenv import load_dotenv
        load_dotenv(RAIZ / ".env")
    except ModuleNotFoundError:
        pass
    nombres = sorted(k.removeprefix("LLM_API_KEY_") for k in os.environ if k.startswith("LLM_API_KEY_"))
    # Se omiten los bloques sin completar (key vacía o modelo "<...>" de la plantilla).
    nombres = [n for n in nombres if os.environ[f"LLM_API_KEY_{n}"].strip()
               and "<" not in os.environ.get(f"LLM_MODEL_{n}", "<")]
    if not nombres:
        raise SystemExit("No hay bloques LLM_API_KEY_<NOMBRE> en el .env (ver README §3). Prueba con --mock.")
    modelos = [LLM(model=f"openai/{os.environ[f'LLM_MODEL_{n}']}", base_url=os.environ[f"LLM_BASE_URL_{n}"],
                   api_key=os.environ[f"LLM_API_KEY_{n}"]) for n in nombres]
    asignado = {e: modelos[i % len(modelos)] for i, e in enumerate(expertos)}
    asignado["moderador"] = modelos[-1]
    if len(modelos) < 2:
        print("AVISO: un solo modelo disponible: panel mono-modelo, riesgo de falso consenso.")
    return lambda agente_id: asignado[agente_id]


# --- Modo --mock: LLM falsos y deterministas, para ver el flujo completo sin keys --------

def mock(semilla: int):
    azar = random.Random(semilla)
    cuestionario = {
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
    base = {"ARQ-E1": 4, "SEG-E1": 3, "ARQ-D1-a": 5, "ARQ-D1-b": 2, "INF-D1-a": 4, "INF-D1-b": 4}
    justificaciones = ["Prioriza mantenibilidad y separación de responsabilidades.",
                       "Reduce la superficie de ataque y el costo operativo."]

    def ejecutar(moderador_llm, expertos, llms, prompts, **_):
        ronda_k = any("RETROALIMENTACIÓN" in p.upper() or "FEEDBACK" in p.upper() for p in prompts.values())
        ruido = 1 if ronda_k else 2          # la dispersión baja en rondas posteriores
        salida = {}
        for e in expertos:
            salida[e["id"]] = json.dumps({
                "respuestas": [{"item_id": i, "puntaje": max(1, min(5, v + azar.randint(-ruido, ruido))),
                                "justificacion": azar.choice(justificaciones)} for i, v in base.items()],
                "riesgos_detectados": azar.sample(["Plazo ajustado", "Fuga de datos personales",
                                                   "Costos cloud fuera de control"], 2)})
        return salida

    def moderador(prompt: str) -> str:
        if "Diseña el cuestionario" in prompt:
            return json.dumps(cuestionario)
        return '{"continuar": true, "motivo": "aún hay ítems sin consenso"}'

    return ejecutar, moderador


# --- Persistencia ---------------------------------------------------------------------

def guardar(directorio: Path, informe, eventos: list) -> None:
    directorio.mkdir(parents=True, exist_ok=True)
    (directorio / "informe.md").write_text(renderizar_informe(informe), encoding="utf-8")
    escribir_adrs(informe.adrs, directorio / "adr")
    (directorio / "rondas.json").write_text(
        json.dumps([r.model_dump() for r in informe.rondas], ensure_ascii=False, indent=2), encoding="utf-8")
    (directorio / "eventos.jsonl").write_text(
        "\n".join(e.model_dump_json() for e in eventos) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Panel Delphi sin API ni frontend")
    ap.add_argument("proyecto", type=Path, help="archivo .md con la plantilla del proyecto")
    ap.add_argument("--expertos", nargs="+", default=list(NUCLEO), help="ids del panel (por defecto, el núcleo)")
    ap.add_argument("--min-rondas", type=int, default=2)
    ap.add_argument("--max-rondas", type=int, default=3)
    ap.add_argument("--mock", action="store_true", help="LLM falsos: no usa keys ni red")
    ap.add_argument("--semilla", type=int, default=7, help="semilla del modo --mock")
    args = ap.parse_args()

    config = ConfigRun(proyecto=cargar_proyecto(args.proyecto), expertos=args.expertos,
                       min_rondas=args.min_rondas, max_rondas=args.max_rondas)
    if args.mock:
        ejecutar, moderador = mock(args.semilla)
        motor = DelphiEngine(lambda _id: SimpleNamespace(model=f"mock-{hash(_id) % 3}"), ejecutar, moderador)
    else:
        motor = DelphiEngine(llms_desde_env(args.expertos))

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    eventos: list = []

    def al_evento(e):
        eventos.append(e)
        print(f"[{e.seq:03d}] {e.tipo}" + (f" (ronda {e.ronda})" if e.ronda else ""))

    destino = RAIZ / "outputs" / "runs" / run_id
    try:
        informe = motor.run(run_id, config, al_evento, lambda: False)
    except (RunCancelado, RunError) as error:
        print(f"Run terminado sin informe: {error}")
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "eventos.jsonl").write_text("\n".join(e.model_dump_json() for e in eventos) + "\n", encoding="utf-8")
        raise SystemExit(1)
    guardar(destino, informe, eventos)
    print(f"\nListo. Resultados en {destino}")
    for d in informe.decisiones:
        print(f"  {d.estado.upper():13} {d.titulo}: {d.alternativa_recomendada or 'ABIERTA'}")


if __name__ == "__main__":
    main()
