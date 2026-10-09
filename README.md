# MultiAgente_Crew_AI — Panel Delphi con Agentes de IA

Sistema que recibe como **input la descripción de un proyecto** y aplica la **técnica Delphi** con un panel de expertos simulados por **LLM de familias distintas**. Un **agente Moderador** dirige las rondas anónimas hasta llegar a un consenso, o hasta dejar documentados los desacuerdos que persisten. Un **frontend web** permite lanzar y controlar los análisis y explorar los resultados.

Se construye **directamente la versión final**: no hay versiones intermedias. Esa versión toma como base `4-multiagent_crewai_hierarchical.py` de la unidad IL2.3.

| Pieza | Tecnología |
|-------|------------|
| Agente Moderador + panel multiagente | CrewAI `Process.hierarchical` con `manager_agent` propio |
| Diversidad de modelos | Un LLM de una familia distinta por integrante (Mistral, Groq, Google AI Studio) |
| Backend / API | FastAPI: ejecuta los análisis en segundo plano y los persiste |
| Frontend | Streamlit: configurar, lanzar, seguir en vivo, ver resultados y comparar |

**Equipo:** Pamela · Jenaro · Juan

---

## 1. Técnica Delphi: cómo la modelamos

La técnica Delphi es un método estructurado para obtener consenso entre expertos. Sus rasgos esenciales son:

1. **Anonimato:** los expertos no saben quién opinó qué.
2. **Iteración:** hay varias rondas de cuestionario.
3. **Retroalimentación controlada:** entre una ronda y otra, el moderador entrega un resumen estadístico y los argumentos anónimos del grupo.
4. **Respuesta estadística del grupo:** se informa la mediana y el rango intercuartílico (IQR), no un promedio de opiniones.

### Arquitectura

```
┌─────────────────────────── FRONTEND (Streamlit) ───────────────────────────┐
│ Nuevo análisis │ Ejecución en vivo │ Resultados │ Historial / Comparar     │
└───────────────────────────────┬────────────────────────────────────────────┘
                                │ HTTP (JSON) — polling de eventos
┌───────────────────────────────▼──────────────── BACKEND (FastAPI) ─────────┐
│  /runs  /runs/{id}  /runs/{id}/eventos  /runs/{id}/informe  /modelos       │
│  RunStore (persistencia)   ·   ejecución en segundo plano   ·   cancelación│
└───────────────────────────────┬────────────────────────────────────────────┘
                                │ DelphiEngine.run(config, on_event)
┌───────────────────────────────▼──────────────── MOTOR DELPHI (CrewAI) ─────┐
│                    ┌──────────────────────────┐                            │
│                    │   MODERADOR DELPHI       │  manager_agent             │
│                    │ cuestionario · delegación│  tools: DelphiStatsTool,   │
│                    │ feedback · ¿otra ronda?  │         AnonymizerTool     │
│                    └────────────┬─────────────┘                            │
│        ┌──────────────┬─────────┴────┬──────────────┐                      │
│        ▼              ▼              ▼              ▼                      │
│   E1 Técnico     E2 Financiero  E3 Riesgos/Legal E4 Negocio                │
│   (Mistral)      (Qwen·Groq)    (Gemini)        (modelo rotado)            │
│                                                                            │
│   ModelPool: un modelo por experto · stats.py: mediana / IQR / consenso    │
└────────────────────────────────────────────────────────────────────────────┘
```

### Flujo de una ejecución

1. **Ingesta:** el usuario pega o sube el proyecto en el frontend y elige los parámetros.
2. **Cuestionario:** el Moderador genera los criterios y las preguntas (escala Likert 1–5 más una justificación).
3. **Ronda k:** el Moderador delega en cada experto **por separado**. Cada experto responde en JSON usando *su* modelo.
4. **Agregación:** `DelphiStatsTool` calcula, sin LLM, la mediana, Q1, Q3 y el IQR de cada ítem. `AnonymizerTool` resume los argumentos a favor y en contra sin revelar autor ni modelo.
5. **Decisión:** el Moderador propone si hace falta otra ronda. **El código impone los límites** (consenso, estabilidad y número máximo de rondas). Si hay otra ronda, cada experto recibe el feedback anónimo junto con su respuesta anterior.
6. **Informe final:** consensos, disensos, evolución por ronda, sesgo por modelo y recomendaciones.

