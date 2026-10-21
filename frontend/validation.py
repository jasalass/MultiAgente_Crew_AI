"""Validaciones de interacción, independientes de Streamlit y del backend."""

CORE = {"arquitectura", "cloud", "desarrollo", "seguridad", "devops"}
RELATED = (("arquitectura", "desarrollo"), ("cloud", "devops"), ("seguridad", "datos"))


def validar_config(config, modelos=()):
    """Devuelve errores legibles antes de POST /runs; la API debe revalidar."""
    errores = []
    proyecto = config.get("proyecto", {})
    for campo in ("nombre", "objetivo", "texto_original"):
        if not str(proyecto.get(campo, "")).strip():
            errores.append(f"Completa el campo {campo.replace('_', ' ')} del proyecto.")
    panel = config.get("expertos", [])
    if len(panel) != len(set(panel)) or not 5 <= len(panel) <= 7 or not CORE.issubset(panel):
        errores.append("El panel debe incluir los cinco expertos del núcleo y hasta dos opcionales.")
    minimo, maximo = config.get("min_rondas", 2), config.get("max_rondas", 3)
    if not 2 <= minimo <= maximo <= 3:
        errores.append("Las rondas deben cumplir 2 ≤ mínimo ≤ máximo ≤ 3.")
    if not 0 <= config.get("umbral_iqr", 1) <= 4:
        errores.append("El umbral IQR debe estar entre 0 y 4.")
    if not 0 < config.get("umbral_consenso_global", .8) <= 1:
        errores.append("El consenso global debe estar entre 1 % y 100 %.")
    modo = config.get("asignacion_modelos")
    if modo not in {"auto", "seed", "manual", "mono"}:
        errores.append("Selecciona un modo de asignación válido.")
    if modo == "seed" and not isinstance(config.get("seed"), int):
        errores.append("Indica una semilla entera para la asignación reproducible.")
    if modo in {"manual", "mono"}:
        asignacion = config.get("modelos_manual") or {}
        disponibles = {m["nombre"]: m for m in modelos}
        if any(asignacion.get(rol) not in disponibles for rol in panel):
            errores.append("Asigna un modelo disponible a cada experto.")
        elif modo == "mono" and len({asignacion[rol] for rol in panel}) != 1:
            errores.append("El control mono debe usar el mismo modelo en todo el panel.")
        elif modo == "manual":
            for primero, segundo in RELATED:
                if primero in panel and segundo in panel and asignacion[primero] == asignacion[segundo]:
                    errores.append(f"{primero.capitalize()} y {segundo} deben usar modelos distintos.")
    return errores


def proyecto_a_markdown(proyecto):
    secciones = (
        ("Objetivo y contexto", "objetivo"), ("Usuarios y volumen", "usuarios_volumen"),
        ("Requisitos funcionales", "requisitos_funcionales"),
        ("Requisitos no funcionales", "requisitos_no_funcionales"),
        ("Restricciones", "restricciones"), ("Equipo", "equipo"),
        ("Integraciones", "integraciones"), ("Decisiones a evaluar", "decisiones_a_evaluar"),
    )
    texto = [f"# {proyecto.get('nombre', '')}"]
    for titulo, campo in secciones:
        valor = proyecto.get(campo, "")
        contenido = "\n".join(f"- {v}" for v in valor) if isinstance(valor, list) else str(valor)
        texto.extend((f"## {titulo}", contenido))
    return "\n\n".join(texto)
