# MultiAgente_Crew_AI — Panel Delphi para Decisiones en Proyectos Informáticos

Sistema que recibe como **input la descripción de un proyecto informático** y aplica la **técnica Delphi** con un panel de **expertos de TI** simulados por LLM de familias distintas: Arquitectura, Cloud, Desarrollo, Seguridad, DevOps, Datos, QA, UX, Gestión e IA. Un **agente Moderador** dirige rondas anónimas para que el panel contraste opiniones sobre las **decisiones clave del proyecto**: estilo de arquitectura, proveedor cloud, stack, base de datos, estrategia de despliegue, seguridad, plazos, etc.

**Objetivo: tomar mejores decisiones antes de construir.** El sistema no entrega una opinión aislada. Entrega:

- **Decisiones recomendadas** con su nivel de consenso: *firme*, *condicionada* o *abierta*.
- **ADR** (*Architecture Decision Records*) listos para incorporar al repositorio del proyecto.
- **Riesgos técnicos** priorizados y los **desacuerdos** que conviene resolver con una prueba de concepto (*PoC*) o un *spike*.

| Pieza | Tecnología |
|-------|------------|
| Agente Moderador + panel multiagente | CrewAI `Process.hierarchical` con `manager_agent` propio, un Crew por experto y ronda (base: `4-multiagent_crewai_hierarchical.py`, IL2.3) |
| Diversidad de modelos | Un LLM de una familia distinta por bloque del `.env` (hoy: Gemini, Gemma y GPT-OSS, vía Google AI Studio y Groq) |
| Backend / API | FastAPI: ejecuta los análisis en segundo plano y los persiste |
| Frontend | Streamlit: configurar, lanzar, seguir en vivo, ver decisiones y ADR, y comparar |

Se construye **directamente la versión final**, sin versiones intermedias.

**Equipo:** Pamela · Jenaro · Juan

---

## 0. Cómo funciona, explicado sin tecnicismos

Esta sección es para quien no sabe nada de inteligencia artificial. Las secciones siguientes son la documentación técnica.

![Visión general: la persona usa las pantallas, la API recibe el pedido, el motor organiza las rondas, el equipo de IA opina y los proveedores aportan los modelos](docs/img/arquitectura-1-vision-general.jpg)

### El problema

Antes de construir un sistema informático hay que tomar decisiones difíciles de revertir: cómo organizar el programa, dónde alojarlo, con qué tecnologías hacerlo. Si las toma una sola persona, su opinión pesa demasiado y sus puntos ciegos pasan a ser los del proyecto. Lo ideal es consultar a varios especialistas, pero eso es caro y lento, y en una reunión el que habla más fuerte suele arrastrar al resto.

### La idea: un comité que opina por separado

El sistema aplica el **método Delphi**, una técnica que se usa desde los años 50 para lograr acuerdos entre expertos:

1. Cada experto responde un cuestionario **por separado**, sin saber qué opinan los demás.
2. Un moderador junta las respuestas y le devuelve a cada uno un **resumen anónimo** ("el grupo opina mayoritariamente esto, y estos son los argumentos").
3. Cada experto puede **mantener o cambiar** su respuesta. Si se aleja mucho del grupo, debe explicar por qué.
4. Se repite hasta que hay acuerdo o hasta un máximo de rondas.

Como nadie sabe quién dijo qué, nadie se deja llevar por el cargo o la personalidad de otro. Solo pesan los argumentos.

### ¿Quiénes son los "expertos"?

No son personas. Son programas de **inteligencia artificial** del mismo tipo que ChatGPT, llamados **modelos de lenguaje** (en inglés, *LLM*). Un modelo de lenguaje aprendió a partir de enormes cantidades de texto: lee una pregunta y escribe una respuesta razonada.

A cada uno se le da un **rol** con instrucciones que describen su especialidad y sus prioridades. Por ejemplo, al experto en seguridad se le pide que priorice proteger los datos aunque cueste más tiempo, y al experto en desarrollo, que priorice entregar rápido. Los roles tienen prioridades distintas a propósito, como pasaría con especialistas reales, para que haya algo que discutir. Hay 10 roles posibles (arquitectura, nube, desarrollo, seguridad, operación, datos, calidad, experiencia de usuario, gestión e IA), y en cada análisis participan de 5 a 7.

### ¿Por qué cada experto usa una IA distinta?

Si los cinco expertos fueran la misma IA con distinto rol, compartirían las mismas costumbres y puntos ciegos, y su "acuerdo" sería engañoso: sería una sola opinión repetida cinco veces. Es como pedirle una segunda opinión a la misma persona. Por eso el sistema mezcla IA de **empresas distintas** (hoy: Gemini y Gemma de Google, y GPT-OSS de OpenAI), y nunca les asigna la misma IA a dos roles que suelen pensar parecido.

### El Moderador

Es otra IA que organiza el proceso: lee el proyecto, decide cuáles son las preguntas importantes y le entrega el cuestionario a cada experto. Lo que **no** puede hacer es tan importante como lo que hace:

- **No puede cambiar lo que recibe cada experto:** el programa arma el cuestionario de cada uno y se lo entrega "sellado".
- **No puede alterar las respuestas:** el programa las toma directamente del experto.
- **No hace los cálculos ni decide el resultado:** eso lo hace el programa con reglas fijas, siempre igual.

### Un análisis paso a paso (ejemplo real)

