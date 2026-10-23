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
from backend.delphi.asignacion import asignar_modelos
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

def llms_desde_env(expertos: list[str], rotacion: int = 0):
    """Lee el .env (ver su cabecera): bloques MODERADOR_<n> y un bloque por modelo experto."""
    from crewai import LLM
    try:
        from dotenv import load_dotenv
        load_dotenv(RAIZ / ".env")
    except ModuleNotFoundError:
        pass
    url_groq = os.environ.get("LLM_BASE_URL_GROQ", "")

    def crear(nombre: str, modelo: str) -> "LLM":
        extra: dict = {}
        # Modelos de razonamiento (OpenRouter): LLM_REASONING_<N>=low|medium|high limita lo que
        # "piensan" antes de responder; sin esto pueden agotar los tokens y devolver JSON vacío.
        esfuerzo = os.environ.get(f"LLM_REASONING_{nombre}", "").strip()
        if esfuerzo:
            extra["extra_body"] = {"reasoning": {"effort": esfuerzo}}
        tope = os.environ.get(f"LLM_MAX_TOKENS_{nombre}", "").strip()
        if tope:
            extra["max_tokens"] = int(tope)
        return LLM(model=f"openai/{modelo}", api_key=os.environ[f"LLM_API_KEY_{nombre}"],
                   base_url=os.environ.get(f"LLM_BASE_URL_{nombre}", url_groq), **extra)

    bloques = sorted(k.removeprefix("LLM_API_KEY_") for k in os.environ if k.startswith("LLM_API_KEY_"))
    bloques = [b for b in bloques if os.environ[f"LLM_API_KEY_{b}"].strip()]   # sin key: se omite
    # Moderadores: mismo modelo, una key distinta cada uno (se rotan entre expertos).
    modelo_mod = os.environ.get("LLM_MODEL_MODERADOR", "")
    moderadores = [crear(b, modelo_mod) for b in bloques if b.startswith("MODERADOR_")]
    if not moderadores:
        raise SystemExit("Faltan los bloques LLM_API_KEY_MODERADOR_<n> y LLM_MODEL_MODERADOR en el .env.")
    # Expertos: un bloque por modelo; se omiten los que aún tienen el modelo sin completar.
    modelos = [crear(b, os.environ[f"LLM_MODEL_{b}"]) for b in bloques
               if not b.startswith("MODERADOR_") and "<" not in os.environ.get(f"LLM_MODEL_{b}", "<")]
    if not modelos:
        raise SystemExit("No hay bloques de expertos completos en el .env (ver su cabecera).")
    asignado = asignar_modelos(expertos, modelos, rotacion)   # sin roles afines en el mismo modelo
    asignado["moderador"] = moderadores
    if len(modelos) < 2:
        print("AVISO: un solo modelo de experto: panel mono-modelo, riesgo de falso consenso.")
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
    ap.add_argument("--rotacion", type=int, default=None,
                    help="desplaza la asignación de modelos; por defecto cambia en cada ejecución")
    ap.add_argument("--pausa", type=float, default=10.0, help="segundos entre expertos (modelos reales)")
    ap.add_argument("--mock", action="store_true", help="LLM falsos: no usa keys ni red")
    ap.add_argument("--semilla", type=int, default=7, help="semilla del modo --mock")
    args = ap.parse_args()

    config = ConfigRun(proyecto=cargar_proyecto(args.proyecto), expertos=args.expertos,
                       min_rondas=args.min_rondas, max_rondas=args.max_rondas)
    if args.mock:
        ejecutar, moderador = mock(args.semilla)
        motor = DelphiEngine(lambda _id: SimpleNamespace(model=f"mock-{hash(_id) % 3}"), ejecutar, moderador)
    else:
        runs = RAIZ / "outputs" / "runs"
        rotacion = args.rotacion if args.rotacion is not None else (len(list(runs.iterdir())) if runs.exists() else 0)
        llm_para = llms_desde_env(args.expertos, rotacion)
        print(f"Asignación de modelos (rotación {rotacion}):")
        for e in args.expertos:
            print(f"  {e:13} -> {llm_para(e).model}")
        motor = DelphiEngine(llm_para, pausa_entre_expertos=args.pausa)

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
