"""Un ADR (Architecture Decision Record) por decisión Delphi (README §1.7 y §5, Pamela).

Formato: Contexto · Decisión · Alternativas consideradas · Consecuencias ·
Estado (Aceptada / Condicionada / Abierta) · Evidencia Delphi.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from backend.delphi.models import (
    ADR, Cuestionario, DecisionRecomendada, EstadisticaItem, Proyecto, ResumenRonda,
)

ESTADO_ADR = {"firme": "aceptada", "condicionada": "condicionada", "abierta": "abierta"}


def _alternativas(cuestionario: Cuestionario, decision_id: str) -> dict[str, str]:
    """nombre de alternativa -> item_id"""
    return {i.alternativa: i.id for i in cuestionario.items if i.decision_id == decision_id}


def _stats_por_ronda(rondas: list[ResumenRonda]) -> list[dict[str, EstadisticaItem]]:
    return [{e.item_id: e for e in r.estadisticas} for r in rondas]


def _contexto(proyecto: Proyecto) -> str:
    partes = [f"Proyecto «{proyecto.nombre}»: {proyecto.objetivo}"]
    if proyecto.restricciones:
        partes.append("Restricciones: " + "; ".join(proyecto.restricciones) + ".")
    if proyecto.equipo:
        partes.append(f"Equipo: {proyecto.equipo}")
    return " ".join(partes)


def _evidencia(d: DecisionRecomendada, cuestionario: Cuestionario, rondas: list[ResumenRonda]) -> str:
    alts = _alternativas(cuestionario, d.decision_id)
    por_ronda = _stats_por_ronda(rondas)
    lineas = [f"{len(rondas)} ronda(s). Resultado final: mediana {d.mediana:g}, IQR {d.iqr:g}, "
              f"margen frente a la segunda alternativa {d.margen_vs_segunda:g}.", ""]
    lineas += ["| Alternativa | " + " | ".join(f"R{r.ronda} (mediana / IQR)" for r in rondas) + " |",
               "|---|" + "---|" * len(rondas)]
    for nombre, item_id in alts.items():
        celdas = [f"{s[item_id].mediana:g} / {s[item_id].iqr:g}" if item_id in s else "—" for s in por_ronda]
        lineas.append(f"| {nombre} | " + " | ".join(celdas) + " |")
    if d.alternativa_recomendada:
        final = por_ronda[-1].get(alts[d.alternativa_recomendada])
        if final:
            for titulo, args in (("A favor", final.argumentos_a_favor), ("En contra", final.argumentos_en_contra)):
                if args:
                    lineas += ["", f"{titulo} (síntesis anónima):"] + [f"- {a}" for a in args]
    return "\n".join(lineas)


def construir_adrs(proyecto: Proyecto, cuestionario: Cuestionario, rondas: list[ResumenRonda],
                   decisiones: list[DecisionRecomendada]) -> list[ADR]:
    adrs = []
    for numero, d in enumerate(decisiones, 1):
        alternativas = list(_alternativas(cuestionario, d.decision_id))
        if d.estado == "abierta":
            decision = f"No se adopta una alternativa todavía. {d.poc_sugerida}"
            consecuencias = ["No comprometer el diseño que depende de esta decisión hasta resolverla.",
                             "Reservar tiempo para la PoC o el spike."]
        else:
            decision = f"Se adopta «{d.alternativa_recomendada}»."
            consecuencias = ([f"Las demás alternativas ({', '.join(a for a in alternativas if a != d.alternativa_recomendada)}) "
                              "quedan descartadas para este proyecto."]
                             if d.estado == "firme" else d.condiciones)
        adrs.append(ADR(numero=numero, titulo=d.titulo, estado=ESTADO_ADR[d.estado],
                        contexto=_contexto(proyecto), decision=decision,
                        alternativas_consideradas=alternativas, consecuencias=consecuencias,
                        evidencia_delphi=_evidencia(d, cuestionario, rondas)))
    return adrs


def renderizar_adr(adr: ADR) -> str:
    alternativas = "\n".join(f"- {a}" for a in adr.alternativas_consideradas)
    consecuencias = "\n".join(f"- {c}" for c in adr.consecuencias)
    return (f"# ADR-{adr.numero:03d}: {adr.titulo}\n\n"
            f"**Estado:** {adr.estado.capitalize()}\n\n"
            f"## Contexto\n{adr.contexto}\n\n"
            f"## Decisión\n{adr.decision}\n\n"
            f"## Alternativas consideradas\n{alternativas}\n\n"
            f"## Consecuencias\n{consecuencias}\n\n"
            f"## Evidencia Delphi\n{adr.evidencia_delphi}\n")


def _slug(texto: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-") or "decision"


def nombre_archivo(adr: ADR) -> str:
    return f"ADR-{adr.numero:03d}-{_slug(adr.titulo)}.md"


def escribir_adrs(adrs: list[ADR], directorio: Path) -> list[Path]:
    """Escribe adr/ADR-001-<decision>.md, … en `directorio`."""
    directorio.mkdir(parents=True, exist_ok=True)
    rutas = []
    for adr in adrs:
        ruta = directorio / nombre_archivo(adr)
        ruta.write_text(renderizar_adr(adr), encoding="utf-8")
        rutas.append(ruta)
    return rutas