![Un análisis paso a paso: qué hace la persona, las pantallas, el motor, el Moderador y los expertos en cada uno de los 10 pasos](docs/img/arquitectura-2-paso-a-paso.jpg)

Este es un análisis real hecho con el proyecto de ejemplo de una red de clínicas que quiere un sistema de reservas de horas.

1. **La persona describe su proyecto** en un formulario: objetivo, cantidad de usuarios, plazo (6 meses), presupuesto, equipo (4 personas), normativa (Ley 21.719 de datos de salud) y las dudas que ya tiene.
2. **El sistema sugiere el panel de expertos** según el proyecto, y la persona puede ajustarlo.
3. **El Moderador escribe el cuestionario.** Para las clínicas preguntó, entre otras cosas, por el estilo de arquitectura (*monolito modular* o *microservicios*), el alojamiento (*plataforma gestionada* o *Kubernetes*) y la app móvil (*React Native* o *PWA*), además de preguntas como "¿El diseño de datos cumple la Ley 21.719?".
4. **Ronda 1: cada experto responde por separado** con una nota de 1 a 5 y una justificación. Por ejemplo: *"La entrega en 6 meses es viable si se opta por una arquitectura monolítica modular… el equipo de cuatro personas tiene el perfil adecuado"*.
5. **El programa resume las respuestas** con dos números:
   - La **mediana**, que es el valor del medio. Si las notas son 2, 3, 3, 4 y 5, la mediana es 3.
   - La **dispersión** (*IQR*), que mide qué tan de acuerdo están. Si es 1 o menos, se considera que hay **consenso**.
6. **Ronda 2: cada experto ve el resumen anónimo** y puede reconsiderar. En la pregunta sobre la Ley 21.719 pasó esto:

   | | Arquitectura | Nube | Desarrollo | Seguridad | Operación | Mediana |
   |---|:-:|:-:|:-:|:-:|:-:|:-:|
   | Ronda 1 | 3 | 3 | 4 | **2** | **5** | 3 |
   | Ronda 2 | 3 | 3 | 4 | **3** | **4** | 3 |

   Los dos expertos más alejados se acercaron al grupo. Así es como Delphi construye acuerdo.
7. **El programa clasifica cada decisión** con una regla fija:
   - ✅ **Firme:** hay acuerdo, la opción ganadora tiene nota 4 o más y le saca al menos un punto a la segunda. *Se recomienda adoptarla.*
   - ⚠️ **Condicionada:** hay acuerdo, pero la ventaja es pequeña o la nota es solo intermedia. *Se adopta con condiciones o se revisa más adelante.*
   - ❓ **Abierta:** no hubo acuerdo. *Conviene una prueba pequeña (prueba de concepto) antes de decidir.*

   Para las clínicas, las tres decisiones salieron **firmes**: monolito modular (nota 5 contra 2 de microservicios), plataforma gestionada (5 contra 2) y PWA para la app móvil (4 contra 3). Es razonable para un equipo pequeño con poco plazo y poco presupuesto.
8. **El sistema da un veredicto de viabilidad.** A todos los expertos se les hace siempre una pregunta más: *¿qué tan viable es el proyecto tal como está planteado?* Con la nota final, el programa dice si es ✅ **viable** (4 o más), ⚠️ **viable con condiciones** (3), ⛔ **no viable** (menos de 3) o ❓ **en discusión** (si no hubo acuerdo), y explica por qué con los argumentos y los riesgos más graves.
9. **El sistema entrega un informe** con las decisiones, los riesgos que detectaron los expertos (por ejemplo, incumplir la ley de datos de salud), los desacuerdos y un **ADR** por decisión: un documento breve que deja registrado qué se decidió, qué otras opciones había y por qué.

### ¿Qué hace la IA y qué hace el programa?

| Tarea | Lo hace | Por qué |
|---|---|---|
| Escribir el cuestionario | IA (Moderador) | Requiere entender el proyecto |
| Opinar y justificar | IA (cada experto) | Es el juicio experto |
| Agrupar riesgos parecidos | IA (Moderador) | Requiere entender el texto |
| Armar lo que recibe cada experto | Programa | Garantiza que nadie vea opiniones ajenas |
| Calcular medianas y consenso | Programa | Los números deben ser exactos y repetibles |
| Decidir si hay otra ronda | Programa (la IA solo opina en casos dudosos) | Las reglas no deben depender de la IA |
| Clasificar firme, condicionada o abierta | Programa | Una regla fija, igual para todos los proyectos |
| Dar el veredicto de viabilidad | Programa (con la nota que dieron los expertos) | Una regla fija: la IA opina, el programa concluye |

### Qué se ve en pantalla

- **Nuevo análisis:** se describe el proyecto (o se elige un ejemplo), se ajusta el panel y se inicia.
- **En vivo:** el análisis aparece por etapas (preparación y cada ronda). Solo queda abierta la etapa en curso; las terminadas se pliegan con un resumen (por ejemplo, "Ronda 1 · ✔ terminada · consenso 60 %"). Las respuestas llegan identificadas solo como E1, E2…; el "modo auditor" muestra qué rol e IA hay detrás de cada uno.
- **Decisiones:** arriba, el **veredicto de viabilidad** en una caja de color; luego las tarjetas de cada decisión, los **riesgos ordenados por gravedad** (🔴 alta, 🟠 media, 🟡 baja, con su mitigación), los gráficos de convergencia y las descargas del informe.
- **Historial:** análisis anteriores, y la comparación de dos de ellos (por ejemplo, el mismo proyecto con un panel de una sola IA contra uno de varias).

