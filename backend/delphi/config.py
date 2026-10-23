"""ModelPool: modelos del .env, asignación a roles y Moderador neutral (README §3).

Formato del .env (ver .env.example): un bloque por modelo de experto, con
LLM_API_KEY_<N>, LLM_MODEL_<N> y LLM_BASE_URL_<N> (si falta, se usa LLM_BASE_URL_GROQ).
Los bloques LLM_API_KEY_MODERADOR_<n> comparten LLM_MODEL_MODERADOR: son keys de cuentas
distintas que el Moderador rota. Un bloque con LLM_USO_<N>=puntual no es experto: se reserva
para las llamadas únicas de alto valor (cuestionario y riesgos), útil para un modelo bueno
pero lento o con pocas peticiones al día. Opcionales por bloque: LLM_FAMILIA_<N>,
LLM_REASONING_<N> (low|medium|high), LLM_MAX_TOKENS_<N> y LLM_TIMEOUT_<N> (segundos).
Un bloque sin key se omite.

Las keys nunca salen de este módulo: listar_modelos() devuelve nombre, proveedor y familia.
"""
from __future__ import annotations

import os
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.delphi.asignacion import AFINES, asignar_modelos

RAIZ = Path(__file__).resolve().parents[2]
PREFIJO_MODERADOR = "MODERADOR"
_PAREJA = {a: b for a, b in AFINES} | {b: a for a, b in AFINES}

# Subcadena del nombre del modelo -> familia. El orden importa: "gpt-oss" antes que "gpt".
FAMILIAS = (("gpt-oss", "GPT-OSS (OpenAI)"), ("qwen", "Qwen (Alibaba)"), ("gemini", "Gemini (Google)"),
            ("gemma", "Gemma (Google)"), ("nemotron", "Nemotron (NVIDIA)"), ("minimax", "MiniMax"),
            ("ministral", "Mistral"), ("mistral", "Mistral"), ("llama", "Llama (Meta)"),
            ("deepseek", "DeepSeek"), ("kimi", "Kimi (Moonshot)"), ("glm", "GLM (Zhipu)"),
            ("claude", "Claude (Anthropic)"), ("gpt", "GPT (OpenAI)"))
PROVEEDORES = (("groq", "Groq"), ("googleapis", "Google AI Studio"), ("openrouter", "OpenRouter"),
               ("mistral", "Mistral AI"), ("nvidia", "NVIDIA"), ("openai.com", "OpenAI"))


def familia_de(modelo: str) -> str:
    nombre = modelo.lower()
    return next((familia for clave, familia in FAMILIAS if clave in nombre), modelo.split("/")[-1])


@dataclass(frozen=True)
class Bloque:
    """Un bloque LLM_*_<nombre> del .env."""
    nombre: str
    modelo: str
    base_url: str
    api_key: str = field(repr=False)
    familia: str
    reasoning: str = ""
    max_tokens: int | None = None
    timeout: float | None = None

    @property
    def proveedor(self) -> str:
        host = urlparse(self.base_url).netloc.lower()
        return next((nombre for clave, nombre in PROVEEDORES if clave in host), host or "desconocido")


def leer_bloques(entorno: Mapping[str, str]) -> tuple[list[Bloque], list[Bloque], list[Bloque]]:
    """(expertos, moderadores, puntuales) a partir de las variables de entorno."""
    url_por_defecto = entorno.get("LLM_BASE_URL_GROQ", "").strip()
    modelo_moderador = entorno.get("LLM_MODEL_MODERADOR", "").strip()
    expertos: list[Bloque] = []
    moderadores: list[Bloque] = []
    puntuales: list[Bloque] = []
    for clave in sorted(k for k in entorno if k.startswith("LLM_API_KEY_")):
        nombre = clave.removeprefix("LLM_API_KEY_")
        api_key = entorno[clave].strip()
        es_moderador = nombre.startswith(PREFIJO_MODERADOR)
        modelo = (entorno.get(f"LLM_MODEL_{nombre}") or (modelo_moderador if es_moderador else "")).strip()
        if not api_key or not modelo or "<" in modelo:          # bloque sin completar: se omite
            continue
        base_url = (entorno.get(f"LLM_BASE_URL_{nombre}") or url_por_defecto).strip()
        if not base_url:
            raise ValueError(f"Falta LLM_BASE_URL_{nombre} (o LLM_BASE_URL_GROQ como valor por defecto).")
        def opcion(campo: str) -> str:
            """LLM_<campo>_<N>; los bloques MODERADOR_<n> heredan LLM_<campo>_MODERADOR."""
            valor = entorno.get(f"LLM_{campo}_{nombre}", "").strip()
            return valor or (entorno.get(f"LLM_{campo}_{PREFIJO_MODERADOR}", "").strip() if es_moderador else "")
        tope, espera = opcion("MAX_TOKENS"), opcion("TIMEOUT")
        bloque = Bloque(nombre=nombre, modelo=modelo, base_url=base_url, api_key=api_key,
                        familia=opcion("FAMILIA") or familia_de(modelo),
                        reasoning=opcion("REASONING"),
                        max_tokens=int(tope) if tope else None, timeout=float(espera) if espera else None)
        if es_moderador:
            moderadores.append(bloque)
        elif entorno.get(f"LLM_USO_{nombre}", "").strip().lower() == "puntual":
            puntuales.append(bloque)
        else:
            expertos.append(bloque)
    return expertos, moderadores, puntuales


