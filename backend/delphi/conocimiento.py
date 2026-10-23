"""Conocimiento y memoria del panel: búsqueda semántica (RAG) heredada de la Evaluación Parcial 1.

Dos índices vectoriales locales (un .json con los documentos y un .npz con los vectores):

  - Ley 21.719: los 140 fragmentos por artículo que produjo la EP1 (data/conocimiento/), con
    embeddings gemini-embedding-001. La EP1 usaba mistral-embed + Postgres/pgvector; aquí se
    guarda en archivo para que la demo no dependa de Docker.
  - Memoria institucional (largo plazo): un documento por análisis terminado (proyecto,
    veredicto, decisiones y riesgos). Se agrega solo al finalizar cada run y la consulta el
    Asesor normativo en los análisis siguientes (outputs/memoria/, fuera de git).

Si la API de embeddings falla o no hay key, la búsqueda cae a coincidencia de palabras: más
pobre, pero el análisis no se cae.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

RAIZ = Path(__file__).resolve().parents[2]
DIR_CONOCIMIENTO = RAIZ / "data" / "conocimiento"
DIR_MEMORIA = RAIZ / "outputs" / "memoria"
GOOGLE_OPENAI = "https://generativelanguage.googleapis.com/v1beta/openai/"

Embedder = Callable[[list[str]], np.ndarray]


class EmbedderOpenAI:
    """Embeddings por una API compatible con OpenAI (Google AI Studio por defecto). Vectores normalizados."""

    def __init__(self, api_key: str, base_url: str = GOOGLE_OPENAI, modelo: str = "gemini-embedding-001",
                 lote: int = 40, reintentos: int = 4, espera: float = 20.0):
        # Plan gratuito de Google: 100 textos por minuto (cada texto de un lote cuenta). Lotes chicos y,
        # ante un 429, esperar y reintentar: así se indexan los 140 fragmentos de la ley sin pagar.
        self.api_key, self.base_url, self.modelo, self.lote = api_key, base_url, modelo, lote
        self.reintentos, self.espera = reintentos, espera

    @classmethod
    def desde_env(cls, entorno: Mapping[str, str] | None = None) -> "EmbedderOpenAI | None":
        """EMBEDDINGS_API_KEY / _BASE_URL / _MODEL; sin ellas, la key y la URL del bloque GEMINI."""
        if entorno is None:
            try:
                from dotenv import load_dotenv
                load_dotenv(RAIZ / ".env")
            except ModuleNotFoundError:
                pass
            entorno = os.environ
        key = (entorno.get("EMBEDDINGS_API_KEY") or entorno.get("LLM_API_KEY_GEMINI") or "").strip()
        if not key:
            return None
        url = (entorno.get("EMBEDDINGS_BASE_URL") or entorno.get("LLM_BASE_URL_GEMINI") or GOOGLE_OPENAI).strip()
        return cls(key, url, (entorno.get("EMBEDDINGS_MODEL") or "gemini-embedding-001").strip())

    def __call__(self, textos: list[str]) -> np.ndarray:
        from openai import OpenAI
        cliente = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=30)
        vectores = []
        for i in range(0, len(textos), self.lote):
            lote = textos[i:i + self.lote]
            for intento in range(self.reintentos):
                try:
                    datos = cliente.embeddings.create(model=self.modelo, input=lote).data
                    break
                except Exception as error:
                    if "429" not in str(error) or intento == self.reintentos - 1:
                        raise
                    time.sleep(self.espera * (intento + 1))
            if len(datos) != len(lote):
                raise ValueError(f"Se pidieron {len(lote)} embeddings y llegaron {len(datos)}")
            if all(d.index is not None for d in datos):   # Google no informa el índice: vale el orden
                datos = sorted(datos, key=lambda d: d.index)
            vectores += [d.embedding for d in datos]
        return _normalizar_filas(np.asarray(vectores, dtype=np.float32))


def _normalizar_filas(matriz: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    return matriz / np.where(normas == 0, 1, normas)


def _palabras(texto: str) -> set[str]:
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return {p for p in re.findall(r"[a-z0-9]+", sin_tildes) if len(p) > 3}


class IndiceVectorial:
    """Documentos (dict con "texto") y sus vectores normalizados; búsqueda por coseno."""

    def __init__(self, documentos: list[dict] | None = None, vectores: np.ndarray | None = None):
        self.documentos = list(documentos or [])
        self.vectores = vectores
        if vectores is not None and len(vectores) != len(self.documentos):
            raise ValueError("La cantidad de vectores no coincide con la de documentos")

    @classmethod
    def construir(cls, documentos: list[dict], embedder: Embedder) -> "IndiceVectorial":
        return cls(documentos, embedder([d["texto"] for d in documentos]))

    @classmethod
    def cargar(cls, base: Path) -> "IndiceVectorial":
        """`base` sin extensión: lee base.json y, si existe, base.npz."""
        documentos = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
        npz = base.with_suffix(".npz")
        return cls(documentos, np.load(npz)["vectores"] if npz.exists() else None)

    def guardar(self, base: Path) -> None:
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix(".json").write_text(json.dumps(self.documentos, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
        if self.vectores is not None:
            np.savez_compressed(base.with_suffix(".npz"), vectores=self.vectores.astype(np.float32))

    def agregar(self, documento: dict, embedder: Embedder | None, clave: str | None = None) -> None:
        """Agrega (o reemplaza, si coincide `clave`) un documento; sin embedder queda solo para palabras."""
        if clave is not None:
            previos = [i for i, d in enumerate(self.documentos) if d.get(clave) == documento.get(clave)]
            for i in reversed(previos):
                del self.documentos[i]
                if self.vectores is not None:
                    self.vectores = np.delete(self.vectores, i, axis=0)
        vector = None
        if embedder is not None:
            try:
                vector = embedder([documento["texto"]])
            except Exception:
                vector = None
        if vector is not None and (self.vectores is not None or not self.documentos):
            self.vectores = vector if self.vectores is None else np.vstack([self.vectores, vector])
        elif self.vectores is not None:        # sin vector: el índice pasa a buscar solo por palabras
            self.vectores = None
        self.documentos.append(documento)

    def buscar(self, consulta: str, embedder: Embedder | None, top_k: int = 4,
               filtro: Callable[[dict], bool] | None = None) -> list[tuple[float, dict, str]]:
        """[(puntaje, documento, modo)] de mayor a menor. modo: "semántica" o "palabras"."""
        indices = [i for i, d in enumerate(self.documentos) if filtro is None or filtro(d)]
        if not indices:
            return []
        if embedder is not None and self.vectores is not None:
            try:
                q = embedder([consulta])[0]
                if q.shape[0] == self.vectores.shape[1]:
                    puntajes = self.vectores[indices] @ q
                    orden = np.argsort(-puntajes)[:top_k]
                    return [(float(puntajes[k]), self.documentos[indices[k]], "semántica") for k in orden]
            except Exception:
                pass                            # sin red o sin cuota: se busca por palabras
        # Respaldo: coincidencia de palabras ponderada por IDF (las palabras raras, como "salud", pesan más
        # que las que están en casi todos los artículos, como "datos").
        q = _palabras(consulta)
        palabras_doc = {i: _palabras(self.documentos[i]["texto"]) for i in indices}
        idf = {w: math.log((1 + len(indices)) / (1 + sum(w in p for p in palabras_doc.values()))) + 1 for w in q}
        puntuados = []
        for i in indices:
            p = palabras_doc[i]
            puntuados.append((sum(idf[w] for w in q & p) / math.sqrt(len(p) + 1), i))
        puntuados.sort(key=lambda x: -x[0])
        return [(s, self.documentos[i], "palabras") for s, i in puntuados[:top_k] if s > 0]


# --- Ley 21.719 ---------------------------------------------------------------------

def cita(fragmento: dict) -> str:
    """Referencia legible: la Ley 21.719 modifica la Ley 19.628 (artículo primero) y agrega otros artículos."""
    if fragmento.get("nivel1") == "primero" and fragmento.get("articulo"):
        numero = fragmento["articulo"] + (f" {fragmento['articulo_sufijo']}" if fragmento.get("articulo_sufijo") else "")
        nombre = f" ({fragmento['articulo_nombre']})" if fragmento.get("articulo_nombre") else ""
        parte = f", parte {fragmento['parte']}" if fragmento.get("parte") not in (None, "1/1") else ""
        return f"Ley 19.628 art. {numero}{nombre}{parte}, texto según la Ley 21.719"
    transitorio = " transitorio" if fragmento.get("ambito") == "transitorio" else ""
    return f"Ley 21.719, artículo {fragmento.get('nivel1') or '—'}{transitorio}"


def documentos_ley(chunks: list[dict]) -> list[dict]:
    return [{**c, "cita": cita(c)} for c in chunks]


# --- Memoria institucional (largo plazo) ---------------------------------------------

def documento_de_informe(informe: Any, run_id: str) -> dict:
    """Resumen de un análisis terminado, para recuperarlo cuando llegue un proyecto parecido."""
    i = informe.model_dump() if hasattr(informe, "model_dump") else dict(informe)
    p = i["proyecto"]
    veredicto = (i.get("viabilidad") or {}).get("veredicto", "sin veredicto")
    decisiones = [f"{d['titulo']}: {d.get('alternativa_recomendada') or 'abierta'} ({d['estado']})"
                  for d in i.get("decisiones", [])]
    riesgos = [r["descripcion"] for r in sorted(i.get("riesgos", []),
                                                key=lambda r: -r["probabilidad"] * r["impacto"])[:3]]
    texto = (f"Proyecto: {p['nombre']}. {p['objetivo']} Restricciones: {'; '.join(p.get('restricciones', []))}. "
             f"Equipo: {p.get('equipo', '')}. Veredicto de viabilidad: {veredicto}. "
             f"Decisiones: {'; '.join(decisiones)}. Riesgos principales: {'; '.join(riesgos)}.")
    return {"run_id": run_id, "proyecto": p["nombre"], "veredicto": veredicto, "decisiones": decisiones,
            "riesgos": riesgos, "texto": texto}


class BaseConocimiento:
    """Lo que consultan las herramientas del Asesor: la ley y la memoria de análisis anteriores."""

    def __init__(self, embedder: Embedder | None, dir_conocimiento: Path = DIR_CONOCIMIENTO,
                 dir_memoria: Path = DIR_MEMORIA):
        self.embedder = embedder
        self._base_ley = dir_conocimiento / "indice_ley_21719"
        self._chunks = dir_conocimiento / "ley_21719_chunks.json"
        self._base_memoria = dir_memoria / "analisis"
        self._ley: IndiceVectorial | None = None
        self._memoria: IndiceVectorial | None = None

    @property
    def ley(self) -> IndiceVectorial:
        if self._ley is None:
            if self._base_ley.with_suffix(".json").exists():
                self._ley = IndiceVectorial.cargar(self._base_ley)
            else:                               # sin índice construido: solo búsqueda por palabras
                chunks = json.loads(self._chunks.read_text(encoding="utf-8")) if self._chunks.exists() else []
                self._ley = IndiceVectorial(documentos_ley(chunks))
        return self._ley

    @property
    def memoria(self) -> IndiceVectorial:
        if self._memoria is None:
            existe = self._base_memoria.with_suffix(".json").exists()
            self._memoria = IndiceVectorial.cargar(self._base_memoria) if existe else IndiceVectorial()
        return self._memoria

    def consultar_ley(self, pregunta: str, articulo: str | None = None, top_k: int = 4):
        filtro = (lambda d: d.get("articulo") == str(articulo).strip()) if articulo else None
        return self.ley.buscar(pregunta, self.embedder, top_k, filtro)

    def buscar_analisis(self, descripcion: str, top_k: int = 3, excluir_run: str | None = None):
        filtro = (lambda d: d.get("run_id") != excluir_run) if excluir_run else None
        return self.memoria.buscar(descripcion, self.embedder, top_k, filtro)

    def recordar(self, informe: Any, run_id: str) -> None:
        """Guarda el análisis terminado en la memoria de largo plazo (reemplaza si ya estaba)."""
        self.memoria.agregar(documento_de_informe(informe, run_id), self.embedder, clave="run_id")
        self.memoria.guardar(self._base_memoria)
