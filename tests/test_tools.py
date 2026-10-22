import json

import pytest

from backend.delphi.tools import DelphiStatsTool, estadisticas_ronda, porcentaje_consenso


def _resp(eid, puntajes, ronda=1):
    return {"experto_id": eid, "rol": "x", "modelo": "m", "ronda": ronda,
            "respuestas": [{"item_id": i, "puntaje": p, "justificacion": "j"} for i, p in puntajes.items()]}


RESPUESTAS = [_resp("E1", {"A": 4, "B": 1}), _resp("E2", {"A": 4, "B": 5}),
              _resp("E3", {"A": 5, "B": 3}), _resp("E4", {"A": 4, "B": 4})]


def test_mediana_iqr_y_consenso():
    por_item = {e["item_id"]: e for e in estadisticas_ronda(RESPUESTAS)}
    assert por_item["A"]["mediana"] == 4 and por_item["A"]["consenso"]
    assert por_item["B"]["iqr"] > 1 and not por_item["B"]["consenso"]
    assert porcentaje_consenso(list(por_item.values())) == 0.5


def test_rechaza_puntaje_invalido_y_rondas_mezcladas():
    with pytest.raises(ValueError):
        estadisticas_ronda([_resp("E1", {"A": 6})])
    with pytest.raises(ValueError):
        estadisticas_ronda([_resp("E1", {"A": 3}, 1), _resp("E2", {"A": 3}, 2)])


def test_herramienta_devuelve_json():
    salida = json.loads(DelphiStatsTool()._run(RESPUESTAS))
    assert {"estadisticas", "porcentaje_consenso"} <= salida.keys()