def crear_llm(bloque: Bloque) -> Any:
    """crewai.LLM con el protocolo compatible con OpenAI (prefijo "openai/"), como en la clase."""
    from crewai import LLM
    extra: dict[str, Any] = {}
    if bloque.reasoning:
        # Modelos de razonamiento: sin un tope de esfuerzo pueden agotar los tokens pensando y
        # devolver un JSON cortado. OpenRouter usa {"reasoning": {...}}; Groq y Google, reasoning_effort.
        extra["extra_body"] = ({"reasoning": {"effort": bloque.reasoning}} if "openrouter" in bloque.base_url
                               else {"reasoning_effort": bloque.reasoning})
    if bloque.max_tokens:
        extra["max_tokens"] = bloque.max_tokens
    if bloque.timeout:
        extra["timeout"] = bloque.timeout
    return LLM(model=f"openai/{bloque.modelo}", api_key=bloque.api_key, base_url=bloque.base_url, **extra)


class ModelPool:
    """Modelos disponibles y su reparto entre los expertos de UN run a la vez.

    Uso: asignar(...) al empezar el run; luego get_llm(id) y, ante un 429 persistente,
    alternativo(id). "moderador" devuelve la lista de LLM del Moderador (una por key) y
    "puntual" la de los bloques de uso puntual (vacía si no hay).
    Si dos bloques de experto usan el mismo modelo, cuenta el primero: la diversidad es
    por modelo, no por key.
    """

    def __init__(self, expertos: list[Bloque], moderadores: list[Bloque] | None = None,
                 puntuales: list[Bloque] | None = None, fabrica: Callable[[Bloque], Any] = crear_llm):
        unicos: dict[str, Bloque] = {}
        for bloque in expertos:
            unicos.setdefault(bloque.modelo, bloque)
        self.expertos = list(unicos.values())
        self.moderadores = list(moderadores or [])
        self.puntuales = list(puntuales or [])
        self._fabrica = fabrica
        self._llms: dict[str, Any] = {}
        self._asignacion: dict[str, Bloque] = {}
        self._fallidos: dict[str, set[str]] = defaultdict(set)
        self._caidos: set[str] = set()
        self._modo = "auto"
        self.seed_usada: int | None = None
        self.avisos: list[str] = []

    @classmethod
    def desde_env(cls, ruta: Path | None = None, entorno: Mapping[str, str] | None = None) -> "ModelPool":
        if entorno is None:
            try:
                from dotenv import load_dotenv
                load_dotenv(ruta or RAIZ / ".env")
            except ModuleNotFoundError:
                pass
            entorno = os.environ
        return cls(*leer_bloques(entorno))

    # ----- catálogo -----
    def listar_modelos(self) -> list[dict[str, str]]:
        """Modelos de experto, sin keys (GET /modelos)."""
        return [{"nombre": b.modelo, "proveedor": b.proveedor, "familia": b.familia} for b in self.expertos]

    def _por_nombre(self, nombre: str) -> Bloque:
        for bloque in self.expertos:
            if bloque.modelo == nombre:
                return bloque
        raise ValueError(f"El modelo «{nombre}» no está disponible en el .env.")

    # ----- asignación -----
    def planificar(self, expertos: list[str], modo: str = "auto", seed: int | None = None,
                   manual: Mapping[str, str] | None = None) -> dict[str, Bloque]:
        """Reparto sin efectos: sirve también para validar una configuración antes de encolarla.

        auto:   equilibrado y sin roles afines en el mismo modelo.
        seed:   igual, pero con el orden rotado por la semilla (separa sesgo de rol y de modelo).
        manual: el que eligió el usuario; los roles afines deben usar modelos distintos.
        mono:   un solo modelo para todo el panel (control del experimento de sesgo).
        """
        if not self.expertos:
            raise ValueError("No hay modelos de experto configurados en el .env.")
        if modo in ("auto", "seed"):
            return asignar_modelos(expertos, self.expertos, (seed or 0) if modo == "seed" else 0)
        if modo == "mono":
            elegidos = {manual[e] for e in expertos if e in manual} if manual else set()
            if len(elegidos) > 1:
                raise ValueError("El control mono debe usar un único modelo.")
            # Sin elección: el primer modelo del .env (orden por nombre de bloque), siempre el mismo,
            # para que los runs mono de un experimento sean comparables entre sí.
            bloque = self._por_nombre(elegidos.pop()) if elegidos else self.expertos[0]
            return {e: bloque for e in expertos}
        if modo == "manual":
            faltan = [e for e in expertos if not manual or e not in manual]
            if faltan:
                raise ValueError(f"Falta elegir el modelo de: {', '.join(faltan)}.")
            reparto = {e: self._por_nombre(manual[e]) for e in expertos}
            for a, b in AFINES:
                if a in reparto and b in reparto and reparto[a] is reparto[b]:
                    raise ValueError(f"Los roles afines {a} y {b} deben usar modelos distintos.")
            return reparto
        raise ValueError(f"Modo de asignación desconocido: {modo}.")

    def asignar(self, expertos: list[str], modo: str = "auto", seed: int | None = None,
                manual: Mapping[str, str] | None = None) -> dict[str, str]:
        """Fija el reparto del run. Devuelve experto -> nombre de modelo."""
        if modo == "seed" and seed is None:
            seed = random.randrange(10_000)
        self._asignacion = self.planificar(expertos, modo, seed, manual)
        self._modo, self.seed_usada = modo, seed
        self._fallidos.clear()
        self._caidos.clear()
        self.avisos = self._avisos()
        return {e: b.modelo for e, b in self._asignacion.items()}

    def para_run(self, config: Any) -> Callable[[str], Any]:
        """Atajo para el motor: asigna según ConfigRun y devuelve get_llm."""
        self.asignar(config.expertos, config.asignacion_modelos, config.seed, config.modelos_manual)
        return self.get_llm

    def _moderadores(self) -> list[Bloque]:
        """Bloques dedicados; si no hay, el modelo de experto menos usado por el panel (neutral)."""
        if self.moderadores:
            return self.moderadores
        usos = Counter(b.modelo for b in self._asignacion.values())
        return [min(self.expertos, key=lambda b: (usos[b.modelo], self.expertos.index(b)))]

    def _avisos(self) -> list[str]:
        avisos = []
        if self._modo != "mono" and len({b.familia for b in self.expertos}) < 2:
            avisos.append("Hay menos de dos familias de modelos disponibles: riesgo de falso consenso.")
        familias = Counter(b.familia for b in self._asignacion.values())
        if familias and self._modo != "mono":
            mayoritaria, n = familias.most_common(1)[0]
            if n > len(self._asignacion) / 2 and self._moderadores()[0].familia == mayoritaria:
                avisos.append(f"El Moderador usa la familia de la mayoría del panel ({mayoritaria}): no es neutral.")
        return avisos

    # ----- LLM -----
    def _llm(self, bloque: Bloque) -> Any:
        if bloque.nombre not in self._llms:
            self._llms[bloque.nombre] = self._fabrica(bloque)
        return self._llms[bloque.nombre]

    def get_llm(self, agente_id: str) -> Any:
        if agente_id == "moderador":
            return [self._llm(b) for b in self._moderadores()]
        if agente_id == "puntual":
            return [self._llm(b) for b in self.puntuales]
        if agente_id not in self._asignacion:
            raise KeyError(f"El experto «{agente_id}» no tiene modelo asignado: llama a asignar() primero.")
        return self._llm(self._asignacion[agente_id])

    def get_client(self, agente_id: str) -> Any:
        """Cliente OpenAI directo (sin CrewAI) para el mismo bloque que usaría get_llm."""
        from openai import OpenAI
        bloque = self._moderadores()[0] if agente_id == "moderador" else self._asignacion[agente_id]
        return OpenAI(api_key=bloque.api_key, base_url=bloque.base_url)

    def alternativo(self, agente_id: str, caido: bool = False) -> Any | None:
        """Otro modelo para el experto tras un 429 persistente, respetando los roles afines.

        Con caido=True el modelo ya no existe: no se vuelve a ofrecer a ningún experto del run.
        Devuelve None si no queda ninguno o si el panel es mono (cambiarlo arruinaría el control).
        """
        if self._modo == "mono" or agente_id not in self._asignacion:
            return None
        actual = self._asignacion[agente_id].modelo
        self._fallidos[agente_id].add(actual)
        if caido:
            self._caidos.add(actual)
        pareja = self._asignacion.get(_PAREJA.get(agente_id, ""))
        usos = Counter(b.modelo for b in self._asignacion.values())
        candidatos = [b for b in self.expertos if b.modelo not in self._fallidos[agente_id] | self._caidos
                      and (pareja is None or b.modelo != pareja.modelo)]
        if not candidatos:
            return None
        nuevo = min(candidatos, key=lambda b: (usos[b.modelo], self.expertos.index(b)))
        self._asignacion[agente_id] = nuevo
        return self._llm(nuevo)
