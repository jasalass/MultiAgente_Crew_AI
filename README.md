# MultiAgente_Crew_AI — Panel Delphi para Decisiones en Proyectos Informáticos

Sistema que recibe como **input la descripción de un proyecto informático** y aplica la **técnica Delphi** con un panel de **expertos de TI** simulados por LLM de familias distintas: Arquitectura, Cloud, Desarrollo, Seguridad, DevOps, Datos, QA, UX, Gestión e IA. Un **agente Moderador** dirige rondas anónimas para que el panel contraste opiniones sobre las **decisiones clave del proyecto**: estilo de arquitectura, proveedor cloud, stack, base de datos, estrategia de despliegue, seguridad, plazos, etc.

**Objetivo: tomar mejores decisiones antes de construir.** El sistema no entrega una opinión aislada. Entrega:

- **Decisiones recomendadas** con su nivel de consenso: *firme*, *condicionada* o *abierta*.
- **ADR** (*Architecture Decision Records*) listos para incorporar al repositorio del proyecto.
- **Riesgos técnicos** priorizados y los **desacuerdos** que conviene resolver con una prueba de concepto (*PoC*) o un *spike*.

| Pieza | Tecnología |
|-------|------------|
| Agente Moderador + panel multiagente | CrewAI `Process.hierarchical` con `manager_agent` propio (base: `4-multiagent_crewai_hierarchical.py`, IL2.3) |
| Diversidad de modelos | Un LLM de una familia distinta por integrante (Mistral, Groq, Google AI Studio) |
| Backend / API | FastAPI: ejecuta los análisis en segundo plano y los persiste |
| Frontend | Streamlit: configurar, lanzar, seguir en vivo, ver decisiones y ADR, y comparar |

Se construye **directamente la versión final**, sin versiones intermedias.

**Equipo:** Pamela · Jenaro · Juan

---

## 1. Técnica Delphi aplicada a proyectos informáticos

La técnica Delphi es un método estructurado para obtener consenso entre expertos. Sus rasgos esenciales son:

1. **Anonimato:** los expertos no saben quién opinó qué. Así se evita que, por ejemplo, la opinión del arquitecto arrastre al resto.
2. **Iteración:** hay varias rondas de cuestionario.
3. **Retroalimentación controlada:** entre una ronda y otra, el moderador entrega un resumen estadístico y los argumentos anónimos del grupo.
4. **Respuesta estadística del grupo:** se informa la mediana y el rango intercuartílico (IQR), no un promedio.

### 1.1 Panel de expertos de TI

El sistema tiene un **catálogo de 10 expertos**. Para cada proyecto se arma un panel de **5 a 7**: un **núcleo fijo** más los **expertos opcionales** que el proyecto requiera. El sistema sugiere el panel según el input y el usuario puede ajustarlo en el frontend.

| Rol (`id`) | Tipo | Evalúa | Sesgo / prioridad explícita del perfil |
|------------|------|--------|----------------------------------------|
| Arquitecto/a de Software (`arquitectura`) | Núcleo | Estilo arquitectónico (monolito modular, microservicios, serverless, eventos), acoplamiento, escalabilidad, evolución | Prioriza la mantenibilidad a largo plazo y la separación de responsabilidades |
| Experto/a Cloud e Infraestructura (`cloud`) | Núcleo | Proveedor (AWS, Azure, GCP u *on-premise*), IaaS/PaaS/serverless, costos cloud (FinOps), regiones | Prioriza los servicios gestionados y el costo total de propiedad |
| Experto/a en Desarrollo (`desarrollo`) | Núcleo | Lenguajes, frameworks, stack frontend y backend, productividad, deuda técnica | Prioriza la velocidad de entrega y la experiencia del equipo con el stack |
| Experto/a en Ciberseguridad (`seguridad`) | Núcleo | Autenticación y autorización, OWASP, cifrado, protección de datos personales (p. ej., Ley 21.719 en Chile), cumplimiento | Prioriza minimizar la superficie de ataque, aunque cueste plazo |
| Experto/a DevOps / SRE (`devops`) | Núcleo | CI/CD, contenedores, IaC, observabilidad, disponibilidad (SLO), recuperación ante desastres | Prioriza la automatización y la operabilidad en producción |
| Experto/a en Datos (`datos`) | Opcional | Modelado, SQL frente a NoSQL, volumen, analítica, migración de datos | Prioriza la integridad y la consistencia de los datos |
| Experto/a QA / Testing (`qa`) | Opcional | Estrategia de pruebas, automatización, criterios de aceptación, rendimiento | Prioriza la calidad verificable antes de liberar |
| Experto/a UX/UI (`ux`) | Opcional | Usabilidad, accesibilidad (WCAG), flujos, *mobile-first* | Prioriza la experiencia del usuario final |
| Jefe/a de Proyecto / Agile (`gestion`) | Opcional | Alcance, estimación, plazos, metodología, tamaño y *seniority* del equipo | Prioriza el cumplimiento de plazo y presupuesto |
| Experto/a en IA/ML (`ia`) | Opcional | Uso de LLM y modelos, datos de entrenamiento, costos de inferencia, riesgos de la IA | Prioriza el valor medible y el control de las alucinaciones |