Cada paso emite un **evento**, que el frontend muestra en vivo.

### Reglas Delphi (acordadas por los tres, editables desde el frontend)

| Parámetro | Valor por defecto | Nota |
|-----------|-------------------|------|
| Nº de expertos | 4 (Técnico, Financiero, Riesgos/Legal, Negocio/Usuario) | |
| Escala | Likert 1–5 + justificación de 1 a 3 frases | |
| Rondas | mínimo 2, máximo 3 | Limitado por la cuota gratuita |
| Consenso por ítem | IQR ≤ 1 | |
| Consenso global | ≥ 80 % de los ítems con consenso | |
| Estabilidad | variación de la mediana < 0,5 entre rondas | Criterio alternativo de corte |
| Outliers | Si la respuesta de un experto queda fuera de [Q1, Q3], **debe** justificar si mantiene su postura o la cambia | |
| Diversidad | **Cada experto usa un modelo de una familia distinta** (§3), con `backstory` distinto y `temperature` alrededor de 0,7 | Evita el falso consenso |
| Independencia | El Moderador delega **solo** el proyecto, el cuestionario y el feedback anónimo de la ronda anterior. Nunca incluye respuestas de otros expertos de la ronda en curso | El código lo verifica (`guard_independencia`) |

---

## 2. Estructura del repositorio

```
MultiAgente_Crew_AI/
├── README.md
├── requirements.txt               # crewai, openai, fastapi, uvicorn, streamlit, plotly, pydantic, python-dotenv
├── .env.example                   # bloques LLM_*_<NOMBRE> (SIN keys reales)
├── .gitignore                     # .env, outputs/, __pycache__/
├── data/proyectos/                # proyectos de ejemplo               — Juan
├── backend/
│   ├── delphi/
│   │   ├── models.py              # contratos Pydantic (§4)            — los tres
│   │   ├── config.py              # ModelPool (§3)                     — Juan
│   │   ├── stats.py               # mediana, IQR, consenso, estabilidad — Juan
│   │   ├── experts.py             # perfiles de expertos               — Jenaro
│   │   ├── prompts.py             # prompts de experto: ronda 1 y ronda k — Jenaro
│   │   ├── anonymizer.py          # AnonymizerTool + síntesis de argumentos — Jenaro
│   │   ├── llm_io.py              # parseo/validación JSON + reintento — Jenaro
│   │   ├── bias.py                # sesgo por modelo + experimento de control — Jenaro
│   │   ├── tools.py               # DelphiStatsTool                    — Pamela
│   │   ├── crew.py                # Moderador (manager_agent) + panel  — Pamela
│   │   ├── engine.py              # DelphiEngine: rondas, eventos, límites — Pamela
│   │   └── report.py              # InformeDelphi → Markdown           — Pamela
│   ├── api/
│   │   ├── main.py                # FastAPI                            — Juan
│   │   └── store.py               # RunStore (SQLite o JSON por run)   — Juan
│   └── cli.py                     # correr el motor sin API (para depurar) — Pamela
├── frontend/
│   ├── app.py                     # Streamlit multipágina              — Jenaro
│   ├── pages/                     # 1_Nuevo, 2_En_vivo, 3_Resultados, 4_Historial
│   ├── api_client.py              # cliente HTTP de la API             — Jenaro
│   └── mocks/                     # eventos y runs falsos para desarrollar sin backend — Jenaro
├── outputs/runs/<run_id>/         # config.json, eventos.jsonl, rondas.json, informe.md
└── tests/
```

---

## 3. Panel multi-modelo: un LLM distinto por integrante

**Objetivo: reducir los sesgos compartidos.** Si los cuatro expertos son el mismo modelo con distinto `backstory`, comparten los mismos datos de entrenamiento, el mismo alineamiento y los mismos puntos ciegos. El resultado es un **falso consenso**: convergen porque piensan igual, no porque los argumentos convenzan. Por eso cada integrante aporta su API key con un **modelo de una familia distinta**, y el panel mezcla esos modelos. La cuota extra (cada key gasta su propio límite) es un beneficio secundario.

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
  - `auto`: evita repetir modelo dentro de una ronda; con 4 expertos y 3 modelos, el repetido atiende a los dos roles más alejados entre sí.
  - `seed`: rota la asignación entre ejecuciones, para separar el sesgo del rol del sesgo del modelo.
  - `manual`: se elige desde el frontend.
