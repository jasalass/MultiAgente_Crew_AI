"""ModelPool: lectura del .env, modos de asignación, Moderador neutral y cambio de modelo."""
from types import SimpleNamespace

import pytest

from backend.delphi.asignacion import AFINES
from backend.delphi.config import Bloque, ModelPool, familia_de, leer_bloques
from backend.delphi.experts import NUCLEO

PANEL = list(NUCLEO)
ENV = {
    "LLM_BASE_URL_GROQ": "https://api.groq.com/openai/v1",
    "LLM_MODEL_MODERADOR": "openai/gpt-oss-120b",
    "LLM_API_KEY_MODERADOR_1": "k-mod-1", "LLM_API_KEY_MODERADOR_2": "k-mod-2",
    "LLM_API_KEY_QWEN": "k-qwen", "LLM_MODEL_QWEN": "qwen/qwen3.8-27b",
    "LLM_API_KEY_GEMINI": "k-gem", "LLM_MODEL_GEMINI": "gemini-flash-latest",
    "LLM_BASE_URL_GEMINI": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "LLM_API_KEY_NEMO": "k-nemo", "LLM_MODEL_NEMO": "nvidia/nemotron:free",
    "LLM_BASE_URL_NEMO": "https://openrouter.ai/api/v1", "LLM_REASONING_NEMO": "low", "LLM_MAX_TOKENS_NEMO": "8000",
    "LLM_API_KEY_VACIO": "", "LLM_MODEL_VACIO": "x",                  # sin key: se omite
    "LLM_API_KEY_PENDIENTE": "k", "LLM_MODEL_PENDIENTE": "<completar>",  # sin modelo: se omite
}


def _pool(env=ENV):
    return ModelPool(*leer_bloques(env), fabrica=lambda b: SimpleNamespace(model=b.modelo, bloque=b))


def test_lee_bloques_y_nunca_expone_keys():
    pool = _pool()
    assert [b.nombre for b in pool.moderadores] == ["MODERADOR_1", "MODERADOR_2"]
    modelos = pool.listar_modelos()
    assert {m["nombre"] for m in modelos} == {"qwen/qwen3.8-27b", "gemini-flash-latest", "nvidia/nemotron:free"}
    assert {m["proveedor"] for m in modelos} == {"Groq", "Google AI Studio", "OpenRouter"}
    assert "k-" not in str(modelos) and "k-qwen" not in repr(pool.expertos)
    nemo = next(b for b in pool.expertos if b.nombre == "NEMO")
    assert nemo.reasoning == "low" and nemo.max_tokens == 8000


def test_familias_por_nombre_de_modelo():
    assert familia_de("openai/gpt-oss-20b") == "GPT-OSS (OpenAI)"
    assert familia_de("gemma-3") != familia_de("gemini-2.5-flash")
    assert familia_de("modelo-raro") == "modelo-raro"


def test_auto_equilibrado_y_sin_afines_en_el_mismo_modelo():
    pool = _pool()
    asignado = pool.asignar(PANEL + ["datos"], "auto")
    for a, b in AFINES:
        assert asignado[a] != asignado[b]
    assert pool.get_llm("cloud").model == asignado["cloud"]
    assert [m.model for m in pool.get_llm("moderador")] == ["openai/gpt-oss-120b"] * 2


def test_seed_rota_y_es_reproducible():
    pool = _pool()
    assert pool.asignar(PANEL, "seed", 1) == pool.asignar(PANEL, "seed", 1)
    assert pool.asignar(PANEL, "seed", 1) != pool.asignar(PANEL, "seed", 2)
    pool.asignar(PANEL, "seed")
    assert pool.seed_usada is not None


def test_mono_y_manual():
    pool = _pool()
    assert set(pool.asignar(PANEL, "mono", manual={e: "gemini-flash-latest" for e in PANEL}).values()) == {"gemini-flash-latest"}
    assert len(set(pool.asignar(PANEL, "mono", seed=1).values())) == 1
    manual = dict(zip(PANEL, ["qwen/qwen3.8-27b", "gemini-flash-latest", "gemini-flash-latest",
                              "qwen/qwen3.8-27b", "nvidia/nemotron:free"]))
    assert pool.asignar(PANEL, "manual", manual=manual) == manual
    with pytest.raises(ValueError, match="afines"):
        pool.planificar(PANEL, "manual", manual={e: "qwen/qwen3.8-27b" for e in PANEL})
    with pytest.raises(ValueError, match="no está disponible"):
        pool.planificar(PANEL, "manual", manual={**manual, "cloud": "inventado"})
    with pytest.raises(ValueError, match="Falta"):
        pool.planificar(PANEL, "manual", manual={"cloud": "qwen/qwen3.8-27b"})