> Que los sesgos de los perfiles sean **explícitos y distintos** es intencional: así el panel diverge en la ronda 1, como pasaría con expertos reales, y Delphi tiene algo que hacer converger.

### 1.2 Qué se pregunta: evaluaciones y decisiones

El Moderador genera el cuestionario a partir del proyecto. Los ítems se agrupan en **dimensiones**: Arquitectura, Infraestructura/Cloud, Stack, Datos, Seguridad, Calidad, Operación y Gestión. Hay dos tipos de ítem:

| Tipo | Ejemplo | Respuesta |
|------|---------|-----------|
| **Evaluación** | "¿Qué tan viable es cumplir el plazo de 4 meses con el equipo descrito?" | Likert 1–5 + justificación |
| **Decisión entre alternativas** | "Estilo de arquitectura: (a) monolito modular, (b) microservicios, (c) serverless" | Cada alternativa se puntúa con Likert 1–5 (adecuación al proyecto) + justificación |

**Regla de recomendación para cada decisión** (se calcula en el código, no la decide el LLM):

| Resultado | Condición | Significado |
|-----------|-----------|-------------|
| ✅ **Firme** | La mejor alternativa tiene consenso (IQR ≤ 1), mediana ≥ 4 y supera en ≥ 1 punto a la segunda | Adoptar |
| ⚠️ **Condicionada** | Hay consenso, pero la diferencia con la segunda es < 1, o la mediana es 3 | Adoptar con condiciones o revisarla en un hito definido |
| ❓ **Abierta** | Sin consenso al terminar la última ronda | Resolver con una PoC o un *spike* antes de comprometerse |

### 1.3 Arquitectura del sistema

```
┌─────────────────────────── FRONTEND (Streamlit) ───────────────────────────┐
│ Nuevo análisis │ Ejecución en vivo │ Decisiones y ADR │ Historial/Comparar │
└───────────────────────────────┬────────────────────────────────────────────┘
                                │ HTTP (JSON) — polling de eventos
┌───────────────────────────────▼──────────────── BACKEND (FastAPI) ─────────┐
│  /runs  /runs/{id}  /runs/{id}/eventos  /runs/{id}/informe  /expertos      │
│  RunStore (persistencia)   ·   ejecución en segundo plano   ·   cancelación│
└───────────────────────────────┬────────────────────────────────────────────┘
                                │ DelphiEngine.run(config, on_event)
┌───────────────────────────────▼──────────────── MOTOR DELPHI (CrewAI) ─────┐
│                   ┌─────────────────────────────┐                          │
│                   │      MODERADOR DELPHI       │  manager_agent           │
│                   │ cuestionario · delegación   │  tools: DelphiStatsTool, │
│                   │ feedback · ¿otra ronda?     │         AnonymizerTool   │
│                   └──────────────┬──────────────┘                          │
│     ┌──────────┬──────────┬──────┴─────┬───────────┬──────────┐            │
│     ▼          ▼          ▼            ▼           ▼          ▼            │
│ Arquitectura  Cloud   Desarrollo   Seguridad    DevOps    (opcionales:     │
│  (Mistral)  (Qwen)    (Gemini)     (Mistral)    (Gemini)   Datos, QA, UX,  │
│                                                            Gestión, IA)    │
│   ModelPool: modelos distintos en roles afines · stats.py: mediana/IQR     │
└────────────────────────────────────────────────────────────────────────────┘
```

### 1.4 Flujo de una ejecución

1. **Ingesta:** el usuario completa la plantilla del proyecto (§1.6) en el frontend o sube un `.md`.
2. **Panel:** el sistema sugiere los expertos (núcleo más opcionales relevantes) y el usuario confirma o ajusta.
3. **Cuestionario:** el Moderador identifica las **decisiones clave** y genera los ítems de evaluación y de decisión por dimensión.
4. **Ronda k:** el Moderador delega en cada experto **por separado**. Cada experto responde en JSON usando *su* modelo.
5. **Agregación:** `DelphiStatsTool` calcula, sin LLM, la mediana, Q1, Q3 y el IQR de cada ítem y cada alternativa. `AnonymizerTool` resume los argumentos sin revelar autor ni modelo.
6. **Decisión de continuar:** el Moderador propone si hace falta otra ronda, y **el código impone los límites**. Si hay otra ronda, cada experto recibe el feedback anónimo junto con su respuesta anterior.
7. **Informe:** decisiones recomendadas (firme, condicionada o abierta), ADR, riesgos técnicos, evaluación por dimensión, disensos con la PoC sugerida y sesgo por modelo.