### Cuánto tarda y por qué

Un análisis completo tarda **unos 5 a 10 minutos**: los expertos responden al mismo tiempo, así que cada ronda dura lo que tarda el más lento (Gemma, 1 a 2 minutos). Las IA usadas son las de los **planes gratuitos** de cada empresa, que limitan cuántas preguntas por minuto y por día se pueden hacer. Cuando una IA llega a su límite, el sistema espera y reintenta, o le pasa ese experto a otra IA, y lo deja registrado. Para una demostración se puede usar el **modo simulado**, que recorre todo el proceso en segundos con respuestas ficticias.

### Lo que el sistema no hace

- **No reemplaza el juicio humano.** Es un apoyo para decidir mejor y dejar registrado el porqué, no una orden.
- **La IA puede equivocarse** o basarse en supuestos. Las justificaciones están a la vista para revisarlas.
- **Un acuerdo no garantiza que la decisión sea correcta.** Mezclar IA distintas reduce el riesgo de un falso acuerdo, pero no lo elimina. Por eso el sistema también mide el sesgo de cada IA (cuánto se aleja del grupo).

### Glosario

| Término | Significado |
|---|---|
| **IA / modelo de lenguaje (LLM)** | Programa que aprendió de grandes cantidades de texto y responde preguntas escribiendo. |
| **Agente** | Una IA con un rol y una tarea, por ejemplo "experto en seguridad que responde este cuestionario". |
| **Familia de modelos** | IA de un mismo origen (por ejemplo, Gemini de Google). Distintas familias "piensan" distinto. |
| **Prompt** | Las instrucciones y la información que se le entregan a la IA. |
| **API / API key** | La forma en que un programa se conecta con el servicio de IA de una empresa, y la clave personal para usarlo. |
| **Mediana** | El valor del medio cuando las notas se ordenan de menor a mayor. |
| **IQR (rango intercuartílico)** | Cuánto se separan las notas del medio. Si es 1 o menos, hay consenso. |
| **ADR** | *Architecture Decision Record:* documento breve que registra una decisión técnica y sus razones. |
| **PoC / spike** | Prueba pequeña y rápida para resolver una duda antes de comprometerse. |
| **CrewAI** | La herramienta con la que se programa el equipo de agentes (Moderador y expertos). |
| **Frontend / backend** | La parte que se ve (las pantallas) y la parte que trabaja detrás (el motor y la API). |

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

Diagrama completo en [`docs/arquitectura.drawio`](docs/arquitectura.drawio), en 5 hojas con notas explicativas: **1** visión general, **2** un análisis paso a paso (quién hace cada cosa), **3** una ronda por dentro (CrewAI y por qué los expertos no se influyen), **4** componentes y responsables, **5** modelos de IA y respaldos ante los límites de los planes gratuitos. Se abre en https://app.diagrams.net o en la extensión Draw.io de VS Code. Las imágenes de [`docs/img/`](docs/img/) son la exportación de esas hojas: si se edita el diagrama, hay que volver a exportarlas.

![Componentes del sistema por capa y responsable](docs/img/arquitectura-4-componentes.jpg)