- **Modo control mono-modelo:** todo el panel usa un solo modelo. Sirve para el experimento de sesgo. Si hay menos de 2 familias disponibles, el sistema avisa: *"panel mono-modelo: riesgo de falso consenso"*.
- **Moderador neutral:** usa un modelo distinto del de la mayoría del panel.
- **Errores 429 o caídas:** reintento con espera progresiva (*backoff*) en el mismo modelo. Solo si el error persiste se cambia de modelo, y el cambio se registra y se emite como evento.

**Medición del sesgo (aparece en el frontend y en el informe):**

- **Sesgo por modelo:** el puntaje medio que da cada modelo en todas las preguntas.
- **Experimento de control:** el mismo proyecto con un panel mono-modelo y con uno multi-modelo. Se compara el IQR de la ronda 1, las rondas hasta el consenso y si las conclusiones cambian.

> ⚠️ Cada key es personal: se guarda solo en el `.env` local de cada uno y nunca va en el repositorio ni en el chat del grupo.

---

## 4. Contratos compartidos (se congelan el día 1)

Estos contratos son los que permiten trabajar **los tres en paralelo desde el primer día**: el frontend se desarrolla contra *mocks*, el motor contra la CLI y la API contra un motor *stub*. Ningún contrato se cambia sin avisar al resto.

### 4.1 Modelos de datos (`backend/delphi/models.py`)

```python
class Proyecto(BaseModel):
    nombre: str
    descripcion: str

class ConfigRun(BaseModel):                 # lo que envía el frontend
    proyecto: Proyecto
    expertos: list[str] = ["tecnico", "financiero", "riesgos_legal", "negocio"]
    asignacion_modelos: Literal["auto", "seed", "manual", "mono"] = "auto"
    modelos_manual: dict[str, str] | None = None   # rol -> nombre de modelo
    seed: int | None = None
    min_rondas: int = 2
    max_rondas: int = 3
    umbral_iqr: float = 1.0
    umbral_consenso_global: float = 0.8

class Item(BaseModel):
    id: str                     # "T1", "F2", ...
    criterio: str
    pregunta: str

class Cuestionario(BaseModel):
    items: list[Item]

class RespuestaItem(BaseModel):
    item_id: str
    puntaje: int = Field(ge=1, le=5)
    justificacion: str

class RespuestaExperto(BaseModel):
    experto_id: str             # "E1".."E4": anónimo
    ronda: int
    modelo: str                 # solo para auditoría y medición de sesgo; NUNCA se muestra a otros expertos
    respuestas: list[RespuestaItem]

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
    motivo: str                 # "consenso", "estabilidad", "max_rondas", "moderador"

class SesgoModelo(BaseModel):
    modelo: str
    puntaje_medio: float
    desviacion_vs_mediana_grupo: float

class InformeDelphi(BaseModel):
    proyecto: Proyecto
    cuestionario: Cuestionario
    rondas: list[ResumenRonda]
    respuestas: list[RespuestaExperto]
    consensos: list[str]
    disensos: list[str]
    recomendaciones: list[str]
    sesgo_por_modelo: list[SesgoModelo]
    avisos: list[str]           # p. ej. "panel mono-modelo"

class EventoDelphi(BaseModel):              # lo que consume el frontend en vivo
    run_id: str
    seq: int                    # incremental, para pedir solo los eventos nuevos
    timestamp: datetime
    tipo: Literal["run_iniciado", "cuestionario_generado", "ronda_iniciada",
                  "respuesta_experto", "ronda_agregada", "decision_moderador",
                  "cambio_modelo", "run_finalizado", "run_cancelado", "error"]
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
| `GET` | `/expertos` | Perfiles de experto disponibles |
| `POST` | `/runs` (body `ConfigRun`) | `{run_id}`; lanza el análisis en segundo plano |
| `GET` | `/runs` | Lista de `EstadoRun` (historial) |
| `GET` | `/runs/{id}` | `EstadoRun` |
| `GET` | `/runs/{id}/eventos?desde=<seq>` | `list[EventoDelphi]` nuevos (polling cada 2 s) |
| `POST` | `/runs/{id}/cancelar` | Cancela el análisis al terminar el paso en curso |
| `GET` | `/runs/{id}/informe?formato=json\|md` | `InformeDelphi` o Markdown |

### 4.3 Interfaz del motor (`backend/delphi/engine.py`)

```python
class DelphiEngine:
    def run(self, run_id: str, config: ConfigRun,
            on_event: Callable[[EventoDelphi], None],
            should_cancel: Callable[[], bool]) -> InformeDelphi: ...
