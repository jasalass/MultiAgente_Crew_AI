"""Compara los mismos tres proyectos con panel mono y auto.

No invoca LLM directamente: usa el contrato HTTP del README mediante ApiClient.
Con ``--mock`` valida el flujo con resultados ficticios claramente identificados;
no es evidencia experimental sobre modelos. Con API real se pueden pasar tres
archivos Markdown: ``--proyectos p1.md p2.md p3.md``. Si se omite, se utilizan los
tres proyectos canónicos de ``data/proyectos/``. ``--modelo-mono`` permite elegir
el modelo de control; por defecto se fija el primero del catálogo de la API.
Los informes JSON se guardan junto a la comparación CSV/Markdown. Una API que
devuelva el aviso de ejecución simulada también se identifica como simulación.

Ejecutar desde la raíz: ``python -m scripts.experimento_sesgo --mock``.
La API real debe estar lista: ``python -m scripts.experimento_sesgo --api-url
http://localhost:8000 --timeout 1800``. No se necesitan dependencias adicionales
a las del frontend y la biblioteca estándar.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
import time
from typing import Any
import unicodedata


PROYECTOS_CONTROL = ("clinica_reservas.md", "migracion_erp.md", "marketplace_ia.md")


def cargar_proyectos(
    cliente: Any, rutas: list[Path] | None = None, *, directorio: Path | None = None,
) -> list[dict[str, Any]]:
    """Parsea los mismos tres inputs canónicos tanto en mock como en HTTP."""
    if rutas is None:
        directorio = directorio or Path(__file__).resolve().parents[1] / "data" / "proyectos"
        rutas = [directorio / nombre for nombre in PROYECTOS_CONTROL]
    if len(rutas) != 3:
        raise ValueError("El experimento requiere exactamente tres proyectos.")
    # Leer todos antes de enviar solicitudes para detectar archivos faltantes.
    textos = [ruta.read_text(encoding="utf-8-sig") for ruta in rutas]
    return [cliente.parsear_proyecto(texto) for texto in textos]


def elegir_modelo_mono(modelos: list[dict[str, Any]], solicitado: str | None) -> str:
    """Congela una elección explícita del catálogo antes de iniciar seis runs."""
    nombres = [modelo["nombre"] for modelo in modelos]
    if not nombres:
        raise ValueError("La API no tiene modelos de experto disponibles.")
    if solicitado is not None and solicitado not in nombres:
        raise ValueError(f"El modelo de control «{solicitado}» no está disponible en la API.")
    return solicitado if solicitado is not None else nombres[0]


def origen_resultados(evidencias: list[dict[str, Any]], *, mock: bool) -> str:
    """Distingue el mock frontend de la API real que ejecuta su motor simulado."""
    if mock:
        return "SIMULADO: mock del frontend, no evidencia de sesgo"
    simulados = [
        any("simulad" in str(aviso).casefold() or "fictici" in str(aviso).casefold()
            for aviso in evidencia.get("informe", {}).get("avisos", []))
        for evidencia in evidencias
    ]
    if any(simulados):
        if all(simulados):
            return "API SIMULADA: motor con LLM ficticios, no evidencia de sesgo"
        return "MIXTO: incluye API simulada, no tratar como evidencia íntegramente real"
    return "API"


def _normalizar(texto: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", texto).casefold().split())


def _items(informe: Mapping[str, Any]) -> list[dict[str, Any]]:
    return informe.get("cuestionario", {}).get("items", [])


def _firma_cuestionario(informe: Mapping[str, Any]) -> list[tuple[str, ...]]:
    # Los ids no garantizan equivalencia semántica de cuestionarios generados.
    return sorted(
        tuple(_normalizar(str(item.get(campo) or "")) for campo in (
            "dimension", "tipo", "pregunta", "alternativa"
        ))
        for item in _items(informe)
    )


def _iqr_ronda_uno(informe: Mapping[str, Any]) -> float | None:
    ronda = next((r for r in informe.get("rondas", []) if r["ronda"] == 1), None)
    valores = [float(e["iqr"]) for e in ronda.get("estadisticas", [])] if ronda else []
    return fmean(valores) if valores else None


def _ronda_consenso(informe: Mapping[str, Any], umbral: float) -> int | None:
    # Un cierre por estabilidad o max_rondas no equivale a lograr consenso.
    rondas = [
        r["ronda"] for r in informe.get("rondas", [])
        if r["porcentaje_consenso"] >= umbral
    ]
    return min(rondas) if rondas else None


def _decisiones_por_titulo(informe: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    decisiones = {}
    for decision in informe.get("decisiones", []):
        clave = _normalizar(decision["titulo"])
        if clave in decisiones:
            raise ValueError("Hay títulos de decisión repetidos; la comparación es ambigua.")
        decisiones[clave] = decision
    return decisiones


def comparar_informes(
    mono: Mapping[str, Any], auto: Mapping[str, Any], umbral: float = 0.8
) -> dict[str, Any]:
    """Métricas puras; los valores ausentes se conservan como None.

    El IQR de ronda 1 es la media de los IQR de todos los ítems de cada informe.
    Se indica si los cuestionarios son equivalentes antes de interpretar esa
    comparación. Se emparejan decisiones por título, no por ids generados. Un
    cambio de estado se cuenta separado de un cambio de alternativa; las
    decisiones presentes en solo un informe se señalan como no emparejables.
    """
    if not 0 < umbral <= 1:
        raise ValueError("El umbral de consenso debe estar entre 0 y 1.")
    nombre = mono["proyecto"]["nombre"]
    if _normalizar(nombre) != _normalizar(auto["proyecto"]["nombre"]):
        raise ValueError("Los informes deben corresponder al mismo proyecto.")
    decisiones_mono, decisiones_auto = map(_decisiones_por_titulo, (mono, auto))
    cambios = []
    cambios_alternativa = cambios_estado = sin_pareja = 0
    for clave in sorted(decisiones_mono.keys() | decisiones_auto.keys()):
        a, b = decisiones_mono.get(clave), decisiones_auto.get(clave)
        if a is None or b is None:
            sin_pareja += 1
            tipo = "sin pareja"
        else:
            cambia_alternativa = a["alternativa_recomendada"] != b["alternativa_recomendada"]
            cambia_estado = a["estado"] != b["estado"]
            cambios_alternativa += int(cambia_alternativa)
            cambios_estado += int(cambia_estado)
            if not cambia_alternativa and not cambia_estado:
                continue
            tipo = "alternativa" if cambia_alternativa else "estado"
        cambios.append({
            "titulo": (a or b)["titulo"], "tipo": tipo,
            "mono": a["alternativa_recomendada"] if a else None,
            "auto": b["alternativa_recomendada"] if b else None,
            "estado_mono": a["estado"] if a else "ausente",
            "estado_auto": b["estado"] if b else "ausente",
        })
    firma_mono, firma_auto = map(_firma_cuestionario, (mono, auto))
    return {
        "proyecto": nombre,
        "iqr_ronda1_mono": _iqr_ronda_uno(mono),
        "iqr_ronda1_auto": _iqr_ronda_uno(auto),
        "rondas_hasta_consenso_mono": _ronda_consenso(mono, umbral),
        "rondas_hasta_consenso_auto": _ronda_consenso(auto, umbral),
        "rondas_ejecutadas_mono": len(mono.get("rondas", [])),
        "rondas_ejecutadas_auto": len(auto.get("rondas", [])),
        "cuestionarios_equivalentes": bool(firma_mono) and firma_mono == firma_auto,
        "cambios_alternativa": cambios_alternativa,
        "cambios_estado": cambios_estado,
        "decisiones_sin_pareja": sin_pareja,
        "cambios": cambios,
    }


def ejecutar_run(
    cliente: Any, config: dict[str, Any], *, timeout: float = 900,
    intervalo: float = 2, reloj: Callable[[], float] = time.monotonic,
    esperar: Callable[[float], None] = time.sleep,
) -> tuple[str, dict[str, Any]]:
    """Espera un run con límite, detecta error/cancelación y cancela al expirar.

    Los eventos también se consultan: permiten avanzar el mock y recoger la
    explicación de un error sin depender de sleeps artificiales en las pruebas.
    """
    if timeout <= 0 or intervalo < 0:
        raise ValueError("timeout debe ser positivo e intervalo no negativo.")
    limite = reloj() + timeout
    run_id = cliente.crear_run(config)["run_id"]
    secuencia = 0
    ultimo_error = ""
    try:
        while reloj() < limite:
            eventos = cliente.obtener_eventos(run_id, desde=secuencia)
            for evento in eventos:
                secuencia = max(secuencia, evento["seq"])
                if evento["tipo"] == "error":
                    ultimo_error = str(evento.get("payload", {}))
            estado = cliente.obtener_run(run_id)["estado"]
            if estado == "finalizado":
                return run_id, cliente.obtener_informe(run_id, formato="json")
            if estado in {"error", "cancelado"}:
                raise RuntimeError(f"Run {run_id}: {estado}. {ultimo_error}".strip())
            if estado not in {"en_cola", "ejecutando"}:
                raise RuntimeError(f"Estado desconocido del run {run_id}: {estado}.")
            restante = limite - reloj()
            if restante > 0:
                esperar(min(intervalo, restante))
        try:
            cliente.cancelar_run(run_id)
        except Exception as exc:
            raise TimeoutError(
                f"Run {run_id}: excedió {timeout:g} s y no se pudo solicitar cancelación: {exc}"
            ) from exc
        raise TimeoutError(f"Run {run_id}: excedió {timeout:g} s; cancelación solicitada.")
    except KeyboardInterrupt:
        cliente.cancelar_run(run_id)
        raise


def _celda(valor: Any) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, float):
        return f"{valor:.3f}"
    return str(valor).replace("|", "\\|").replace("\n", " ")


def guardar_comparacion(
    resultados: list[dict[str, Any]], salida: Path, *, mock: bool,
    evidencias: list[dict[str, Any]],
) -> None:
    """Exporta métricas y evidencia; nunca convierte un resultado mock en real."""
    salida.mkdir(parents=True, exist_ok=True)
    origen = origen_resultados(evidencias, mock=mock)
    simulado = origen != "API"
    columnas = ["origen", "proyecto", "run_mono", "run_auto", "iqr_ronda1_mono",
                "iqr_ronda1_auto", "rondas_hasta_consenso_mono", "rondas_hasta_consenso_auto",
                "rondas_ejecutadas_mono", "rondas_ejecutadas_auto", "cuestionarios_equivalentes",
                "cambios_alternativa", "cambios_estado", "decisiones_sin_pareja", "modelo_mono"]
    with (salida / "comparacion.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        writer = csv.DictWriter(archivo, fieldnames=columnas, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({"origen": origen, **fila} for fila in resultados)
    lineas = ["# Comparación mono frente a auto", "",
              f"**DATOS SIMULADOS: {origen}. No son resultados empíricos de modelos reales.**"
              if simulado else "Resultados obtenidos de la API; revisar las condiciones de cada ejecución.",
              "", f"Generado: {datetime.now(timezone.utc).isoformat()} (UTC).", "",
              "IQR: media de los IQR por ítem en la ronda 1. Consenso: primera ronda que alcanza "
              "el umbral global configurado; — significa que no se alcanzó. Un cierre por estabilidad "
              "no se cuenta como consenso. Cambios de alternativa incluyen pasar a o desde una decisión abierta.",
              "", "| Proyecto | IQR R1 mono | IQR R1 auto | Consenso mono | Consenso auto | "
              "Alternativas cambiadas | Estados cambiados | Sin pareja | Cuestionario equivalente |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for fila in resultados:
        campos = ["proyecto", "iqr_ronda1_mono", "iqr_ronda1_auto", "rondas_hasta_consenso_mono",
                  "rondas_hasta_consenso_auto", "cambios_alternativa", "cambios_estado",
                  "decisiones_sin_pareja", "cuestionarios_equivalentes"]
        lineas.append("| " + " | ".join(_celda(fila[c]) for c in campos) + " |")
    lineas += ["", "Si los cuestionarios difieren, los IQR resumen conjuntos de preguntas distintos y "
               "la comparación requiere revisión humana. Los títulos distintos de decisiones se informan "
               "como sin pareja; no se asume que sean cambios de preferencia.", "",
               "La asignación rol–modelo, el cuestionario y la variabilidad de generación pueden explicar "
               "las diferencias. Este control descriptivo no identifica un efecto causal del modelo. "
               "Para estudiar ese efecto, repetir proyectos con semillas y asignaciones rotadas."]
    for fila in resultados:
        lineas += ["", "## " + fila["proyecto"], "",
                   f"Runs: mono `{fila['run_mono']}` · auto `{fila['run_auto']}`.", ""]
        if fila.get("modelo_mono"):
            lineas += [f"Modelo fijado para el control mono: `{fila['modelo_mono']}`.", ""]
        if not fila["cambios"]:
            lineas.append("No cambiaron las alternativas ni los estados de las decisiones emparejadas.")
            continue
        lineas += ["| Decisión | Mono | Estado mono | Auto | Estado auto | Cambio |",
                   "|---|---|---|---|---|---|"]
        for cambio in fila["cambios"]:
            lineas.append("| " + " | ".join(_celda(cambio[c]) for c in (
                "titulo", "mono", "estado_mono", "auto", "estado_auto", "tipo"
            )) + " |")
    (salida / "comparacion.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    (salida / "ejecuciones.json").write_text(json.dumps({
        "origen": origen, "ejecuciones": evidencias, "comparacion": resultados
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true", help="Usar solo datos simulados; no invoca LLM.")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--modelo-mono", help="Nombre exacto del modelo de control en GET /modelos.")
    parser.add_argument("--proyectos", nargs=3, type=Path, metavar="ARCHIVO_MD")
    parser.add_argument("--salida", type=Path, default=Path("outputs/experimento_sesgo"))
    parser.add_argument("--timeout", type=float, default=900, help="Límite en segundos por run.")
    parser.add_argument("--intervalo", type=float, default=None, help="Polling; 2 s API, 0 s mock.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    if args.timeout <= 0 or (args.intervalo is not None and args.intervalo < 0):
        parser.error("timeout debe ser positivo e intervalo no negativo")
    from frontend.api_client import ApiClient

    cliente = ApiClient(use_mocks=args.mock, base_url=args.api_url)
    modelo_mono = elegir_modelo_mono(cliente.listar_modelos(), args.modelo_mono)
    proyectos = cargar_proyectos(cliente, args.proyectos)
    if args.mock:
        print("DEMOSTRACIÓN CON DATOS SIMULADOS: no se llamarán modelos reales.")
    else:
        print(f"Ejecutando seis análisis mediante la API {args.api_url}.")
    print(f"Modelo de control mono: {modelo_mono}", flush=True)
    resultados, evidencias = [], []
    for proyecto in proyectos:
        sugerencias = cliente.sugerir_panel(proyecto)
        panel = [sugerencia["id"] for sugerencia in sugerencias]
        config_base = {"proyecto": proyecto, "expertos": panel, "seed": args.seed,
                       "min_rondas": 2, "max_rondas": 3, "umbral_iqr": 1.0,
                       "umbral_consenso_global": 0.8}
        informes, ids = {}, {}
        for modo in ("mono", "auto"):
            print(f"{proyecto['nombre']} · {modo}", flush=True)
            config = {**config_base, "asignacion_modelos": modo,
                      "modelos_manual": {rol: modelo_mono for rol in panel} if modo == "mono" else None}
            ids[modo], informes[modo] = ejecutar_run(
                cliente, config, timeout=args.timeout,
                intervalo=args.intervalo if args.intervalo is not None else (0 if args.mock else 2),
            )
            evidencias.append({"run_id": ids[modo], "config": config, "informe": informes[modo]})
            origen = origen_resultados(evidencias, mock=args.mock)
            # Conservar los runs ya terminados si una ejecución posterior falla.
            args.salida.mkdir(parents=True, exist_ok=True)
            (args.salida / "ejecuciones_parciales.json").write_text(json.dumps({
                "origen": origen, "ejecuciones": evidencias
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        resultados.append({**comparar_informes(informes["mono"], informes["auto"]),
                           "run_mono": ids["mono"], "run_auto": ids["auto"],
                           "modelo_mono": modelo_mono})
    guardar_comparacion(resultados, args.salida, mock=args.mock, evidencias=evidencias)
    print(f"Comparación guardada en {args.salida.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