<details>
<summary>Versión en texto del diagrama</summary>

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
│                   │      MODERADOR DELPHI       │  manager_agent (sin      │
│                   │ cuestionario · delegación   │  tools: CrewAI no lo     │
│                   │ ¿otra ronda? · riesgos      │  permite); rota 4 keys   │
│                   └──────────────┬──────────────┘                          │
│     ┌──────────┬──────────┬──────┴─────┬───────────┬──────────┐            │
│     ▼          ▼          ▼            ▼           ▼          ▼            │
│ Arquitectura  Cloud   Desarrollo   Seguridad    DevOps    (opcionales:     │
│  (Gemini)   (Gemma)  (GPT-OSS)    (Gemini)    (GPT-OSS)    Datos, QA, UX,  │
│                                                            Gestión, IA)    │
│   Cada experto recibe su enunciado SELLADO y su respuesta se toma directo  │
│   Entre rondas, el código calcula la estadística y anonimiza argumentos    │
│   ModelPool: modelos distintos en roles afines · stats.py: mediana/IQR     │
└────────────────────────────────────────────────────────────────────────────┘
```

</details>

### 1.4 Flujo de una ejecución

1. **Ingesta:** el usuario completa la plantilla del proyecto (§1.6) en el frontend o sube un `.md`.
2. **Panel:** el sistema sugiere los expertos (núcleo más opcionales relevantes) y el usuario confirma o ajusta.
3. **Cuestionario:** el Moderador identifica las **decisiones clave** y genera los ítems de evaluación y de decisión por dimensión.
4. **Ronda k:** el Moderador delega en cada experto **por separado**, en un Crew jerárquico propio por experto. Cada experto responde en JSON usando *su* modelo.
   - **Enunciado sellado:** el prompt del experto lo arma el código y el Moderador solo decide la delegación. Así no puede resumirlo ni agregarle opiniones ajenas, y tampoco copia miles de tokens en cada delegación.
   - **Salida directa:** la respuesta se toma del experto, no de la respuesta final del Moderador, que podría reescribir puntajes.
5. **Agregación:** el motor calcula, sin LLM, la mediana, Q1, Q3 y el IQR de cada ítem y cada alternativa (`stats.py`, la misma lógica que expone `DelphiStatsTool`). El anonimizador resume los argumentos sin revelar autor ni modelo. Lo hace el código y no el Moderador porque CrewAI no permite que el `manager_agent` tenga herramientas, y así los números son reproducibles.
6. **Decisión de continuar:** el Moderador propone si hace falta otra ronda, y **el código impone los límites**. Si hay otra ronda, cada experto recibe el feedback anónimo (estadísticas y argumentos saneados, nunca texto libre de un LLM) junto con su respuesta anterior.
7. **Informe:** veredicto de viabilidad (calculado por el código a partir de la pregunta fija `VIA-E1`), decisiones recomendadas (firme, condicionada o abierta), ADR, riesgos técnicos, evaluación por dimensión, disensos con la PoC sugerida y sesgo por modelo.

Cada paso emite un **evento**, que el frontend muestra en vivo.

Así funciona una ronda por dentro: un equipo CrewAI por experto, con el enunciado sellado y la respuesta tomada directo del experto.

![Una ronda por dentro: el Moderador delega, cada experto responde su enunciado sellado y el código valida, agrega y decide si hay otra ronda](docs/img/arquitectura-3-ronda-por-dentro.jpg)

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
| Independencia | El experto recibe **solo** el proyecto, el cuestionario, su respuesta anterior y el feedback anónimo | El código lo verifica (`guard_independencia`) y sella el enunciado (`ExpertoDelphi` en `crew.py`) |
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

- `informe.md` e `informe.json`: resumen ejecutivo, decisiones recomendadas, evaluación por dimensión, riesgos, disensos y PoC sugeridas, evolución por ronda y sesgo por modelo.
- `adr/ADR-001-<decision>.md`, …: **un ADR por decisión**, con el formato *Contexto · Decisión · Alternativas consideradas · Consecuencias · Estado (Aceptada / Condicionada / Abierta) · Evidencia Delphi* (mediana, IQR y argumentos).
- `rondas.json` y `eventos.jsonl`: trazabilidad completa para auditar.
- `estado.json`: estado del run para la API y el historial.

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
│   │   ├── asignacion.py          # reparto de modelos sin roles afines juntos
│   │   ├── simulado.py            # LLM falsos: CLI --mock, API simulada y tests
│   │   ├── tools.py               # DelphiStatsTool                    — Pamela
│   │   ├── moderador_prompts.py   # prompts del Moderador              — Pamela
│   │   ├── crew.py                # Moderador (manager_agent) + panel  — Pamela
│   │   ├── engine.py              # DelphiEngine: rondas, eventos, límites — Pamela
│   │   ├── decisiones.py          # decisiones, disensos y riesgos     — Pamela
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
| **Groq** | `https://api.groq.com/openai/v1` | https://console.groq.com/keys | GPT-OSS (OpenAI), Qwen (Alibaba) | Inferencia muy rápida. Son **modelos de razonamiento**: si no se indica `LLM_MAX_TOKENS_<N>`, Groq corta la salida en 2048 tokens y el JSON queda incompleto. Usar unos 2200 y `LLM_REASONING_<N>=low`: Groq suma entrada + `max_tokens` contra su límite por minuto, así que un valor muy alto hace que la petición sea rechazada. Qwen tiene un límite de 1000 tokens de salida por minuto: no alcanza para responder un cuestionario completo. |
| **Google AI Studio** | `https://generativelanguage.googleapis.com/v1beta/openai/` | https://aistudio.google.com/apikey | Gemini, Gemma (pesos abiertos) | Es la misma cuenta de Google que se usa en Colab, y la misma key sirve para ambas familias. Sirve para expertos; Gemini como Moderador falla al delegar (`thought_signature`). Gemma es lenta (~2 min por respuesta). |
| **OpenRouter** | `https://openrouter.ai/api/v1` | https://openrouter.ai/keys | Nemotron (NVIDIA) y otras (modelos `:free`) | Límites bajos (unas 20 peticiones por minuto y 50 por día). Son modelos de razonamiento: usar `LLM_REASONING_<N>=low`. El catálogo `:free` cambia: MiniMax M3.1 Flash dejó de ser gratuito el 22-10-2026. Nemotron se probó como LLM puntual y se descartó por lento (1 a 6 min por llamada). |

> Lo que importa para la diversidad es la **familia del modelo**, no el proveedor: dos integrantes pueden usar Groq si cada uno elige una familia distinta.

**Asignación original del día 1** (histórica: Mistral dejó de ser gratuito y Qwen no alcanza para un cuestionario completo; ver *Modelos en uso* más abajo).

| Integrante | Proveedor | Familia | `LLM_MODEL` (ejemplo) |
|------------|-----------|---------|-----------------------|
| Juan | Mistral AI | Mistral (Mistral AI) | `mistral-small-latest` |
| Pamela | Groq | Qwen (Alibaba) | `qwen/qwen3.8-27b` |
| Jenaro | Google AI Studio | Gemini (Google) | el modelo *flash* gratuito vigente |

**`.env`** (copiar `.env.example`; el `.env` nunca se sube al repositorio). Un bloque por **modelo** de experto, más los bloques del Moderador:

```env
LLM_BASE_URL_GROQ=https://api.groq.com/openai/v1      # URL por defecto de los bloques sin LLM_BASE_URL propia

# Moderador: el mismo modelo con varias keys de cuentas distintas; se rotan entre delegaciones.
LLM_MODEL_MODERADOR=openai/gpt-oss-120b
LLM_API_KEY_MODERADOR_1=...
LLM_API_KEY_MODERADOR_2=...

# Expertos: una familia distinta por bloque.
LLM_API_KEY_GPT_OSS_20B=...
LLM_MODEL_GPT_OSS_20B=openai/gpt-oss-20b
LLM_REASONING_GPT_OSS_20B=low                         # modelos de razonamiento: limitar lo que piensan
LLM_MAX_TOKENS_GPT_OSS_20B=2200                       # Groq corta en 2048 si no se indica; más alto no cabe en su límite por minuto

LLM_API_KEY_GEMMA=...                                 # la misma key de Google AI Studio
LLM_BASE_URL_GEMMA=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL_GEMMA=gemma-4-31b-it

LLM_API_KEY_GEMINI=...
LLM_BASE_URL_GEMINI=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL_GEMINI=gemini-flash-latest

# Opcional: un LLM puntual (ver más abajo). Hoy no se usa.
# LLM_API_KEY_NEMOTRON=...
# LLM_BASE_URL_NEMOTRON=https://openrouter.ai/api/v1
# LLM_MODEL_NEMOTRON=nvidia/nemotron-3-ultra-550b-a55b:free
# LLM_USO_NEMOTRON=puntual
# LLM_TIMEOUT_NEMOTRON=240
```

**LLM puntual.** Un bloque con `LLM_USO_<N>=puntual` no se asigna a ningún experto. Se usa solo en las dos llamadas únicas y de más valor: generar el cuestionario (identificar las decisiones clave) y consolidar los riesgos. Sirve para un modelo bueno pero lento o con pocas peticiones diarias. Se intenta una vez y, si falla, la llamada la hace el Moderador y el informe lo avisa. Sin bloque puntual, ambas llamadas las hace el Moderador. Nemotron se probó en este rol y se descartó: tardaba de 1 a 6 minutos, mientras que gpt-oss-120b genera un cuestionario de calidad comparable en unos 6 segundos.

Un bloque con la key vacía se omite. La familia se deduce del nombre del modelo; si no, se indica con `LLM_FAMILIA_<N>`. Los límites de los proveedores son **por cuenta y por modelo**: dos keys de la misma cuenta comparten el límite de cada modelo.

**Modelos en uso** (probados de punta a punta el 23-10-2026):

| Rol | Modelo | Proveedor | Nota |
|-----|--------|-----------|------|
| Moderador, cuestionario y riesgos | `openai/gpt-oss-120b` (4 keys de cuentas distintas) | Groq | Rápido (~6 s por cuestionario) |
| Experto | `gemini-3.5-flash` | Google AI Studio | La cuota diaria gratuita es **por modelo**: si una versión la agota (pasó con `gemini-flash-latest`), se puede usar otra |
| Experto | `gemma-4-31b-it` | Google AI Studio | Lento (~2 min por respuesta) |
| Experto | `openai/gpt-oss-20b` | Groq | Razonamiento `low` y `LLM_MAX_TOKENS=2200`. **Solo alcanza para la ronda 1:** desde la ronda 2 el prompt (con la respuesta anterior y el feedback, más lo que agrega CrewAI) supera su límite de 8000 tokens por minuto, y el motor le pasa el experto a otro modelo (evento `cambio_modelo`) |
| Descartados | Qwen (límite de 1000 tokens/min), MiniMax (dejó de ser gratis), Nemotron (lento), Gemini Pro (fuera del plan gratuito) | | |

**`ModelPool` (`backend/delphi/config.py`):**

- Carga los bloques `LLM_*_<NOMBRE>` y expone `listar_modelos()`, que devuelve solo el nombre, el proveedor y la familia (**nunca la key**), `get_llm(agente_id) -> crewai.LLM` (para `"moderador"`, la lista de LLM de sus keys) y `get_client(agente_id) -> OpenAI`.
- **Asignación de modelos a roles:**
  - `auto`: reparte los modelos de forma equilibrada; con 3 modelos y 6 expertos, cada modelo atiende a 2. Los **roles afines nunca comparten modelo** (Arquitectura–Desarrollo, Cloud–DevOps, Seguridad–Datos), porque son los que más se solapan en sus opiniones.
  - `seed`: rota la asignación entre ejecuciones, para separar el sesgo del rol del sesgo del modelo.
  - `manual`: se elige desde el frontend.
  - `mono`: todo el panel usa un solo modelo (el elegido en el frontend o, si no, el primero del `.env`). Sirve como control para el experimento de sesgo. Si hay menos de 2 familias disponibles, el sistema avisa: *"panel mono-modelo: riesgo de falso consenso"*.
- **Moderador neutral:** usa los bloques `MODERADOR_<n>`; si no hay, el modelo de experto menos usado por el panel. Si su familia es la de la mayoría del panel, el informe lo avisa.
- **Errores 429 o caídas:** reintento con espera progresiva (*backoff*: 30 s, 60 s) en el mismo modelo, y en cada reintento el Moderador pasa a la key siguiente. Si el error persiste, o si el modelo ya no existe (404, variante retirada), y es del experto, `alternativo()` le asigna otro modelo (respetando los roles afines; nunca en modo `mono`), y el cambio se registra con el evento `cambio_modelo`.