Cada paso emite un **evento**, que el frontend muestra en vivo.

### 1.5 Reglas Delphi (acordadas por los tres, editables desde el frontend)

| Parámetro | Valor por defecto | Nota |
|-----------|-------------------|------|
| Tamaño del panel | 5 núcleo + hasta 2 opcionales (máx. 7) | Limitado por la cuota gratuita |
| Escala | Likert 1–5 + justificación de 1 a 3 frases | |
| Rondas | mínimo 2, máximo 3 | |
| Consenso por ítem o alternativa | IQR ≤ 1 | |
| Consenso global | ≥ 80 % de los ítems con consenso | |
| Estabilidad | variación de la mediana < 0,5 entre rondas | Criterio alternativo de corte |
| Outliers | Si la respuesta de un experto queda fuera de [Q1, Q3], **debe** justificar si mantiene su postura o la cambia | |
| Diversidad | Modelos de **familias distintas** (§3); los roles afines (Arquitectura–Desarrollo, Cloud–DevOps, Seguridad–Datos) nunca comparten modelo | Evita el falso consenso |
| Independencia | El Moderador delega **solo** el proyecto, el cuestionario y el feedback anónimo de la ronda anterior | El código lo verifica (`guard_independencia`) |
| Cuestionario | 3 a 5 decisiones clave + 6 a 10 ítems de evaluación | Acotado por la cuota |

### 1.6 Input: plantilla de proyecto informático

`data/proyectos/<nombre>.md` (el frontend ofrece el mismo formulario):

```markdown
# <Nombre del proyecto>
## Objetivo y contexto          ¿Qué problema resuelve? ¿Para quién?
## Usuarios y volumen           usuarios concurrentes, crecimiento esperado, picos
## Requisitos funcionales       los 5–10 principales
## Requisitos no funcionales    disponibilidad, latencia, seguridad, accesibilidad
## Restricciones                presupuesto, plazo, tecnologías obligatorias, cloud existente, normativa
## Equipo                       tamaño, seniority, tecnologías que domina
## Integraciones                sistemas externos, APIs, sistemas legados
## Decisiones a evaluar (opc.)  alternativas que el equipo ya está considerando
```

### 1.7 Output

`outputs/runs/<run_id>/`:

- `informe.md`: resumen ejecutivo, decisiones recomendadas, evaluación por dimensión, riesgos, disensos y PoC sugeridas, evolución por ronda y sesgo por modelo.
- `adr/ADR-001-<decision>.md`, …: **un ADR por decisión**, con el formato *Contexto · Decisión · Alternativas consideradas · Consecuencias · Estado (Aceptada / Condicionada / Abierta) · Evidencia Delphi* (mediana, IQR y argumentos).
- `rondas.json` y `eventos.jsonl`: trazabilidad completa para auditar.

---

## 2. Estructura del repositorio

```
MultiAgente_Crew_AI/
├── README.md
├── requirements.txt               # crewai, openai, fastapi, uvicorn, streamlit, plotly, pydantic, python-dotenv
├── .env.example                   # bloques LLM_*_<NOMBRE> (SIN keys reales)
├── .gitignore                     # .env, outputs/, __pycache__/
├── data/
│   ├── plantilla_proyecto.md      # plantilla de input (§1.6)          — Juan
│   └── proyectos/                 # proyectos informáticos de ejemplo  — Juan
├── backend/
│   ├── delphi/
│   │   ├── models.py              # contratos Pydantic (§4)            — los tres
│   │   ├── config.py              # ModelPool (§3)                     — Juan
│   │   ├── stats.py               # mediana, IQR, consenso, estabilidad, regla de recomendación — Juan
│   │   ├── llm_io.py              # parseo/validación JSON + reintento — Juan
│   │   ├── project_loader.py      # parseo de la plantilla → Proyecto  — Juan
│   │   ├── experts.py             # catálogo de 10 expertos TI + sugerir_panel() — Jenaro
│   │   ├── prompts.py             # prompts de experto: ronda 1 y ronda k — Jenaro
│   │   ├── anonymizer.py          # AnonymizerTool + síntesis de argumentos — Jenaro
│   │   ├── bias.py                # sesgo por modelo + experimento de control — Jenaro
│   │   ├── tools.py               # DelphiStatsTool                    — Pamela
│   │   ├── crew.py                # Moderador (manager_agent) + panel  — Pamela
│   │   ├── engine.py              # DelphiEngine: rondas, eventos, límites — Pamela
│   │   ├── report.py              # informe.md                         — Pamela
│   │   └── adr.py                 # generación de ADR por decisión     — Pamela
│   ├── api/
│   │   ├── main.py                # FastAPI                            — Juan
│   │   └── store.py               # RunStore                           — Juan
│   └── cli.py                     # correr el motor sin API (para depurar) — Pamela
├── frontend/
│   ├── app.py                     # Streamlit multipágina              — Jenaro
│   ├── pages/                     # 1_Nuevo, 2_En_vivo, 3_Decisiones, 4_Historial
│   ├── api_client.py              # cliente HTTP de la API             — Jenaro
│   └── mocks/                     # runs falsos para desarrollar sin backend — Jenaro
├── outputs/runs/<run_id>/         # informe.md, adr/, rondas.json, eventos.jsonl
└── tests/
```

