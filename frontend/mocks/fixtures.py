"""Fixtures reproducibles con los contratos de README §4 (sin dependencia del backend)."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import re
from statistics import mean, median, quantiles


MODELOS = [
    {"nombre": "demo-mistral-ficticio", "proveedor": "Simulado local", "familia": "Mistral (simulada)"},
    {"nombre": "demo-qwen-ficticio", "proveedor": "Simulado local", "familia": "Qwen (simulada)"},
    {"nombre": "demo-gemini-ficticio", "proveedor": "Simulado local", "familia": "Gemini (simulada)"},
]
NUCLEO = ["arquitectura", "cloud", "desarrollo", "seguridad", "devops"]
DIMENSIONES = ["arquitectura", "infraestructura", "stack", "datos", "seguridad", "calidad", "operacion", "gestion"]
FECHA_DEMO = "2026-10-21T09:00:00+00:00"


def _proyecto(nombre, objetivo, usuarios, funcionales, no_funcionales, restricciones, equipo, integraciones, decisiones):
    proyecto = {
        "nombre": nombre, "objetivo": objetivo, "usuarios_volumen": usuarios,
        "requisitos_funcionales": funcionales, "requisitos_no_funcionales": no_funcionales,
        "restricciones": restricciones, "equipo": equipo, "integraciones": integraciones,
        "decisiones_a_evaluar": decisiones,
    }
    secciones = [
        ("Objetivo y contexto", objetivo), ("Usuarios y volumen", usuarios),
        ("Requisitos funcionales", funcionales), ("Requisitos no funcionales", no_funcionales),
        ("Restricciones", restricciones), ("Equipo", equipo), ("Integraciones", integraciones),
        ("Decisiones a evaluar", decisiones),
    ]
    proyecto["texto_original"] = f"# {nombre}\n\n" + "\n\n".join(
        f"## {titulo}\n" + ("\n".join(f"- {v}" for v in valor) if isinstance(valor, list) else valor)
        for titulo, valor in secciones
    )
    return proyecto


def ejemplos_proyectos():
    """Tres ejemplos locales para trabajar mientras Juan prepara data/proyectos/."""
    return deepcopy([
        _proyecto(
            "Reservas de una red de clínicas", "Centralizar reservas y disponibilidad de profesionales para pacientes y recepcionistas de cuatro clínicas.",
            "2.000 pacientes diarios; 150 usuarios concurrentes y crecimiento anual del 20 %.",
            ["Buscar horas disponibles", "Reservar y cancelar citas", "Administrar agendas", "Enviar recordatorios", "Consultar historial de reservas"],
            ["Disponibilidad del 99,5 %", "Respuesta bajo 2 segundos", "Acceso por roles", "Accesibilidad en los flujos principales"],
            ["Plazo de 6 meses", "Presupuesto acotado", "Datos personales sensibles"],
            "4 personas con experiencia en Python, React y PostgreSQL.", ["Sistema clínico existente", "Servicio de correo"], []),
        _proyecto(
            "Migración de ERP a la nube", "Migrar un ERP monolítico on-premise sin detener los procesos de venta y contabilidad.",
            "500 empleados y procesos nocturnos de alta carga; 10 años de datos históricos.",
            ["Mantener facturación", "Migrar datos históricos", "Integrar inventario", "Auditar cambios"],
            ["Recuperación en menos de una hora", "Integridad de las transacciones", "Trazabilidad de migración"],
            ["Migración gradual", "Licencias existentes", "Ventanas de mantenimiento de fin de semana"],
            "6 desarrolladores con experiencia en el ERP y limitada experiencia cloud.", ["Bancos", "Facturación electrónica", "Directorio corporativo"],
            ["Migración: lift & shift vs refactorizar a microservicios"]),
        _proyecto(
            "Marketplace con IA generativa", "Crear un marketplace con recomendaciones y descripciones generadas por LLM para pequeños comercios.",
            "Meta inicial de 10.000 usuarios; demanda todavía sin validar.",
            ["Publicar productos", "Procesar compras", "Generar descripciones con IA", "Recomendar productos", "Moderar contenido"],
            ["Protección de datos", "Control del gasto de inferencia", "Disponibilidad durante campañas"],
            ["3 meses de plazo", "Presupuesto mínimo", "Dependencia de APIs externas de IA"],
            "2 desarrolladores junior sin experiencia en producción.", ["Pagos", "API de LLM", "Logística"], []),
    ])


def _alternativas(texto):
    contenido = texto.split(":", 1)[-1].strip()
    opciones = [v.strip(" .;()") for v in re.split(r"\s+(?:vs\.?|versus|frente a)\s+|\s*\|\s*", contenido, flags=re.I)]
    if len(opciones) < 2:
        opciones = [f"Adoptar propuesta: {texto}", "Validar propuesta con una PoC", "Postergar propuesta"]
    return opciones[:5]


def _cuestionario(proyecto):
    decisiones = [
        {"id": "ARQ-D1", "dimension": "arquitectura", "titulo": "Estilo de arquitectura", "alternativas": ["Monolito modular", "Microservicios", "Serverless"]},
        {"id": "INF-D1", "dimension": "infraestructura", "titulo": "Estrategia de infraestructura", "alternativas": ["PaaS gestionado", "Contenedores gestionados", "Máquinas virtuales"]},
        {"id": "DAT-D1", "dimension": "datos", "titulo": "Estrategia de persistencia", "alternativas": ["PostgreSQL gestionado", "Base documental", "Base relacional autogestionada"]},
    ]
    propuestas = proyecto.get("decisiones_a_evaluar", [])
    for indice, propuesta in enumerate(propuestas[:5]):
        if indice < len(decisiones):
            decisiones[indice]["titulo"] = str(propuesta)
            decisiones[indice]["alternativas"] = _alternativas(str(propuesta))
        else:
            decisiones.append({"id": f"GES-D{indice + 1}", "dimension": "gestion", "titulo": str(propuesta), "alternativas": _alternativas(str(propuesta))})
    preguntas = [
        "¿La arquitectura permite evolucionar sin complejidad innecesaria?",
        "¿La infraestructura es sostenible con las restricciones de presupuesto?",
        "¿El equipo domina el stack propuesto?", "¿Se puede mantener la integridad de los datos?",
        "¿Se han definido controles de acceso y protección de datos?", "¿Se podrá verificar la calidad antes del lanzamiento?",
        "¿El equipo puede operar y recuperar el servicio?", "¿Son viables el alcance y el plazo con el equipo descrito?",
    ]
    items = [{"id": f"{dim[:3].upper()}-E1", "dimension": dim, "tipo": "evaluacion", "pregunta": f"{pregunta} Proyecto: {proyecto['nombre']}.", "decision_id": None, "alternativa": None}
             for dim, pregunta in zip(DIMENSIONES, preguntas)]
    for decision in decisiones:
        for indice, alternativa in enumerate(decision["alternativas"]):
            items.append({"id": f"{decision['id']}-{chr(97 + indice)}", "dimension": decision["dimension"], "tipo": "alternativa",
                          "pregunta": f"Adecuación de {alternativa} para {proyecto['nombre']}", "decision_id": decision["id"], "alternativa": alternativa})
    return {"decisiones": decisiones, "items": items}


def _puntaje(item, experto, ronda, total_rondas, config, cuestionario):
    mono = config.get("asignacion_modelos") == "mono"
    if item["tipo"] == "evaluacion":
        debil = any(t in (config["proyecto"].get("equipo", "") + " " + " ".join(config["proyecto"].get("restricciones", []))).lower() for t in ("junior", "mínimo"))
        if debil and item["dimension"] in ("gestion", "operacion", "calidad"):
            return 2 if mono else [1, 2, 2, 2, 3, 2, 2][experto]
        if mono:
            return 4
        if ronda < total_rondas and item["dimension"] in ("arquitectura", "infraestructura"):
            return [2, 2, 4, 4, 5, 2, 5][experto]
        return [4, 4, 5, 4, 4, 5, 4][experto]
    decision_indice = next(i for i, d in enumerate(cuestionario["decisiones"]) if d["id"] == item["decision_id"])
    alternativa_indice = ord(item["id"][-1]) - ord("a")
    if mono:
        return 5 if alternativa_indice == (1 if decision_indice == 0 else 0) else 3
    if decision_indice == 0:
        if alternativa_indice == 0:
            return ([2, 3, 4, 5, 5, 4, 3] if ronda == 1 else [5, 4, 5, 4, 5, 4, 5])[experto]
        return [3, 2, 3, 3, 2, 3, 3][experto] if alternativa_indice == 1 else 2
    if decision_indice == 1:
        if alternativa_indice < 2:
            return ([2, 2, 4, 4, 5, 2, 5] if ronda < total_rondas else [4, 4, 4, 4, 4, 4, 4])[experto]
        return 2
    if alternativa_indice == 0:
        return [2, 2, 4, 4, 5, 2, 5][experto]
    return [2, 4, 2, 4, 2, 3, 4][experto] if alternativa_indice == 1 else [1, 1, 2, 2, 3, 1, 2][experto]


def _asignar_modelos(config):
    panel = config["expertos"]
    nombres = [m["nombre"] for m in MODELOS]
    if config.get("asignacion_modelos") == "mono":
        elegido = next(iter((config.get("modelos_manual") or {}).values()), nombres[0])
        return {rol: elegido for rol in panel}
    if config.get("asignacion_modelos") == "manual":
        return dict(config.get("modelos_manual") or {})
    # Las parejas afines nunca comparten modelo, aun si cambia el orden del panel.
    color = {"arquitectura": 0, "desarrollo": 2, "cloud": 1, "devops": 2, "seguridad": 0, "datos": 1, "qa": 1, "ux": 0, "gestion": 2, "ia": 1}
    rotacion = int(config.get("seed") or 0) % 3 if config.get("asignacion_modelos") == "seed" else 0
    return {rol: nombres[(color.get(rol, indice) + rotacion) % 3] for indice, rol in enumerate(panel)}


def construir_informe(config):
    """Produce evidencia ficticia completa derivada del proyecto y del panel recibidos."""
    config = deepcopy(config)
    proyecto = config["proyecto"]
    cuestionario = _cuestionario(proyecto)
    total_rondas = config["min_rondas"] if config.get("asignacion_modelos") == "mono" else config["max_rondas"]
    modelos = _asignar_modelos(config)
    respuestas, rondas = [], []
    for ronda in range(1, total_rondas + 1):
        respuestas_ronda = []
        for indice, rol in enumerate(config["expertos"]):
            respuesta = {"experto_id": f"E{indice + 1}", "rol": rol, "modelo": modelos[rol], "ronda": ronda,
                         "respuestas": [{"item_id": item["id"], "puntaje": _puntaje(item, indice, ronda, total_rondas, config, cuestionario),
                                         "justificacion": ("Simulación: mantener la reserva sobre costo y capacidad operativa; se requiere una PoC." if item["decision_id"] == "DAT-D1" else "Simulación: priorizar alcance acotado, capacidad del equipo y validación medible del proyecto.")}
                                        for item in cuestionario["items"]],
                         "riesgos_detectados": [f"Capacidad operativa insuficiente para {proyecto['nombre']}", "Acceso indebido a datos personales"]}
            respuestas_ronda.append(respuesta)
        respuestas.extend(respuestas_ronda)
        estadisticas = []
        for item in cuestionario["items"]:
            puntajes = [next(r["puntaje"] for r in respuesta["respuestas"] if r["item_id"] == item["id"]) for respuesta in respuestas_ronda]
            q1, _, q3 = quantiles(puntajes, n=4, method="inclusive")
            estadisticas.append({"item_id": item["id"], "mediana": float(median(puntajes)), "q1": q1, "q3": q3,
                                 "iqr": q3 - q1, "consenso": q3 - q1 <= config["umbral_iqr"],
                                 "argumentos_a_favor": ["Reduce trabajo operativo y permite entregar por incrementos (argumento simulado)."],
                                 "argumentos_en_contra": ["Requiere validar costo y capacidad con una prueba controlada (argumento simulado)."]})
        porcentaje = sum(e["consenso"] for e in estadisticas) / len(estadisticas)
        terminar = ronda >= config["min_rondas"] and porcentaje >= config["umbral_consenso_global"]
        continuar = ronda < total_rondas and not terminar
        motivo = "consenso" if terminar else "moderador" if continuar else "max_rondas"
        rondas.append({"ronda": ronda, "estadisticas": estadisticas, "porcentaje_consenso": porcentaje, "continuar": continuar, "motivo": motivo})
        if not continuar:
            break
    decisiones, adrs = [], []
    estadisticas = {e["item_id"]: e for e in rondas[-1]["estadisticas"]}
    for indice, decision in enumerate(cuestionario["decisiones"]):
        opciones = [(item, estadisticas[item["id"]]) for item in cuestionario["items"] if item["decision_id"] == decision["id"]]
        opciones.sort(key=lambda par: (-par[1]["mediana"], par[1]["iqr"], par[0]["id"]))
        mejor, estadistica = opciones[0]
        margen = estadistica["mediana"] - opciones[1][1]["mediana"]
        estado = "abierta" if not estadistica["consenso"] or estadistica["mediana"] < 3 else "firme" if estadistica["mediana"] >= 4 and margen >= 1 else "condicionada"
        condiciones = ["Validar costo mensual y operación antes del compromiso de implementación."] if estado == "condicionada" else []
        poc = f"Comparar las alternativas de {decision['titulo']} con carga y presupuesto representativos." if estado == "abierta" else None
        recomendada = mejor["alternativa"] if estado != "abierta" else None
        decisiones.append({"decision_id": decision["id"], "titulo": decision["titulo"], "alternativa_recomendada": recomendada,
                           "estado": estado, "mediana": estadistica["mediana"], "iqr": estadistica["iqr"], "margen_vs_segunda": margen,
                           "condiciones": condiciones, "poc_sugerida": poc})
        adrs.append({"numero": indice + 1, "titulo": decision["titulo"], "estado": "aceptada" if estado == "firme" else estado,
                     "contexto": f"{proyecto['nombre']}: {proyecto['objetivo']} (evidencia ficticia de demostración).",
                     "decision": recomendada or "Pendiente de una prueba de concepto.", "alternativas_consideradas": decision["alternativas"],
                     "consecuencias": condiciones or ([poc] if poc else ["Revisar el resultado cuando cambien las restricciones del proyecto."]),
                     "evidencia_delphi": f"Simulación de {len(rondas)} rondas: mediana {estadistica['mediana']}, IQR {estadistica['iqr']}; margen {margen}."})
    evaluacion = {dim: float(median(e["mediana"] for e in rondas[-1]["estadisticas"] if any(i["id"] == e["item_id"] and i["tipo"] == "evaluacion" and i["dimension"] == dim for i in cuestionario["items"]))) for dim in DIMENSIONES}
    try:
        from backend.delphi.bias import calcular_sesgo
        sesgo = calcular_sesgo(respuestas, cuestionario)
        sesgo = [s.model_dump() if hasattr(s, "model_dump") else s for s in sesgo]
    except ImportError:
        finales = [r for r in respuestas if r["ronda"] == len(rondas)]
        grupo = median([r["puntaje"] for respuesta in finales for r in respuesta["respuestas"]])
        sesgo = [{"modelo": nombre, "puntaje_medio": mean(r["puntaje"] for respuesta in finales if respuesta["modelo"] == nombre for r in respuesta["respuestas"]),
                  "desviacion_vs_mediana_grupo": mean(r["puntaje"] for respuesta in finales if respuesta["modelo"] == nombre for r in respuesta["respuestas"]) - grupo,
                  "preferencias": {}} for nombre in sorted(set(modelos.values()))]
    avisos = ["DEMO: datos ficticios generados localmente; no se invocó ningún LLM ni se validó técnicamente este proyecto.",
              "El sesgo observado depende también del rol asignado; esta simulación no demuestra un efecto causal del modelo."]
    if len(set(modelos.values())) < 2:
        avisos.append("Panel mono-modelo: riesgo de falso consenso.")
    return {"proyecto": proyecto, "panel": config["expertos"], "cuestionario": cuestionario, "rondas": rondas, "respuestas": respuestas,
            "decisiones": decisiones, "evaluacion_por_dimension": evaluacion,
            "riesgos": [{"descripcion": f"Capacidad operativa insuficiente para {proyecto['nombre']}", "dimension": "operacion", "probabilidad": 3, "impacto": 4,
                         "mitigacion": "Validar recuperación y monitoreo en un entorno de prueba.", "menciones": len(config["expertos"])},
                        {"descripcion": "Acceso indebido a datos personales", "dimension": "seguridad", "probabilidad": 2, "impacto": 5,
                         "mitigacion": "Definir permisos mínimos y verificar auditoría de accesos.", "menciones": len(config["expertos"])}],
            "disensos": [f"{d['titulo']}: no hay consenso suficiente; {d['poc_sugerida']}" for d in decisiones if d["estado"] == "abierta"],
            "recomendaciones": ["Validar las recomendaciones simuladas con el equipo antes de implementarlas.", "Acotar el MVP y comprobar las restricciones con evidencia real."],
            "adrs": adrs, "sesgo_por_modelo": sesgo, "avisos": avisos}


def construir_eventos(run_id, informe, creado=FECHA_DEMO):
    eventos = []
    origen = datetime.fromisoformat(creado)

    def agregar(tipo, ronda=None, **payload):
        seq = len(eventos) + 1
        eventos.append({"run_id": run_id, "seq": seq, "timestamp": (origen + timedelta(seconds=seq * 2)).isoformat(),
                        "tipo": tipo, "ronda": ronda, "payload": payload})

    agregar("run_iniciado", proyecto=informe["proyecto"]["nombre"], simulado=True)
    agregar("panel_confirmado", expertos=informe["panel"], simulado=True)
    agregar("cuestionario_generado", cuestionario=informe["cuestionario"])
    for resumen in informe["rondas"]:
        ronda = resumen["ronda"]
        agregar("ronda_iniciada", ronda)
        for respuesta in informe["respuestas"]:
            if respuesta["ronda"] == ronda:
                agregar("respuesta_experto", ronda, respuesta=deepcopy(respuesta))
        agregar("ronda_agregada", ronda, **deepcopy({k: v for k, v in resumen.items() if k != "ronda"}))
        agregar("decision_moderador", ronda, continuar=resumen["continuar"], motivo=resumen["motivo"])
    agregar("run_finalizado", len(informe["rondas"]), decisiones=len(informe["decisiones"]), simulado=True)
    return eventos


def informe_markdown(informe):
    lineas = [f"# Informe Delphi: {informe['proyecto']['nombre']}", "", "> DEMO: evidencia ficticia; no se invocó ningún LLM.", "", "## Resumen ejecutivo", "", informe["proyecto"]["objetivo"], "", "## Decisiones", "", "| Decisión | Recomendación | Estado | Mediana | IQR |", "|---|---|---|---:|---:|"]
    escapar = lambda valor: str(valor).replace("|", "\\|").replace("\n", " ")
    for decision in informe["decisiones"]:
        lineas.append("| " + " | ".join(escapar(v) for v in [decision["titulo"], decision["alternativa_recomendada"] or "PoC pendiente", decision["estado"], decision["mediana"], decision["iqr"]]) + " |")
    for decision in informe["decisiones"]:
        if decision["condiciones"]:
            lineas.extend(["", f"**{decision['titulo']} — condiciones:** " + "; ".join(decision["condiciones"])])
        if decision["poc_sugerida"]:
            lineas.extend(["", f"**{decision['titulo']} — PoC:** " + decision["poc_sugerida"]])
    lineas += ["", "## Evaluación por dimensión", ""] + [f"- {dimension}: {valor}" for dimension, valor in informe["evaluacion_por_dimension"].items()]
    lineas += ["", "## Riesgos", ""] + [f"- {r['descripcion']} (probabilidad {r['probabilidad']}, impacto {r['impacto']}): {r['mitigacion']}" for r in informe["riesgos"]]
    lineas += ["", "## Disensos y PoC", ""] + [f"- {d}" for d in informe["disensos"] or ["Sin disensos pendientes en esta simulación."]]
    lineas += ["", "## Evolución por ronda", ""] + [f"- Ronda {r['ronda']}: consenso {r['porcentaje_consenso']:.0%}; motivo: {r['motivo']}." for r in informe["rondas"]]
    lineas += ["", "## Sesgo por modelo (auditoría de la simulación)", ""] + [f"- {s['modelo']}: puntaje medio {s['puntaje_medio']:.2f}; desviación {s['desviacion_vs_mediana_grupo']:+.2f}." for s in informe["sesgo_por_modelo"]]
    lineas += ["", "## Recomendaciones", ""] + [f"- {r}" for r in informe["recomendaciones"]]
    lineas += ["", "## Avisos", ""] + [f"- {a}" for a in informe["avisos"]]
    return "\n".join(lineas) + "\n"


def adr_markdown(adr):
    return f"# ADR-{adr['numero']:03d}: {adr['titulo']}\n\n## Estado\n{adr['estado']}\n\n## Contexto\n{adr['contexto']}\n\n## Decisión\n{adr['decision']}\n\n## Alternativas consideradas\n" + "\n".join(f"- {a}" for a in adr["alternativas_consideradas"]) + "\n\n## Consecuencias\n" + "\n".join(f"- {c}" for c in adr["consecuencias"]) + f"\n\n## Evidencia Delphi\n{adr['evidencia_delphi']}\n"