Qué hace el sistema cuando un proveedor pone límites:

![Modelos de IA y respaldos: ante un 429 espera y reintenta; ante un 413 o 404, o una respuesta inválida que no se corrige, cambia el modelo del experto](docs/img/arquitectura-5-modelos-y-respaldos.jpg)

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

class Viabilidad(BaseModel):              # veredicto global; lo calcula el código desde el ítem VIA-E1
    veredicto: Literal["viable", "viable_con_condiciones", "no_viable", "en_discusion"]
    mediana: float
    iqr: float
    consenso: bool
    explicacion: str

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
    viabilidad: Viabilidad | None = None   # ¿el proyecto, tal como está planteado, es viable?

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

- [x] Estructura del repositorio, `requirements.txt`, `.env.example` y `.gitignore`. **El `.env` con keys reales nunca se sube.**
- [x] `models.py`: transcribir los contratos de §4 el **día 1** y subirlos a `main`.
- [x] `stats.py` (**día 1**, porque el motor lo usa): mediana, Q1/Q3, IQR, consenso por ítem y global, estabilidad entre rondas y la **regla de recomendación** de §1.2 (firme, condicionada o abierta, con el margen respecto de la segunda alternativa). Son funciones puras, sin LLM.
- [x] `llm_io.py`: extraer el JSON de la respuesta (quitando los bloques `<think>` de los modelos de razonamiento), validarlo con Pydantic y reintentar una vez con el error en el prompt. Lo usan los expertos y el Moderador.
- [x] `config.py` → `ModelPool` (§3):
  - Carga de los bloques del `.env`.
  - Modos `auto`, `seed`, `manual` y `mono`, con la **restricción de roles afines**.
  - Moderador neutral.
  - *Backoff* ante 429 y cambio de modelo registrado.
- [x] `project_loader.py` + `data/plantilla_proyecto.md`: convierte la plantilla en `Proyecto`.
- [x] `data/proyectos/`: 3 proyectos informáticos de ejemplo que obliguen a decidir:
  - **Viable:** sistema de reservas para una red de clínicas (equipo de 4 personas con experiencia, 6 meses).
  - **Polémico:** migración de un ERP monolítico *on-premise* a la nube (¿*lift & shift* o refactorizar a microservicios?).
  - **Débil:** marketplace con IA generativa en 3 meses, con 2 desarrolladores junior y presupuesto mínimo.
- [x] `api/store.py` → `RunStore`: persistencia en `outputs/runs/<run_id>/`.
- [x] `api/main.py`: todos los endpoints de §4.2. Ejecución en segundo plano, un análisis activo a la vez con cola, y cancelación por bandera.
- [x] Hasta tener el motor real, un `DelphiEngine` *stub* que emita eventos falsos con tiempos realistas. Hoy es el modo simulado (`DELPHI_SIMULADO=true`, `simulado.py`), que corre el motor real con LLM falsos.
- [x] Tests de `stats.py` (incluida la regla de recomendación), `llm_io.py`, `ModelPool` y la API.

### 👤 Pamela — Orquestación Delphi: Moderador, motor, informe y ADR

- [x] `tools.py` → `DelphiStatsTool(BaseTool)`, que envuelve `stats.py` para CrewAI.
- [x] **Prompts del Moderador:**
  - Identificar las **3 a 5 decisiones clave** del proyecto con sus alternativas realistas (y respetar las `decisiones_a_evaluar` si las hay).
  - Generar los ítems de evaluación por dimensión.
  - Decidir si continuar. El feedback de cada ronda no lo redacta el LLM: son las estadísticas y los argumentos anónimos saneados, para que ningún texto libre llegue a otro experto.
- [x] `crew.py`:
  - **Moderador Delphi** como `manager_agent` (no `manager_llm`).
  - Los expertos del panel como *workers*, cada uno con `llm=ModelPool.get_llm(rol)`.
  - Las tareas de los expertos van con `context=[]` explícito (sin él, CrewAI pasa las salidas anteriores).
  - Enunciado sellado y salida tomada del experto (`ExpertoDelphi`).
  - `max_iter` acotado.
- [x] `engine.py` → `DelphiEngine.run(...)`:
  - Bucle de rondas: un `Crew` jerárquico **por experto** y ronda, para que el Moderador no acumule el panel completo en su contexto y no supere el límite de tokens por minuto del plan gratuito. Los expertos responden en paralelo (cada uno en su Crew, sin verse entre sí); cada respuesta se emite apenas llega.
  - Emisión de **todos** los eventos de §4.1, incluido `cambio_modelo`.
  - Límites impuestos por el código: `max_rondas`, consenso y estabilidad.
  - `guard_independencia`.
  - Respeto de `should_cancel`, revisado entre experto y experto.
  - **Consolidación de riesgos:** agrupar los `riesgos_detectados` duplicados entre expertos y estimar su probabilidad e impacto.
- [x] `report.py` → `informe.md`:
  - Resumen ejecutivo y tabla de decisiones (✅ firme / ⚠️ condicionada / ❓ abierta).
  - Evaluación por dimensión y matriz de riesgos.
  - Disensos y PoC sugeridas.
  - Evolución por ronda y sesgo por modelo.