---

## 3. Panel multi-modelo: un LLM distinto por integrante

**Objetivo: reducir los sesgos compartidos.** Si todos los expertos son el mismo modelo con distinto `backstory`, comparten los mismos datos de entrenamiento y los mismos puntos ciegos. Por ejemplo, un modelo que tienda a recomendar microservicios lo hará con los 7 "expertos". El resultado es un **falso consenso**. Por eso cada integrante aporta su API key con un **modelo de una familia distinta**, y el panel mezcla esos modelos. La cuota extra es un beneficio secundario.

**Proveedores disponibles.** Todos tienen API compatible con OpenAI y plan gratuito, así que funcionan con el mismo código, cambiando solo `LLM_BASE_URL`, `LLM_API_KEY` y `LLM_MODEL`.

| Proveedor | `LLM_BASE_URL` | Obtener key | Familias de modelos | Notas |
|-----------|----------------|-------------|---------------------|-------|
| **Mistral AI** | `https://api.mistral.ai/v1` | https://console.mistral.ai/api-keys | Mistral, Ministral | `mistral-small-latest` puede dar 429 (límite de tasa); en ese caso usar `ministral-8b-latest`. |
| **Groq** | `https://api.groq.com/openai/v1` | https://console.groq.com/keys | Varias familias de terceros, como Qwen (Alibaba) | Inferencia muy rápida. El catálogo gratuito actual son sobre todo **modelos de razonamiento**, que gastan parte de `max_tokens` en pensar: con valores bajos pueden devolver una respuesta vacía. Revisar el catálogo vigente. |
| **Google AI Studio** | `https://generativelanguage.googleapis.com/v1beta/openai/` | https://aistudio.google.com/apikey | Gemini | Es la misma cuenta de Google que se usa en Colab. |

> Lo que importa para la diversidad es la **familia del modelo**, no el proveedor: dos integrantes pueden usar Groq si cada uno elige una familia distinta.

**Asignación sugerida.** Antes de usarla hay que comprobar los nombres vigentes de cada modelo.

| Integrante | Proveedor | Familia | `LLM_MODEL` (ejemplo) |
|------------|-----------|---------|-----------------------|
| Juan | Mistral AI | Mistral (Mistral AI) | `mistral-small-latest` |
| Pamela | Groq | Qwen (Alibaba) | `qwen/qwen3.8-27b` |
| Jenaro | Google AI Studio | Gemini (Google) | el modelo *flash* gratuito vigente |

**`.env`** (cada integrante agrega su bloque; el `.env` nunca se sube al repositorio):

```env
LLM_API_KEY_JUAN=...
LLM_BASE_URL_JUAN=https://api.mistral.ai/v1
LLM_MODEL_JUAN=mistral-small-latest

LLM_API_KEY_PAMELA=...
LLM_BASE_URL_PAMELA=https://api.groq.com/openai/v1
LLM_MODEL_PAMELA=qwen/qwen3.8-27b

LLM_API_KEY_JENARO=...
LLM_BASE_URL_JENARO=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL_JENARO=<modelo-gemini-flash-vigente>
```

**`ModelPool` (`backend/delphi/config.py`):**

- Carga los bloques `LLM_*_<NOMBRE>` y expone `listar_modelos()`, que devuelve solo el nombre, el proveedor y la familia (**nunca la key**), `get_llm(agente_id) -> crewai.LLM` y `get_client(agente_id) -> OpenAI`.
- **Asignación de modelos a roles:**
  - `auto`: reparte los modelos de forma equilibrada; con 3 modelos y 6 expertos, cada modelo atiende a 2. Los **roles afines nunca comparten modelo** (Arquitectura–Desarrollo, Cloud–DevOps, Seguridad–Datos), porque son los que más se solapan en sus opiniones.
  - `seed`: rota la asignación entre ejecuciones, para separar el sesgo del rol del sesgo del modelo.
  - `manual`: se elige desde el frontend.
  - `mono`: todo el panel usa un solo modelo. Sirve como control para el experimento de sesgo. Si hay menos de 2 familias disponibles, el sistema avisa: *"panel mono-modelo: riesgo de falso consenso"*.
- **Moderador neutral:** usa un modelo distinto del de la mayoría del panel.
- **Errores 429 o caídas:** reintento con espera progresiva (*backoff*) en el mismo modelo. Solo si el error persiste se cambia de modelo, y el cambio se registra y se emite como evento.

**Medición del sesgo (aparece en el frontend y en el informe):**

