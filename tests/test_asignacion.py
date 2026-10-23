import pytest

from backend.delphi.asignacion import AFINES, asignar_modelos
from backend.delphi.engine import con_reintentos
from backend.delphi.experts import NUCLEO

TODOS = list(NUCLEO) + ["datos", "qa"]


@pytest.mark.parametrize("rotacion", range(6))
@pytest.mark.parametrize("n_modelos", [2, 3, 4])
def test_afines_nunca_comparten_modelo_y_el_reparto_es_equilibrado(rotacion, n_modelos):
    asig = asignar_modelos(TODOS, list(range(n_modelos)), rotacion)
    for a, b in AFINES:
        if a in asig and b in asig:
            assert asig[a] != asig[b]
    usos = [list(asig.values()).count(i) for i in range(n_modelos)]
    assert max(usos) - min(usos) <= 1


def test_la_rotacion_cambia_la_asignacion():
    a = asignar_modelos(list(NUCLEO), ["A", "B", "C"], 0)
    b = asignar_modelos(list(NUCLEO), ["A", "B", "C"], 1)
    assert a != b and a["arquitectura"] != b["arquitectura"]


def test_un_solo_modelo_es_mono():
    assert set(asignar_modelos(list(NUCLEO), ["A"]).values()) == {"A"}


def test_reintenta_solo_ante_limite_de_tasa():
    esperas, llamadas = [], []

    def falla_dos_veces():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise RuntimeError("Error code: 429 - rate_limit_exceeded")
        return "ok"
    assert con_reintentos(falla_dos_veces, dormir=esperas.append) == "ok" and esperas == [30, 60]

    def demasiado_grande():
        raise RuntimeError("Error code: 413 - Request too large")
    with pytest.raises(RuntimeError):
        con_reintentos(demasiado_grande, dormir=esperas.append)
    assert esperas == [30, 60]            # el 413 no esperó ni reintentó