- [x] `adr.py`: un ADR por decisión, con el formato de §1.7 y la evidencia Delphi.
- [x] `cli.py`: `python -m backend.cli data/proyectos/x.md` para depurar el motor sin API ni frontend.

### 👤 Jenaro — Panel de expertos TI y análisis de sesgo + Frontend

**Sistema (motor):**
- [x] `experts.py`:
  - **Catálogo de los 10 expertos** de §1.1, con `role`, `goal` y `backstory` detallados, y prioridades y sesgos **explícitos y distintos**. Cada perfil incluye las preguntas que ese experto siempre se haría; por ejemplo, Seguridad: "¿dónde se guardan los datos personales y quién accede?".
  - `sugerir_panel(proyecto)`: el núcleo más los opcionales según el input. Por ejemplo, si se mencionan IA o LLM se agrega `ia`; si hay usuarios finales o apps se agrega `ux`; si hay migración o grandes volúmenes, `datos`; si el plazo es corto o el equipo junior, `gestion`. Devuelve también el motivo de cada sugerencia.
- [x] `prompts.py`: prompts **de experto**:
  - Ronda 1: respuesta independiente, que incluye los `riesgos_detectados`.
  - Ronda k: respuesta propia anterior + feedback anónimo + obligación de justificar si queda fuera del IQR.
- [x] `anonymizer.py` → `AnonymizerTool(BaseTool)`: agrupa y resume los argumentos a favor y en contra de cada ítem y alternativa, y quita el rol, el autor y las **marcas de estilo de cada modelo**.
- [x] `bias.py`:
  - Puntaje medio de cada modelo y sus **preferencias por alternativa** (`SesgoModelo`).
  - Script del **experimento de control**: corre los 3 proyectos en modo `mono` y en modo `auto` y genera una tabla que muestra si cambian las decisiones recomendadas.
- [x] Tests de `experts.py` (`sugerir_panel`), `anonymizer.py` y `bias.py`.

**Frontend (Streamlit):**
- [x] `api_client.py` con un interruptor `USE_MOCKS=true`, y `mocks/` con un run completo falso (uno de los proyectos de ejemplo) para desarrollar **sin esperar al backend**.
- [x] **Página 1 · Nuevo análisis:**
  - Formulario con la **plantilla de proyecto informático** (§1.6), o subir un `.md`, o elegir uno de `data/proyectos/`.
  - **Panel sugerido**, editable con casillas y con el motivo de cada experto.
  - Asignación de modelos (`auto`, `seed`, `manual` con un selector por experto, o `mono` para el control).
  - Reglas Delphi y botón **Iniciar**.
- [x] **Página 2 · Ejecución en vivo:**
  - Estado, ronda actual y línea de tiempo de eventos.
  - Respuestas anónimas E1…E7 a medida que llegan; el interruptor **"modo auditor"** muestra el rol y el modelo de cada una.
  - Decisión del Moderador y botón **Cancelar**.
- [x] **Página 3 · Decisiones y resultados:**
  - **Tablero de decisiones:** una tarjeta por decisión, con la alternativa recomendada, su estado (firme, condicionada o abierta), la mediana, el IQR, las condiciones o la PoC sugerida.
  - Gráfico de mediana e IQR por alternativa y ronda (Plotly), para ver la convergencia.
  - **Radar por dimensión** (arquitectura, infraestructura, stack…).
  - **Matriz de riesgos** (probabilidad × impacto).
  - Argumentos a favor y en contra, disensos, y **sesgo por modelo**.
  - Descargas: `informe.md`, `informe.json` y `adr.zip`.
- [x] **Página 4 · Historial / Comparar:** lista de runs y comparación lado a lado de dos runs. Sirve, por ejemplo, para mono contra multi-modelo, o para el mismo proyecto con distintos paneles.

### 👥 Conjuntas

- [ ] **Día 1:**
  - Acordar las reglas Delphi (§1.5), el catálogo de expertos (§1.1) y la regla de recomendación (§1.2), y congelar los contratos (§4).
  - Cada uno elige un modelo de una **familia distinta**, crea su key, la agrega a su `.env` local y comparte con el equipo **solo** el proveedor y el nombre del modelo.
- [x] **Integración:** quitar los *mocks* del frontend y el *stub* del motor, y probar de punta a punta con los 3 proyectos. *Clínicas y ERP con la CLI; marketplace desde el frontend con la API y modelos reales (§9).*
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