def test_alternativo_respeta_afines_y_no_repite_modelos_fallidos():
    pool = _pool()
    pool.asignar(PANEL, "auto")
    original = pool.get_llm("arquitectura").model
    pareja = pool.get_llm("desarrollo").model
    nuevo = pool.alternativo("arquitectura")
    assert nuevo.model not in (original, pareja) and pool.get_llm("arquitectura") is nuevo
    assert pool.alternativo("arquitectura") is None        # el tercero está ocupado por la pareja
    pool.asignar(PANEL, "mono", seed=0)
    assert pool.alternativo("cloud") is None               # mono no se rompe


def test_moderador_neutral_sin_bloques_dedicados():
    env = {k: v for k, v in ENV.items() if "MODERADOR" not in k}
    pool = _pool(env)
    pool.asignar(PANEL + ["datos"], "auto")                # 6 expertos, 3 modelos: 2 cada uno
    assert len(pool.get_llm("moderador")) == 1
    bloque = Bloque("A", "qwen-a", "u", "k", "Qwen")
    solo_qwen = ModelPool([bloque, Bloque("B", "qwen-b", "u", "k", "Qwen")], [Bloque("M", "qwen-m", "u", "k", "Qwen")],
                          fabrica=lambda b: b)
    solo_qwen.asignar(PANEL, "auto")
    assert any("menos de dos familias" in a for a in solo_qwen.avisos)
    assert any("no es neutral" in a for a in solo_qwen.avisos)


def test_sin_modelos_avisa_con_claridad():
    with pytest.raises(ValueError, match="No hay modelos"):
        ModelPool([]).planificar(PANEL)
    with pytest.raises(ValueError, match="LLM_BASE_URL_X"):
        leer_bloques({"LLM_API_KEY_X": "k", "LLM_MODEL_X": "m"})


def test_bloque_puntual_no_es_experto():
    env = {**ENV, "LLM_USO_NEMO": "puntual", "LLM_TIMEOUT_NEMO": "240"}
    pool = _pool(env)
    assert "nvidia/nemotron:free" not in {m["nombre"] for m in pool.listar_modelos()}
    pool.asignar(PANEL, "auto")
    assert "nvidia/nemotron:free" not in {pool.get_llm(e).model for e in PANEL}
    [puntual] = pool.get_llm("puntual")
    assert puntual.model == "nvidia/nemotron:free" and puntual.bloque.timeout == 240
    assert _pool().get_llm("puntual") == []


def test_modelo_caido_no_se_ofrece_a_otros_expertos():
    pool = _pool()
    asignado = pool.asignar(PANEL, "auto")
    caido = asignado["arquitectura"]
    pool.alternativo("arquitectura", caido=True)
    otro = next(e for e in PANEL if e != "arquitectura" and asignado[e] != caido)
    nuevo = pool.alternativo(otro)
    assert nuevo is None or nuevo.model != caido


def test_razonamiento_segun_proveedor_y_opciones_heredadas_del_moderador(monkeypatch):
    import crewai

    from backend.delphi.config import crear_llm
    creados = []
    monkeypatch.setattr(crewai, "LLM", lambda **kw: creados.append(kw) or kw)
    env = {**ENV, "LLM_MAX_TOKENS_MODERADOR": "8000", "LLM_REASONING_MODERADOR": "low", "LLM_REASONING_QWEN": "none"}
    expertos, moderadores, _ = leer_bloques(env)
    assert all(m.max_tokens == 8000 and m.reasoning == "low" for m in moderadores)
    crear_llm(next(b for b in expertos if b.nombre == "QWEN"))     # Groq
    crear_llm(next(b for b in expertos if b.nombre == "NEMO"))     # OpenRouter
    assert creados[0]["extra_body"] == {"reasoning_effort": "none"}
    assert creados[1]["extra_body"] == {"reasoning": {"effort": "low"}} and creados[1]["max_tokens"] == 8000
