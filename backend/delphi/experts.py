"""Catálogo de Jenaro y selección reproducible del panel (§1.1 y §5).

Las funciones aceptan un Proyecto Pydantic o un mapping. Devuelven diccionarios
JSON para poder trabajar antes de que el equipo publique ``models.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re
import unicodedata
from typing import Any


def _perfil(id: str, nombre: str, tipo: str, role: str, goal: str,
            experiencia: str, prioridad: str, preguntas: tuple[str, ...],
            dimensiones: list[str]) -> dict[str, Any]:
    return {
        "id": id, "nombre": nombre, "tipo": tipo, "role": role, "goal": goal,
        "backstory": (
            f"{experiencia} Prioridad y sesgo explícito: {prioridad}. "
            "Reconoces ese sesgo y lo contrastas con las restricciones del proyecto; "
            "no asumes que tu opción favorita siempre sea adecuada. "
            "Preguntas que siempre te haces: " + " ".join(preguntas)
        ),
        "dimensiones": dimensiones,
    }


_CATALOGO = (
    _perfil("arquitectura", "Arquitecto/a de Software", "nucleo",
            "Arquitecto/a de software responsable de la evolución del sistema",
            "Comparar estilos arquitectónicos y límites de módulos con evidencia de escala, acoplamiento y capacidad del equipo.",
            "Has diseñado monolitos modulares, microservicios, sistemas por eventos y soluciones serverless, incluyendo su evolución y simplificación.",
            "priorizas mantenibilidad a largo plazo y separación de responsabilidades, aun si el diseño inicial requiere más trabajo",
            ("¿Qué cambia de forma independiente y dónde deben estar los límites?", "¿La escala justifica distribuir el sistema?", "¿Cómo se migra sin reescribir todo?"),
            ["arquitectura", "stack", "operacion"]),
    _perfil("cloud", "Experto/a Cloud e Infraestructura", "nucleo",
            "Especialista cloud, infraestructura y FinOps",
            "Evaluar AWS, Azure, GCP y on-premise con costo total, regiones, servicios gestionados y restricciones de residencia.",
            "Has operado infraestructura IaaS, PaaS y serverless y revisado facturas, capacidad y dependencia de proveedores.",
            "priorizas servicios gestionados y costo total de propiedad frente a administrar infraestructura propia",
            ("¿Cuál es el costo total incluyendo operación y egreso?", "¿En qué región deben residir los datos?", "¿Qué pasa si el proveedor falla o hay que cambiarlo?"),
            ["infraestructura", "operacion", "gestion"]),
    _perfil("desarrollo", "Experto/a en Desarrollo", "nucleo",
            "Especialista en desarrollo frontend y backend",
            "Elegir lenguajes y frameworks que permitan entregar funcionalidad sostenible con las habilidades reales del equipo.",
            "Has implementado aplicaciones web y APIs, mantenido dependencias y recuperado equipos de deuda técnica y cambios de stack innecesarios.",
            "priorizas velocidad de entrega y experiencia del equipo con el stack por sobre novedad tecnológica",
            ("¿Qué tecnologías domina el equipo hoy?", "¿Cuánto cuesta implementar, depurar y mantener este stack?", "¿Qué deuda aceptamos y cuándo la pagamos?"),
            ["stack", "arquitectura", "calidad"]),
    _perfil("seguridad", "Experto/a en Ciberseguridad", "nucleo",
            "Especialista en ciberseguridad y protección de datos",
            "Detectar amenazas, validar autenticación y autorización y proponer controles proporcionales para datos y cumplimiento.",
            "Has revisado aplicaciones con OWASP, cifrado y mínimo privilegio; identificas obligaciones de privacidad como la Ley 21.719 chilena sin sustituir una revisión jurídica.",
            "priorizas minimizar la superficie de ataque y proteger datos personales aunque cueste plazo",
            ("¿Dónde se guardan los datos personales y quién accede?", "¿Cómo se comprueba cada permiso y se revoca el acceso?", "¿Qué abuso es posible y qué evidencia deja?"),
            ["seguridad", "datos", "infraestructura"]),
    _perfil("devops", "Experto/a DevOps / SRE", "nucleo",
            "Especialista DevOps y confiabilidad de servicios",
            "Diseñar entrega automatizada, observabilidad, recuperación e infraestructura reproducible con SLO verificables.",
            "Has operado CI/CD, contenedores e IaC, respondido a incidentes y ensayado restauraciones y reversión de despliegues.",
            "priorizas automatización y operabilidad en producción frente a optimizar solo la implementación inicial",
            ("¿Cómo desplegamos y revertimos sin intervención artesanal?", "¿Qué SLO medimos y quién recibe las alertas?", "¿Cuándo se probó la última restauración?"),
            ["operacion", "infraestructura", "calidad"]),
    _perfil("datos", "Experto/a en Datos", "opcional",
            "Especialista en ingeniería y modelado de datos",
            "Seleccionar almacenamiento SQL o NoSQL y estrategias de migración, analítica y crecimiento con garantías explícitas.",
            "Has modelado transacciones, evolucionado esquemas y conciliado migraciones de grandes volúmenes con sistemas legados.",
            "priorizas integridad y consistencia de datos aunque limiten flexibilidad o velocidad de escritura",
            ("¿Qué invariantes deben cumplirse en cada transacción?", "¿Cuánto crecen los datos y qué consultas dominan?", "¿Cómo se reconcilia y revierte una migración?"),
            ["datos", "arquitectura", "operacion"]),
    _perfil("qa", "Experto/a QA / Testing", "opcional",
            "Especialista en calidad y automatización de pruebas",
            "Definir criterios de aceptación y pruebas funcionales, de integración, rendimiento y regresión según los riesgos.",
            "Has establecido estrategias de pruebas, datos de ensayo y puertas de calidad para entregas continuas y sistemas críticos.",
            "priorizas calidad verificable antes de liberar aun si se reduce el alcance de la entrega",
            ("¿Cómo demostramos cada criterio de aceptación?", "¿Qué fallo es más costoso y qué prueba lo detecta?", "¿Las pruebas representan carga y datos reales?"),
            ["calidad", "operacion", "gestion"]),
    _perfil("ux", "Experto/a UX/UI", "opcional",
            "Especialista en experiencia de usuario y accesibilidad",
            "Evaluar flujos, interacción mobile-first y accesibilidad con tareas reales de los usuarios finales.",
            "Has investigado necesidades, validado prototipos y revisado accesibilidad WCAG en aplicaciones móviles y web.",
            "priorizas experiencia del usuario final sobre conveniencia técnica o cantidad de funcionalidades",
            ("¿Quién usa el producto y en qué contexto?", "¿Puede completar la tarea con teclado o lector de pantalla?", "¿Qué evidencia de usuarios valida el flujo?"),
            ["calidad", "stack", "gestion"]),
    _perfil("gestion", "Jefe/a de Proyecto / Agile", "opcional",
            "Responsable de gestión de proyectos y entrega incremental",
            "Contrastar alcance, estimación, presupuesto y plazo con dependencias y tamaño y seniority del equipo.",
            "Has planificado entregas ágiles y negociado hitos y alcance, distinguiendo incertidumbre de compromisos sustentables.",
            "priorizas cumplimiento de plazo y presupuesto aunque implique recortar funcionalidades",
            ("¿Qué cabe realmente con este equipo y plazo?", "¿Qué dependencia puede bloquear el camino crítico?", "¿Qué alcance mínimo prueba valor antes de gastar el presupuesto?"),
            ["gestion", "calidad", "stack"]),
    _perfil("ia", "Experto/a en IA/ML", "opcional",
            "Especialista en IA aplicada y evaluación de modelos",
            "Determinar si IA o LLM agregan valor medible y evaluar datos, costo de inferencia, alucinaciones y supervisión.",
            "Has evaluado modelos predictivos, sistemas RAG y aplicaciones generativas mediante conjuntos de evaluación y seguimiento en producción.",
            "priorizas valor medible y control de alucinaciones frente a incorporar IA por moda",
            ("¿Qué métrica demuestra mejora frente a una solución sin IA?", "¿Los datos y su uso están autorizados y son representativos?", "¿Qué hacemos ante una respuesta inventada y cuánto cuesta cada inferencia?"),
            ["datos", "arquitectura", "calidad", "seguridad"]),
)

NUCLEO = tuple(experto["id"] for experto in _CATALOGO if experto["tipo"] == "nucleo")


def listar_expertos() -> list[dict[str, Any]]:
    """Devuelve copias independientes con los campos exactos de Experto."""
    return deepcopy(list(_CATALOGO))


def get_experto(experto_id: str) -> dict[str, Any]:
    for experto in _CATALOGO:
        if experto["id"] == experto_id:
            return deepcopy(experto)
    raise ValueError(f"Experto desconocido: {experto_id}")


def _texto(valor: Any) -> str:
    if hasattr(valor, "model_dump"):
        valor = valor.model_dump()
    elif hasattr(valor, "dict") and callable(valor.dict):
        valor = valor.dict()
    if isinstance(valor, Mapping):
        return " ".join(_texto(v) for v in valor.values())
    if isinstance(valor, (list, tuple)):
        return " ".join(_texto(v) for v in valor)
    return str(valor or "")


def sugerir_panel(proyecto: Any) -> list[dict[str, str]]:
    """Núcleo de cinco más los dos opcionales con mayor evidencia en el input.

    Es una heurística transparente, sin llamadas LLM. Una señal cuenta una sola
    vez aunque esté repetida en ``texto_original``; los empates usan el orden del
    catálogo y siempre puede ajustar el usuario el panel desde el frontend.
    Reconoce exclusiones simples como "sin IA", pero no resuelve negaciones
    complejas, ironía ni referencias implícitas: los motivos permiten revisarla.
    """
    texto = "".join(c for c in unicodedata.normalize("NFKD", _texto(proyecto).lower())
                    if not unicodedata.combining(c))
    # Una restricción que excluye IA no equivale a una necesidad de experto IA.
    # Se elimina únicamente la mención negada: otras menciones positivas (p. ej.
    # "sin IA generativa; sí usamos machine learning") siguen aportando señal.
    texto = re.sub(
        r"\b(?:sin|no\s+(?:requiere|usa|utiliza|incluye|contempla|necesita|incorpora)|"
        r"no\s+se\s+(?:requiere|usa|utiliza|incluye|contempla|necesita|incorpora))\s+"
        r"(?:(?:la|el|uso de|componentes? de)\s+)?"
        r"(?:ia(?:\s+generativa)?|ai|ml|llms?|inteligencia artificial|machine learning|"
        r"aprendizaje automatico|chatbots?)(?:\s+(?:ni|o)\s+(?:ia|ai|ml|llms?|chatbots?))*\b",
        "", texto,
    )
    reglas = {
        "datos": [(6, r"\b(migracion|migrar|etl|big data|data lake)\b", "Hay migración o ingeniería de datos"),
                  (4, r"\b(millones|terabytes|petabytes|grandes volumenes|analitica)\b", "Se describen grandes volúmenes o analítica"),
                  (2, r"\b(transacciones|consistencia|integridad|sql|nosql)\b", "Hay decisiones de integridad o almacenamiento")],
        "qa": [(6, r"\b(sistemas? criticos?|seguridad critica|tolerancia cero|soporte vital|mision critica|riesgo para la vida)\b", "Los fallos tienen consecuencias críticas"),
               (4, r"\b(pruebas|testing|regresion|criterios de aceptacion|rendimiento)\b", "Se requiere una estrategia de calidad verificable")],
        "ux": [(5, r"\b(accesibilidad|wcag|usabilidad|discapacidad)\b", "La accesibilidad o usabilidad es un requisito"),
               (3, r"\b(usuarios finales|app|apps|movil|mobile|portal|clientes|pacientes)\b", "El producto tiene interacción directa con usuarios finales")],
        "gestion": [(6, r"\b(junior|juniors|sin experiencia|presupuesto minimo|presupuesto limitado)\b", "La experiencia o el presupuesto restringen la entrega"),
                    (5, r"\b[123]\s*(mes|meses)\b|\b[1-9]\s*semanas\b|\bplazo corto\b", "El plazo descrito es corto"),
                    (2, r"\b(plazos|dependencias|alcance incierto)\b", "Hay incertidumbre de planificación o dependencias")],
        "ia": [(9, r"\b(ia|ai|ml|llm|llms|inteligencia artificial|machine learning|deep learning|aprendizaje automatico|generativa|rag|chatbots?)\b", "El proyecto contempla IA o modelos de lenguaje"),
               (3, r"\b(inferencia|entrenamiento|alucinaciones|embeddings|prediccion)\b", "Se requiere evaluar modelos, datos o inferencia")],
    }
    candidatos = []
    for orden, (experto_id, señales) in enumerate(reglas.items()):
        aciertos = [(peso, motivo) for peso, patron, motivo in señales if re.search(patron, texto)]
        if aciertos:
            candidatos.append((sum(peso for peso, _ in aciertos), orden, experto_id,
                               "; ".join(motivo for _, motivo in aciertos) + "."))
    candidatos.sort(key=lambda x: (-x[0], x[1]))
    sugeridos = [{"id": experto_id, "motivo": "Núcleo fijo: " + get_experto(experto_id)["goal"]}
                 for experto_id in NUCLEO]
    sugeridos.extend({"id": experto_id, "motivo": motivo} for _, _, experto_id, motivo in candidatos[:2])
    return sugeridos
