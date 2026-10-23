"""Corre el motor Delphi sin API ni frontend, para depurarlo (README §5, Pamela).

    python -m backend.cli data/proyectos/clinica_reservas.md            # LLM reales (.env)
    python -m backend.cli data/proyectos/clinica_reservas.md --mock     # sin keys ni red
    python -m backend.cli data/proyectos/migracion_erp.md --asignacion mono

Escribe outputs/runs/<run_id>/ con informe.md, informe.json, adr/, rondas.json y
eventos.jsonl. Los modelos salen del .env vía ModelPool (ver .env.example).
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from backend.delphi.asesor import asesor_simulado, preparar_ficha
from backend.delphi.config import RAIZ, ModelPool
from backend.delphi.conocimiento import BaseConocimiento, EmbedderOpenAI
from backend.delphi.engine import DelphiEngine, RunCancelado, RunError
from backend.delphi.experts import NUCLEO
from backend.delphi.models import ConfigRun, EstadoRun
from backend.delphi.project_loader import cargar_proyecto
from backend.delphi.report import guardar_resultados
from backend.delphi.simulado import crear_simulacion, pool_simulado


def main() -> None:
    ap = argparse.ArgumentParser(description="Panel Delphi sin API ni frontend")
    ap.add_argument("proyecto", type=Path, help="archivo .md con la plantilla del proyecto")
    ap.add_argument("--expertos", nargs="+", default=list(NUCLEO), help="ids del panel (por defecto, el núcleo)")
    ap.add_argument("--min-rondas", type=int, default=2)
    ap.add_argument("--max-rondas", type=int, default=3)
    ap.add_argument("--asignacion", choices=["auto", "seed", "mono"], default="seed",
                    help="reparto de modelos (README §3); seed rota la asignación entre ejecuciones")
    ap.add_argument("--seed", type=int, default=None,
                    help="semilla de seed/mono; por defecto, la cantidad de runs ya guardados")
    ap.add_argument("--pausa", type=float, default=5.0, help="segundos entre el inicio de un experto y el siguiente")
    ap.add_argument("--paralelo", type=int, default=5, help="expertos que responden a la vez (1 = de a uno)")
    ap.add_argument("--mock", action="store_true", help="LLM falsos: no usa keys ni red")
    ap.add_argument("--sin-asesor", action="store_true", help="sin el Asesor normativo (más rápido)")
    args = ap.parse_args()
    # La consola de Windows (cp1252) no admite algunos caracteres que escriben los LLM (p. ej. "‑").
    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(errors="replace")
    logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("delphi").setLevel(logging.INFO)

    runs = RAIZ / "outputs" / "runs"
    seed = args.seed if args.seed is not None else (len(list(runs.iterdir())) if runs.exists() else 0)
    config = ConfigRun(proyecto=cargar_proyecto(args.proyecto), expertos=args.expertos,
                       asignacion_modelos=args.asignacion, seed=seed,
                       min_rondas=args.min_rondas, max_rondas=args.max_rondas)
    pool = pool_simulado() if args.mock else ModelPool.desde_env()
    try:
        llm_para = pool.para_run(config)
    except ValueError as error:
        raise SystemExit(f"{error} Revisa el .env (ver .env.example).")
    print(f"Asignación de modelos ({config.asignacion_modelos}, semilla {seed}):")
    for e in args.expertos:
        print(f"  {e:13} -> {llm_para(e).model}")
    moderadores = llm_para("moderador")
    print(f"  {'moderador':13} -> {moderadores[0].model} ({len(moderadores)} key/s)")
    for llm in llm_para("puntual"):
        print(f"  {'puntual':13} -> {llm.model} (cuestionario y riesgos)")
    for aviso in pool.avisos:
        print(f"AVISO: {aviso}")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.mock:
        base = BaseConocimiento(None, dir_memoria=RAIZ / "outputs" / "memoria_simulada")
        ejecutar, moderador = crear_simulacion(seed)
        motor = DelphiEngine(llm_para, ejecutar, moderador, asesor=None if args.sin_asesor else asesor_simulado(base))
    else:
        base = BaseConocimiento(EmbedderOpenAI.desde_env())
        moderadores = llm_para("moderador")         # una key para cada agente del Asesor
        asesor = None if args.sin_asesor else (lambda proyecto, rid: preparar_ficha(
            proyecto, moderadores[0], base, runs / rid / "ficha_contexto.md", rid,
            moderadores[1 % len(moderadores)]))
        motor = DelphiEngine(llm_para, pausa_entre_expertos=args.pausa, paralelo=args.paralelo,
                             modelo_alternativo=pool.alternativo, avisos=pool.avisos, asesor=asesor)

    destino = runs / run_id
    destino.mkdir(parents=True, exist_ok=True)
    eventos = destino / "eventos.jsonl"

    def al_evento(e):
        with open(eventos, "a", encoding="utf-8") as archivo:
            archivo.write(e.model_dump_json() + "\n")
        print(f"[{e.seq:03d}] {e.tipo}" + (f" (ronda {e.ronda})" if e.ronda else ""))

    try:
        informe = motor.run(run_id, config, al_evento, lambda: False)
    except (RunCancelado, RunError) as error:
        print(f"Run terminado sin informe: {error}")
        raise SystemExit(1)
    guardar_resultados(destino, informe)
    # estado.json: así el Historial de la API y el frontend también muestran los runs de la CLI.
    (destino / "estado.json").write_text(EstadoRun(
        run_id=run_id, estado="finalizado", ronda_actual=len(informe.rondas), config=config,
        creado=datetime.strptime(run_id, "%Y%m%d-%H%M%S").astimezone(),
        finalizado=datetime.now().astimezone()).model_dump_json(indent=2), encoding="utf-8")
    try:
        base.recordar(informe, run_id)          # memoria institucional para los próximos análisis
    except Exception as error:
        print(f"AVISO: no se pudo guardar el análisis en la memoria: {error}")
    print(f"\nListo. Resultados en {destino}")
    if informe.viabilidad:
        print(f"  VEREDICTO: {informe.viabilidad.veredicto}")
    for d in informe.decisiones:
        print(f"  {d.estado.upper():13} {d.titulo}: {d.alternativa_recomendada or 'ABIERTA'}")


if __name__ == "__main__":
    main()