## 8. Ejecución

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env                     # completar las keys (§3)
```

**Sistema completo** (dos terminales):

```powershell
.venv\Scripts\python.exe -m uvicorn backend.api.main:app --reload      # API en http://localhost:8000
.venv\Scripts\python.exe -m streamlit run frontend/app.py              # Frontend en http://localhost:8501
```

Con `USE_MOCKS=false` en el `.env`, el frontend usa la API. Para una demo sin keys hay dos opciones:

- `DELPHI_SIMULADO=true`: la API corre el motor real con LLM falsos. Prueba la API, los eventos, la persistencia y el frontend de punta a punta.
- `USE_MOCKS=true`: el frontend no usa la API (ver la [guía de Jenaro](docs/entrega_jenaro.md)).

**Motor sin API ni frontend**, para depurar:

```powershell
.venv\Scripts\python.exe -m backend.cli data/proyectos/clinica_reservas.md            # LLM reales
.venv\Scripts\python.exe -m backend.cli data/proyectos/migracion_erp.md --asignacion mono
.venv\Scripts\python.exe -m backend.cli data/proyectos/marketplace_ia.md --mock        # sin keys
```

**Experimento de sesgo** (con la API iniciada):

```powershell
.venv\Scripts\python.exe -m scripts.experimento_sesgo --api-url http://localhost:8000 --timeout 1800 --proyectos data/proyectos/clinica_reservas.md data/proyectos/migracion_erp.md data/proyectos/marketplace_ia.md
```

**Tests:** `.venv\Scripts\python.exe -m pytest -q` (sin keys ni red).

> **Cuota del LLM:** por ronda, cada experto hace 1 llamada y el Moderador unas 2 por experto (delegar y cerrar), más 1 para decidir si continuar. A eso se suman 1 llamada para el cuestionario y 1 para consolidar los riesgos. Con 5 expertos y 3 rondas son unas **50 llamadas**, pero las del Moderador son cortas porque el enunciado va sellado y no lo copia. Los expertos responden **en paralelo** (`DELPHI_PARALELO`, 5 por defecto; `--paralelo` en la CLI), así que cada ronda dura lo que tarda el experto más lento. Para el límite de tokens por minuto sirven las keys `MODERADOR_<n>` de cuentas distintas y `DELPHI_PAUSA` (5 s por defecto entre el inicio de un experto y el siguiente). Con `DELPHI_PARALELO=1` responden de a uno. Si se agota la cuota, reducir el panel a los 5 del núcleo o usar `max_rondas = 2`.

## 9. Validación con modelos reales

Corridas de punta a punta con la configuración de *Modelos en uso* (§3), el 23-10-2026.

| Proyecto | Rondas | Consenso | Decisiones | Duración |
|----------|:------:|:--------:|------------|:--------:|
| Clínicas (viable) | 2 | 100 % y 100 % | ✅ Monolito modular · ✅ PaaS gestionado · ✅ PWA | 27 min (antes de ejecutar a los expertos en paralelo) |
| ERP (polémico) | 2 | 96 % y 96 % | ✅ Lift & shift · ✅ Mantener Oracle · ✅ Máquinas virtuales · ⚠️ Identidad cloud (empata con Zero-Trust) · ⚠️ Blue-green (empata con migración por módulos) | **5 min 34 s** |
| Marketplace (débil), **desde el frontend**, 7 expertos | 2 | **60 % → 80 %** | ✅ **MVP de catálogo** (el marketplace completo sacó 1) · ✅ Serverless · ✅ Cifrado mínimo PCI DSS · ✅ Pruebas automatizadas · ⚠️ Observabilidad completa | 6 min 30 s |

**Observaciones para la validación con criterio humano:**

- Las recomendaciones son coherentes con las restricciones de cada proyecto: un equipo pequeño con plazo corto lleva al monolito y la plataforma gestionada, y un equipo sin experiencia cloud con 14 meses de plazo lleva al *lift & shift*.
- El sistema **distingue los tres casos**: en el marketplace el consenso parte en 60 % (frente a 96-100 % en los otros), las evaluaciones por dimensión bajan a 2-3 (frente a 3-5 en clínicas), recomienda recortar el alcance a un MVP y señala riesgos altos (fuga de datos por *prompts*, bugs por falta de experiencia y pruebas, agotar los créditos de IA). Desde esa corrida, el motor agrega siempre la pregunta de viabilidad global (`VIA-E1`) y el informe trae un **veredicto explícito** (`InformeDelphi.viabilidad`).
- El ERP muestra que el panel también distingue matices: dos decisiones quedaron condicionadas por empate y un ítem (la protección de Zero-Trust) terminó sin consenso (IQR 2).
- El consenso es alto desde la ronda 1. Con 5 expertos y notas de 1 a 5, el umbral IQR ≤ 1 es fácil de cumplir (2, 3, 3, 4, 5 ya es consenso). Conviene probar `umbral_iqr = 0.5` (se cambia en la página 1) o acentuar los sesgos de los perfiles.
- Los riesgos siempre muestran "5 menciones": el conteo de `consolidar_riesgos` compara palabras sueltas y con descripciones largas todo coincide. Pendiente de ajustar.

**Problemas de los planes gratuitos que el motor ya resuelve solo:**

| Situación | Qué hace el motor |
|-----------|-------------------|
| Límite por minuto (429) | Espera 30 s y 60 s y reintenta; el Moderador pasa a su key siguiente |
| Petición mayor que el límite por minuto (413) o modelo retirado (404) | Cambia de inmediato el modelo del experto (`cambio_modelo`), respetando los roles afines, y encadena respaldos si hace falta |
| Respuesta incompleta o JSON mal formado | Reintenta con el error en el prompt; si sigue mal, cambia de modelo |
| Pregunta de evaluación vinculada a una decisión | La desvincula al recibir el cuestionario |
| Cuestionario más grande que lo acordado | Lo recorta a 5 decisiones y 10 evaluaciones |

**Limitación conocida:** con el plan gratuito de Groq, GPT-OSS-20B solo responde la ronda 1; desde la ronda 2 su experto pasa a Gemini o Gemma. El panel conserva 3 familias en la ronda 1 y 2 en las siguientes. Con una key de pago (o un proveedor con más tokens por minuto) se mantienen las 3 en todas las rondas.