- **Sesgo por modelo:** el puntaje medio de cada modelo, y su **preferencia por alternativas**. Por ejemplo: "el modelo X puntúa microservicios 1,2 puntos por encima del grupo".
- **Experimento de control:** el mismo proyecto con un panel `mono` y con uno `auto`. Se compara el IQR de la ronda 1, las rondas hasta el consenso y **si cambian las decisiones recomendadas**.

> ⚠️ Cada key es personal: se guarda solo en el `.env` local de cada uno y nunca va en el repositorio ni en el chat del grupo.

---

## 4. Contratos compartidos (se congelan el día 1)

Estos contratos son los que permiten trabajar **los tres en paralelo desde el primer día**: el frontend se desarrolla contra *mocks*, el motor contra la CLI y la API contra un motor *stub*. Ningún contrato se cambia sin el visto bueno de los tres.

### 4.1 Modelos de datos (`backend/delphi/models.py`)

```python
Dimension = Literal["arquitectura", "infraestructura", "stack", "datos",
                    "seguridad", "calidad", "operacion", "gestion"]

class Proyecto(BaseModel):
    nombre: str
    objetivo: str
    usuarios_volumen: str = ""
    requisitos_funcionales: list[str] = []
    requisitos_no_funcionales: list[str] = []
    restricciones: list[str] = []          # presupuesto, plazo, tecnologías obligatorias, normativa
    equipo: str = ""
    integraciones: list[str] = []
    decisiones_a_evaluar: list[str] = []   # opcional: alternativas que el equipo ya considera
    texto_original: str                    # el .md completo

class Experto(BaseModel):
    id: str                                # "arquitectura", "cloud", ...
    nombre: str
    tipo: Literal["nucleo", "opcional"]
    role: str
    goal: str
    backstory: str
    dimensiones: list[Dimension]           # en qué dimensiones opina con más peso

class ConfigRun(BaseModel):                # lo que envía el frontend
    proyecto: Proyecto
    expertos: list[str]                    # ids; por defecto, sugerir_panel(proyecto)
    asignacion_modelos: Literal["auto", "seed", "manual", "mono"] = "auto"
    modelos_manual: dict[str, str] | None = None   # rol -> nombre de modelo
    seed: int | None = None
    min_rondas: int = 2
    max_rondas: int = 3
    umbral_iqr: float = 1.0
    umbral_consenso_global: float = 0.8

class Item(BaseModel):
    id: str                                # "ARQ-E1" (evaluación) o "ARQ-D1-a" (alternativa)
    dimension: Dimension
    tipo: Literal["evaluacion", "alternativa"]
    pregunta: str
    decision_id: str | None = None         # "ARQ-D1": agrupa las alternativas de una decisión
    alternativa: str | None = None         # "Monolito modular"

class Decision(BaseModel):
    id: str                                # "ARQ-D1"
    dimension: Dimension
    titulo: str                            # "Estilo de arquitectura"
    alternativas: list[str]

class Cuestionario(BaseModel):
    decisiones: list[Decision]
    items: list[Item]                      # evaluaciones + una alternativa por ítem

class RespuestaItem(BaseModel):
    item_id: str
    puntaje: int = Field(ge=1, le=5)
    justificacion: str

class RespuestaExperto(BaseModel):
    experto_id: str                        # "E1".."E7": anónimo hacia los demás expertos
    rol: str                               # solo para auditoría; NUNCA se muestra a otros expertos
    modelo: str                            # solo para auditoría y medición de sesgo
    ronda: int
    respuestas: list[RespuestaItem]
    riesgos_detectados: list[str] = []     # riesgos técnicos que el experto quiere señalar

class EstadisticaItem(BaseModel):
    item_id: str
    mediana: float
    q1: float
    q3: float
    iqr: float
    consenso: bool
    argumentos_a_favor: list[str]
    argumentos_en_contra: list[str]

class ResumenRonda(BaseModel):
    ronda: int
    estadisticas: list[EstadisticaItem]
    porcentaje_consenso: float
    continuar: bool
    motivo: str                            # "consenso", "estabilidad", "max_rondas", "moderador"

class DecisionRecomendada(BaseModel):
    decision_id: str
    titulo: str
    alternativa_recomendada: str | None    # None si queda abierta
    estado: Literal["firme", "condicionada", "abierta"]
    mediana: float
    iqr: float
    margen_vs_segunda: float
    condiciones: list[str]                 # p. ej. "revisar si se superan 10k usuarios concurrentes"
    poc_sugerida: str | None               # solo si queda abierta

class Riesgo(BaseModel):
    descripcion: str
    dimension: Dimension
    probabilidad: int = Field(ge=1, le=5)
    impacto: int = Field(ge=1, le=5)
    mitigacion: str
    menciones: int                         # cuántos expertos lo señalaron

class SesgoModelo(BaseModel):
    modelo: str
    puntaje_medio: float
    desviacion_vs_mediana_grupo: float
    preferencias: dict[str, float]         # alternativa -> desviación respecto del grupo

class ADR(BaseModel):
    numero: int
    titulo: str
    estado: Literal["aceptada", "condicionada", "abierta"]
    contexto: str
    decision: str
    alternativas_consideradas: list[str]
    consecuencias: list[str]
    evidencia_delphi: str                  # mediana, IQR, rondas y argumentos clave

class InformeDelphi(BaseModel):
    proyecto: Proyecto
    panel: list[str]
    cuestionario: Cuestionario
    rondas: list[ResumenRonda]
    respuestas: list[RespuestaExperto]
    decisiones: list[DecisionRecomendada]
    evaluacion_por_dimension: dict[str, float]     # dimensión -> mediana final
    riesgos: list[Riesgo]
    disensos: list[str]
    recomendaciones: list[str]
    adrs: list[ADR]
    sesgo_por_modelo: list[SesgoModelo]
    avisos: list[str]                      # p. ej. "panel mono-modelo"

class EventoDelphi(BaseModel):             # lo que consume el frontend en vivo
    run_id: str
    seq: int                               # incremental, para pedir solo los eventos nuevos
    timestamp: datetime
    tipo: Literal["run_iniciado", "panel_confirmado", "cuestionario_generado",
                  "ronda_iniciada", "respuesta_experto", "ronda_agregada",
                  "decision_moderador", "cambio_modelo", "run_finalizado",
                  "run_cancelado", "error"]
    ronda: int | None = None
    payload: dict

class EstadoRun(BaseModel):
    run_id: str
    estado: Literal["en_cola", "ejecutando", "finalizado", "cancelado", "error"]
    ronda_actual: int
    config: ConfigRun
    creado: datetime
    finalizado: datetime | None = None
```

