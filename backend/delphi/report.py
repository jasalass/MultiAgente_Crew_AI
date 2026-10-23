"""informe.md a partir de un InformeDelphi (README §1.7 y §5, Pamela)."""
from __future__ import annotations

import json
from pathlib import Path

from backend.delphi.adr import escribir_adrs
from backend.delphi.models import InformeDelphi

ICONO = {"firme": "✅ Firme", "condicionada": "⚠️ Condicionada", "abierta": "❓ Abierta"}
VEREDICTO = {"viable": "✅ Viable", "viable_con_condiciones": "⚠️ Viable con condiciones",
             "no_viable": "⛔ No viable tal como está planteado", "en_discusion": "❓ Viabilidad en discusión"}


def _tabla(encabezados: list[str], filas: list[list[str]]) -> str:
    if not filas:
        return "_Sin datos._"
    lineas = ["| " + " | ".join(encabezados) + " |", "|" + "---|" * len(encabezados)]
    return "\n".join(lineas + ["| " + " | ".join(f) + " |" for f in filas])


def _resumen_ejecutivo(i: InformeDelphi) -> str:
    n = {e: sum(d.estado == e for d in i.decisiones) for e in ICONO}
    ultima = i.rondas[-1] if i.rondas else None
    texto = (f"Panel de {len(i.panel)} expertos, {len(i.rondas)} ronda(s). "
             f"De {len(i.decisiones)} decisión(es): {n['firme']} firme(s), "
             f"{n['condicionada']} condicionada(s), {n['abierta']} abierta(s).")
    if ultima:
        texto += (f" Consenso final: {ultima.porcentaje_consenso:.0%} de los ítems "
                  f"(motivo de cierre: {ultima.motivo}).")
    return texto


def renderizar_informe(i: InformeDelphi) -> str:
    dims = sorted(i.evaluacion_por_dimension.items(), key=lambda kv: kv[1])
    riesgos = sorted(i.riesgos, key=lambda r: -r.probabilidad * r.impacto)
    sec = [f"# Informe Delphi — {i.proyecto.nombre}", ""]
    if i.viabilidad:
        sec += ["## Veredicto de viabilidad", f"**{VEREDICTO[i.viabilidad.veredicto]}**", "",
                i.viabilidad.explicacion, ""]
    sec += ["## Resumen ejecutivo", _resumen_ejecutivo(i), ""]
    if i.avisos:
        sec += ["> " + " · ".join(i.avisos), ""]

    sec += ["## Decisiones recomendadas", _tabla(
        ["Decisión", "Recomendación", "Estado", "Mediana", "IQR", "Margen"],
        [[d.titulo, d.alternativa_recomendada or "—", ICONO[d.estado], f"{d.mediana:g}",
          f"{d.iqr:g}", f"{d.margen_vs_segunda:g}"] for d in i.decisiones]), ""]
    for d in i.decisiones:
        if d.condiciones:
            sec += [f"**{d.titulo}** — condiciones:"] + [f"- {c}" for c in d.condiciones] + [""]

    sec += ["## Evaluación por dimensión (mediana final, de menor a mayor)",
            _tabla(["Dimensión", "Mediana"], [[k, f"{v:g}"] for k, v in dims]), ""]

    sec += ["## Matriz de riesgos (ordenada por probabilidad × impacto)", _tabla(
        ["Riesgo", "Dimensión", "Prob.", "Impacto", "Puntaje", "Menciones", "Mitigación"],
        [[r.descripcion, r.dimension, str(r.probabilidad), str(r.impacto),
          str(r.probabilidad * r.impacto), str(r.menciones), r.mitigacion] for r in riesgos]), ""]

    abiertas = [d for d in i.decisiones if d.poc_sugerida]
    sec += ["## Disensos y PoC sugeridas"]
    sec += [f"- {d}" for d in i.disensos] or ["_Todos los ítems terminaron con consenso._"]
    sec += [f"- **PoC — {d.titulo}:** {d.poc_sugerida}" for d in abiertas] + [""]

    sec += ["## Recomendaciones"] + [f"- {r}" for r in i.recomendaciones] + [""]

    sec += ["## Evolución por ronda", _tabla(
        ["Ronda", "Consenso", "¿Continúa?", "Motivo"],
        [[str(r.ronda), f"{r.porcentaje_consenso:.0%}", "sí" if r.continuar else "no", r.motivo]
         for r in i.rondas]), ""]

    sec += ["## Sesgo por modelo",
            "_Descriptivo: rol, proyecto y modelo están confundidos si no se rota la asignación._",
            _tabla(["Modelo", "Puntaje medio", "Desviación vs. mediana del grupo"],
                   [[s.modelo, f"{s.puntaje_medio:.2f}", f"{s.desviacion_vs_mediana_grupo:+.2f}"]
                    for s in i.sesgo_por_modelo]), ""]
    return "\n".join(sec)


def guardar_resultados(directorio: Path, informe: InformeDelphi) -> None:
    """outputs/runs/<run_id>/: informe.md, informe.json, adr/ y rondas.json (README §1.7).

    eventos.jsonl lo escribe quien recibe los eventos (CLI o RunStore), a medida que llegan.
    """
    directorio.mkdir(parents=True, exist_ok=True)
    (directorio / "informe.md").write_text(renderizar_informe(informe), encoding="utf-8")
    (directorio / "informe.json").write_text(informe.model_dump_json(indent=2), encoding="utf-8")
    escribir_adrs(informe.adrs, directorio / "adr")
    (directorio / "rondas.json").write_text(
        json.dumps([r.model_dump() for r in informe.rondas], ensure_ascii=False, indent=2), encoding="utf-8")
