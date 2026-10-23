"""Construye los índices de conocimiento y memoria (RAG).

    python -m scripts.indexar_conocimiento             # índice de la Ley 21.719 + memoria desde outputs/runs/
    python -m scripts.indexar_conocimiento --solo-ley  # solo el índice de la ley

El índice de la ley (data/conocimiento/indice_ley_21719.*) se versiona en git: la demo no necesita
recalcular embeddings. La memoria (outputs/memoria/) es local y crece sola con cada análisis; este
script solo la reconstruye a partir de los informes ya guardados.
"""
from __future__ import annotations

import argparse
import json
import sys

from backend.delphi.conocimiento import (DIR_CONOCIMIENTO, DIR_MEMORIA, BaseConocimiento, EmbedderOpenAI,
                                         IndiceVectorial, documentos_ley)
from backend.delphi.config import RAIZ
from backend.delphi.models import InformeDelphi


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--solo-ley", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    embedder = EmbedderOpenAI.desde_env()
    if embedder is None:
        raise SystemExit("Falta EMBEDDINGS_API_KEY o LLM_API_KEY_GEMINI en el .env.")

    chunks = json.loads((DIR_CONOCIMIENTO / "ley_21719_chunks.json").read_text(encoding="utf-8"))
    indice = IndiceVectorial.construir(documentos_ley(chunks), embedder)
    indice.guardar(DIR_CONOCIMIENTO / "indice_ley_21719")
    print(f"Ley 21.719: {len(indice.documentos)} fragmentos, vectores de {indice.vectores.shape[1]} dimensiones "
          f"({embedder.modelo}).")

    if not args.solo_ley:
        base = BaseConocimiento(embedder, dir_memoria=DIR_MEMORIA)
        for informe_json in sorted((RAIZ / "outputs" / "runs").glob("*/informe.json")):
            informe = InformeDelphi.model_validate_json(informe_json.read_text(encoding="utf-8"))
            base.recordar(informe, informe_json.parent.name)
            print(f"Memoria: {informe_json.parent.name} · {informe.proyecto.nombre}")
        print(f"Memoria institucional: {len(base.memoria.documentos)} análisis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