### 4.2 API (`backend/api/main.py`)

| Método | Ruta | Devuelve |
|--------|------|----------|
| `GET` | `/modelos` | Modelos disponibles en `ModelPool`: nombre, proveedor y familia (sin keys) |
| `GET` | `/expertos` | Catálogo de `Experto` |
| `POST` | `/panel/sugerir` (body `Proyecto`) | Lista de ids de experto sugeridos, con el motivo de cada uno |
| `POST` | `/proyectos/parsear` (body: texto `.md`) | `Proyecto` |
| `POST` | `/runs` (body `ConfigRun`) | `{run_id}`; lanza el análisis en segundo plano |
| `GET` | `/runs` | Lista de `EstadoRun` (historial) |
| `GET` | `/runs/{id}` | `EstadoRun` |
| `GET` | `/runs/{id}/eventos?desde=<seq>` | `list[EventoDelphi]` nuevos (polling cada 2 s) |
| `POST` | `/runs/{id}/cancelar` | Cancela el análisis al terminar el paso en curso |
| `GET` | `/runs/{id}/informe?formato=json\|md` | `InformeDelphi` o Markdown |
| `GET` | `/runs/{id}/adr.zip` | Todos los ADR del run |

### 4.3 Interfaz del motor (`backend/delphi/engine.py`)

```python
class DelphiEngine:
    def run(self, run_id: str, config: ConfigRun,
            on_event: Callable[[EventoDelphi], None],
            should_cancel: Callable[[], bool]) -> InformeDelphi: ...
```

> Los LLM responden en **JSON validado con Pydantic** (`llm_io.py`). Si la validación falla, se reintenta una sola vez con el error incluido en el prompt.

---

## 5. Distribución de tareas (todos arrancan de inmediato, en paralelo)

### 👤 Juan — Plataforma: backend, API, ModelPool, estadística e input

- [ ] Estructura del repositorio, `requirements.txt`, `.env.example` y `.gitignore`. **El `.env` con keys reales nunca se sube.**
- [ ] `models.py`: transcribir los contratos de §4 el **día 1** y subirlos a `main`.
- [ ] `stats.py` (**día 1**, porque el motor lo usa): mediana, Q1/Q3, IQR, consenso por ítem y global, estabilidad entre rondas y la **regla de recomendación** de §1.2 (firme, condicionada o abierta, con el margen respecto de la segunda alternativa). Son funciones puras, sin LLM.
- [ ] `llm_io.py`: extraer el JSON de la respuesta (quitando los bloques `<think>` de los modelos de razonamiento), validarlo con Pydantic y reintentar una vez con el error en el prompt. Lo usan los expertos y el Moderador.
- [ ] `config.py` → `ModelPool` (§3):
  - Carga de los bloques del `.env`.
  - Modos `auto`, `seed`, `manual` y `mono`, con la **restricción de roles afines**.
  - Moderador neutral.
  - *Backoff* ante 429 y cambio de modelo registrado.