```

> Los LLM responden en **JSON validado con Pydantic**. Si la validación falla, se reintenta una sola vez con el error incluido en el prompt.

---

## 5. Distribución de tareas (todos arrancan de inmediato, en paralelo)

### 👤 Juan — Plataforma: backend, API, ModelPool y estadística

- [ ] Estructura del repositorio, `requirements.txt`, `.env.example` y `.gitignore`. **El `.env` con keys reales nunca se sube.**
- [ ] `models.py`: transcribir los contratos de §4 el **día 1** y subirlos a `main`.
- [ ] `config.py` → `ModelPool` (§3): carga de bloques del `.env`; modos de asignación `auto`, `seed`, `manual` y `mono`; moderador neutral; *backoff* ante 429 y cambio de modelo registrado; `listar_modelos()` sin keys.
- [ ] `stats.py`: mediana, Q1/Q3, IQR, consenso por ítem y global, y estabilidad entre rondas. Son funciones puras, sin LLM, y van el **día 1**, porque el motor las usa.
- [ ] `api/store.py` → `RunStore`: persistencia en `outputs/runs/<run_id>/` (`config.json`, `eventos.jsonl` y `rondas.json`) o en SQLite.
- [ ] `api/main.py`: todos los endpoints de §4.2. Ejecución en segundo plano (hilo o `BackgroundTasks`), un análisis activo a la vez con cola, y cancelación por bandera (`should_cancel`).
- [ ] Hasta tener el motor real, un `DelphiEngine` *stub* que emita eventos falsos con tiempos realistas.
- [ ] `data/proyectos/`: al menos 3 proyectos de ejemplo (uno claramente viable, uno polémico y uno débil).
- [ ] Tests de `stats.py`, `ModelPool` y la API.

### 👤 Pamela — Orquestación Delphi: Moderador, motor e informe

- [ ] `tools.py` → `DelphiStatsTool(BaseTool)`, que envuelve `stats.py` para CrewAI.
- [ ] `crew.py`:
  - **Moderador Delphi** como `manager_agent` (no `manager_llm`): genera el cuestionario, delega, usa las tools y propone si hace falta otra ronda.
  - Los expertos de `experts.py` van como *workers*, cada uno con `llm=ModelPool.get_llm(rol)`.
  - Las tareas de los expertos van **sin** `context`.
  - `max_iter` acotado.
- [ ] Prompts **del Moderador**: generación del cuestionario, criterios de delegación y decisión de continuar.
- [ ] `engine.py` → `DelphiEngine.run(...)`:
  - Bucle de rondas: un `Crew` jerárquico por ronda y `crew.kickoff(inputs=...)`.
  - Emisión de **todos** los eventos de §4.1, usando `step_callback` y `task_callback` de CrewAI.
  - Límites impuestos por el código: `max_rondas`, consenso y estabilidad.
  - `guard_independencia`: revisa que la delegación del Moderador no incluya respuestas de otros expertos de la ronda en curso.
  - Respeto de `should_cancel`.
- [ ] `report.py`: `InformeDelphi` → Markdown, con una tabla de evolución por ronda, consensos, disensos, recomendaciones, sesgo por modelo y avisos.
- [ ] `cli.py`: `python -m backend.cli data/proyectos/x.md` para depurar el motor sin API ni frontend.

### 👤 Jenaro — Panel de expertos y análisis de sesgo + Frontend

**Sistema (motor):**
- [ ] `experts.py`: 4 perfiles (`role`, `goal`, `backstory`) con prioridades y sesgos **distintos y explícitos**, y los datos que devuelve `/expertos`.
- [ ] `prompts.py`: prompts **de experto**:
  - Ronda 1: respuesta independiente.
  - Ronda k: respuesta propia anterior + feedback anónimo + obligación de justificar si queda fuera del IQR.
- [ ] `anonymizer.py` → `AnonymizerTool(BaseTool)`: agrupa y resume los argumentos a favor y en contra de cada ítem, y quita el rol, el autor y las **marcas de estilo de cada modelo**.
- [ ] `llm_io.py`: extraer el JSON de la respuesta (quitando los bloques `<think>` de los modelos de razonamiento), validarlo con Pydantic y reintentar una vez con el error en el prompt. Lo usan los expertos y el Moderador.
- [ ] `bias.py`:
  - Puntaje medio de cada modelo y su desviación respecto de la mediana del grupo (`SesgoModelo`).
  - Script del **experimento de control**: corre los 3 proyectos en modo `mono` y en modo `auto` y genera la tabla comparativa.
- [ ] Tests de `anonymizer.py`, `llm_io.py` y `bias.py`.

**Frontend (Streamlit):**
- [ ] `api_client.py` con un interruptor `USE_MOCKS=true`, y `mocks/` con un run completo falso para desarrollar **sin esperar al backend**.
- [ ] **Página 1 · Nuevo análisis:**
  - Pegar o subir el proyecto, o elegir uno de `data/proyectos/`.
  - Elegir los expertos y la asignación de modelos (`auto`, `seed`, `manual` con un selector por experto, o `mono` para el control).
  - Ajustar las reglas Delphi y pulsar el botón **Iniciar**.
- [ ] **Página 2 · Ejecución en vivo:**
  - Estado, ronda actual y línea de tiempo de eventos (polling a `/eventos?desde=`).
  - Respuestas anónimas E1…E4 a medida que llegan; el interruptor **"modo auditor"** muestra el modelo de cada una.
  - Decisión del Moderador y botón **Cancelar**.
- [ ] **Página 3 · Resultados:**
  - Gráfico de mediana con barras de IQR por ítem y ronda (Plotly) y el % de consenso por ronda.
  - Consensos y disensos con sus argumentos.
  - **Sesgo por modelo** y avisos.
  - Descarga del informe en `.md` y `.json`.
- [ ] **Página 4 · Historial / Comparar:** lista de runs y comparación lado a lado de dos runs (mono contra multi-modelo).

### 👥 Conjuntas

- [ ] **Día 1:** acordar las reglas Delphi (§1) y congelar los contratos (§4). Cada uno elige un modelo de una **familia distinta**, crea su key, la agrega a su `.env` local y comparte con el equipo **solo** el proveedor y el nombre del modelo.
- [ ] **Integración:** quitar los *mocks* del frontend y el *stub* del motor, y probar de punta a punta con los 3 proyectos.
- [ ] **Experimento de sesgo:** ejecutar el script de `bias.py` (Jenaro) con los 3 proyectos, analizar los resultados entre los tres y resumirlos en una tabla de este README.
- [ ] Demo y presentación.

---

## 6. Plan de trabajo en paralelo

| Hito | Juan | Pamela | Jenaro |
|------|------|--------|--------|
| **H0 · Día 1** | `models.py` + `stats.py` en `main` | Acordar contratos | Acordar contratos |
| **H1 · Construcción** | ModelPool, RunStore, API con motor *stub*, proyectos de ejemplo | Moderador, crew, motor, eventos, `report.py` (vía CLI) | Expertos, prompts, anonimizador, `llm_io`, `bias` + las 4 páginas contra *mocks* |
| **H2 · Integración** | API ↔ motor real | Motor ↔ panel de expertos; ajuste de límites | Ajuste de prompts de experto con modelos reales; frontend ↔ API real |
| **H3 · Cierre** | Experimento de sesgo, README final y demo (los tres) | | |

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

python -m backend.cli data/proyectos/ejemplo.md   # (opcional) motor sin frontend
```

> **Cuota del LLM:** una ejecución hace aproximadamente `1 + expertos × rondas + rondas + 1` llamadas, más las de delegación del Moderador. Son unas 15 a 20 con 4 expertos y 3 rondas. Como cada experto usa el modelo y la key de un integrante distinto, la carga se reparte entre las tres cuentas.