- [ ] `project_loader.py` + `data/plantilla_proyecto.md`: convierte la plantilla en `Proyecto`.
- [ ] `data/proyectos/`: 3 proyectos informáticos de ejemplo que obliguen a decidir:
  - **Viable:** sistema de reservas para una red de clínicas (equipo de 4 personas con experiencia, 6 meses).
  - **Polémico:** migración de un ERP monolítico *on-premise* a la nube (¿*lift & shift* o refactorizar a microservicios?).
  - **Débil:** marketplace con IA generativa en 3 meses, con 2 desarrolladores junior y presupuesto mínimo.
- [ ] `api/store.py` → `RunStore`: persistencia en `outputs/runs/<run_id>/`.
- [ ] `api/main.py`: todos los endpoints de §4.2. Ejecución en segundo plano, un análisis activo a la vez con cola, y cancelación por bandera.
- [ ] Hasta tener el motor real, un `DelphiEngine` *stub* que emita eventos falsos con tiempos realistas.
- [ ] Tests de `stats.py` (incluida la regla de recomendación), `llm_io.py`, `ModelPool` y la API.

### 👤 Pamela — Orquestación Delphi: Moderador, motor, informe y ADR

- [ ] `tools.py` → `DelphiStatsTool(BaseTool)`, que envuelve `stats.py` para CrewAI.
- [ ] **Prompts del Moderador:**
  - Identificar las **3 a 5 decisiones clave** del proyecto con sus alternativas realistas (y respetar las `decisiones_a_evaluar` si las hay).
  - Generar los ítems de evaluación por dimensión.
  - Redactar el feedback de cada ronda y decidir si continuar.
- [ ] `crew.py`:
  - **Moderador Delphi** como `manager_agent` (no `manager_llm`).
  - Los expertos del panel como *workers*, cada uno con `llm=ModelPool.get_llm(rol)`.
  - Las tareas de los expertos van **sin** `context`.
  - `max_iter` acotado.
- [ ] `engine.py` → `DelphiEngine.run(...)`:
  - Bucle de rondas: un `Crew` jerárquico por ronda y `crew.kickoff(inputs=...)`.
  - Emisión de **todos** los eventos de §4.1, usando `step_callback` y `task_callback`.
  - Límites impuestos por el código: `max_rondas`, consenso y estabilidad.
  - `guard_independencia`.
  - Respeto de `should_cancel`.
  - **Consolidación de riesgos:** agrupar los `riesgos_detectados` duplicados entre expertos y estimar su probabilidad e impacto.
- [ ] `report.py` → `informe.md`:
  - Resumen ejecutivo y tabla de decisiones (✅ firme / ⚠️ condicionada / ❓ abierta).
  - Evaluación por dimensión y matriz de riesgos.
  - Disensos y PoC sugeridas.
  - Evolución por ronda y sesgo por modelo.
- [ ] `adr.py`: un ADR por decisión, con el formato de §1.7 y la evidencia Delphi.
- [ ] `cli.py`: `python -m backend.cli data/proyectos/x.md` para depurar el motor sin API ni frontend.

### 👤 Jenaro — Panel de expertos TI y análisis de sesgo + Frontend

**Sistema (motor):**
- [ ] `experts.py`:
  - **Catálogo de los 10 expertos** de §1.1, con `role`, `goal` y `backstory` detallados, y prioridades y sesgos **explícitos y distintos**. Cada perfil incluye las preguntas que ese experto siempre se haría; por ejemplo, Seguridad: "¿dónde se guardan los datos personales y quién accede?".
  - `sugerir_panel(proyecto)`: el núcleo más los opcionales según el input. Por ejemplo, si se mencionan IA o LLM se agrega `ia`; si hay usuarios finales o apps se agrega `ux`; si hay migración o grandes volúmenes, `datos`; si el plazo es corto o el equipo junior, `gestion`. Devuelve también el motivo de cada sugerencia.
- [ ] `prompts.py`: prompts **de experto**:
  - Ronda 1: respuesta independiente, que incluye los `riesgos_detectados`.
  - Ronda k: respuesta propia anterior + feedback anónimo + obligación de justificar si queda fuera del IQR.
- [ ] `anonymizer.py` → `AnonymizerTool(BaseTool)`: agrupa y resume los argumentos a favor y en contra de cada ítem y alternativa, y quita el rol, el autor y las **marcas de estilo de cada modelo**.
- [ ] `bias.py`:
  - Puntaje medio de cada modelo y sus **preferencias por alternativa** (`SesgoModelo`).
  - Script del **experimento de control**: corre los 3 proyectos en modo `mono` y en modo `auto` y genera una tabla que muestra si cambian las decisiones recomendadas.
- [ ] Tests de `experts.py` (`sugerir_panel`), `anonymizer.py` y `bias.py`.

**Frontend (Streamlit):**
- [ ] `api_client.py` con un interruptor `USE_MOCKS=true`, y `mocks/` con un run completo falso (uno de los proyectos de ejemplo) para desarrollar **sin esperar al backend**.
- [ ] **Página 1 · Nuevo análisis:**
  - Formulario con la **plantilla de proyecto informático** (§1.6), o subir un `.md`, o elegir uno de `data/proyectos/`.
  - **Panel sugerido**, editable con casillas y con el motivo de cada experto.
  - Asignación de modelos (`auto`, `seed`, `manual` con un selector por experto, o `mono` para el control).
  - Reglas Delphi y botón **Iniciar**.
- [ ] **Página 2 · Ejecución en vivo:**
  - Estado, ronda actual y línea de tiempo de eventos.
  - Respuestas anónimas E1…E7 a medida que llegan; el interruptor **"modo auditor"** muestra el rol y el modelo de cada una.
  - Decisión del Moderador y botón **Cancelar**.
- [ ] **Página 3 · Decisiones y resultados:**
  - **Tablero de decisiones:** una tarjeta por decisión, con la alternativa recomendada, su estado (firme, condicionada o abierta), la mediana, el IQR, las condiciones o la PoC sugerida.
  - Gráfico de mediana e IQR por alternativa y ronda (Plotly), para ver la convergencia.
  - **Radar por dimensión** (arquitectura, infraestructura, stack…).
  - **Matriz de riesgos** (probabilidad × impacto).
  - Argumentos a favor y en contra, disensos, y **sesgo por modelo**.
  - Descargas: `informe.md`, `informe.json` y `adr.zip`.
- [ ] **Página 4 · Historial / Comparar:** lista de runs y comparación lado a lado de dos runs. Sirve, por ejemplo, para mono contra multi-modelo, o para el mismo proyecto con distintos paneles.

### 👥 Conjuntas

- [ ] **Día 1:**
  - Acordar las reglas Delphi (§1.5), el catálogo de expertos (§1.1) y la regla de recomendación (§1.2), y congelar los contratos (§4).
  - Cada uno elige un modelo de una **familia distinta**, crea su key, la agrega a su `.env` local y comparte con el equipo **solo** el proveedor y el nombre del modelo.
- [ ] **Integración:** quitar los *mocks* del frontend y el *stub* del motor, y probar de punta a punta con los 3 proyectos.
- [ ] **Validación con criterio humano:** revisar entre los tres si las decisiones recomendadas para los 3 proyectos de ejemplo son razonables. ¿Detecta que el proyecto débil no es viable?
- [ ] **Experimento de sesgo:** ejecutar el script de `bias.py` con los 3 proyectos y resumir el resultado en una tabla de este README.
- [ ] Demo y presentación.

---

## 6. Plan de trabajo en paralelo

| Hito | Juan | Pamela | Jenaro |
|------|------|--------|--------|
| **H0 · Día 1** | `models.py` + `stats.py` en `main` | Acordar contratos y regla de recomendación | Acordar contratos y catálogo de expertos |
| **H1 · Construcción** | `llm_io`, ModelPool, loader + plantilla, proyectos, RunStore, API con motor *stub* | Moderador, crew, motor, riesgos, `report.py`, `adr.py` (vía CLI) | Catálogo + `sugerir_panel`, prompts de experto, anonimizador, `bias` + las 4 páginas contra *mocks* |
| **H2 · Integración** | API ↔ motor real | Motor ↔ panel de expertos; ajuste de límites | Ajuste de prompts de experto con modelos reales; frontend ↔ API real |
| **H3 · Cierre** | Validación con criterio humano, experimento de sesgo, README final y demo (los tres) | | |

Nadie espera a nadie después del día 1: cada pieza tiene su sustituto (*mock*, *stub* o CLI) hasta la integración.

## 7. Flujo de trabajo Git

- Ramas: `feat/plataforma-api` (Juan), `feat/motor-delphi` (Pamela) y `feat/panel-y-frontend` (Jenaro).
- Todo entra a `main` por **Pull Request** con revisión cruzada: Juan revisa a Pamela, Pamela revisa a Jenaro y Jenaro revisa a Juan.
- Cambiar `models.py` requiere el visto bueno de los tres.
- Nunca se commitean `.env`, keys ni `outputs/`.

## 8. Ejecución (cuando esté implementado)

```bash
pip install -r requirements.txt
cp .env.example .env                       # cada uno completa su bloque LLM_*_<NOMBRE> (§3)

uvicorn backend.api.main:app --reload      # API en http://localhost:8000
streamlit run frontend/app.py              # Frontend en http://localhost:8501

python -m backend.cli data/proyectos/clinica_reservas.md   # (opcional) motor sin frontend
```

> **Cuota del LLM:** una ejecución hace aproximadamente `1 (cuestionario) + expertos × rondas + rondas (feedback) + 1 (informe)` llamadas, más las de delegación del Moderador. Son unas **25 a 30** con 6 expertos y 3 rondas. Como cada experto usa el modelo y la key de un integrante distinto, la carga se reparte entre las tres cuentas. Si se agota la cuota, reducir el panel a los 5 del núcleo o usar `max_rondas = 2`.
