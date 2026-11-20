# Plan EP3: Observabilidad del Panel Delphi

**Equipo:** Juan · Pamela · Jenaro  
**Rúbrica:** [`rubrica_3.pdf`](rubrica_3.pdf), ISY1010 Evaluación Parcial N°3 (35 %), con encargo (60 %) y presentación (40 %)  
**Calendario:** instrucciones en la semana 14, presentación en la semana 17 y entrega del informe y el repositorio en la semana 18.

> La rúbrica está pensada para parejas; nosotros somos tres. Cada uno es dueño de un bloque de indicadores y los tres tienen que hablar en la presentación (≈ 3 min 20 s cada uno).

---

## 1. Qué pide la rúbrica y quién responde

| IE | Qué pide | Peso | Dueño | Apoyo |
|----|----------|:----:|-------|-------|
| **IE1** | Métricas de **precisión, consistencia y frecuencia de errores** en escenarios con variabilidad de datos | 15 % | Pamela | Juan (datos crudos) |
| **IE2** | Métricas de **latencia y uso de recursos** en escenarios variados | 10 % | Juan | — |
| **IE3** | Examinar **logs y eventos** para encontrar errores y cuellos de botella | 15 % | Pamela | Juan |
| **IE4** | **Dashboard** visual, claro e interactivo con todas las métricas | 10 % | Jenaro | Juan (endpoints) |
| **IE5** | **Informe técnico** de hasta 5 páginas, con capturas, gráficos y referencias APA | 10 % | Pamela (editora) | Los tres |
| **IE6** | Presentación: **patrones y anomalías** en los registros y correcciones justificadas | 10 % | Pamela | — |
| **IE7** | Presentación: **mejoras y rediseño** para la sostenibilidad y la escalabilidad | 10 % | Juan | — |
| **IE8** | Presentación: **seguridad, ética y privacidad** en producción | 10 % | Jenaro | — |
| **IE9** | **Lenguaje técnico** y defensa con datos del dashboard | 10 % | Los tres | — |

Encargo = IE1–IE5 (60 %). Presentación = IE6–IE9 (40 %). Cada uno defiende en la presentación lo que construyó.

---

## 2. Punto de partida: qué ya tenemos

El sistema de la EP2 ya deja trazas útiles, aunque nadie las mide todavía:

- `outputs/runs/<run_id>/eventos.jsonl`: eventos `run_iniciado`, `respuesta_experto`, `ronda_agregada`, `decision_moderador`, `cambio_modelo`, `error`, etc., con `timestamp` y `seq`.
- `rondas.json`, `informe.json` y `estado.json` por run.
- Logs de texto del logger `delphi`, sin estructura (`engine.py`, `api/main.py`).
- Respaldos ante 429, 413, 404 y JSON inválido (`config.py`, `llm_io.py`), aunque no se cuentan.
- Modo simulado (`DELPHI_SIMULADO=true`) para correr muchas ejecuciones sin gastar cuota.

**Lo que falta:** latencia y tokens por llamada al LLM, conteo de errores y reintentos, uso de CPU y RAM, métricas agregadas, un dashboard de observabilidad, un conjunto de referencia ("gold") para medir precisión y protocolos explícitos de privacidad en los logs.

**Problemas conocidos (README §9)** que conviene presentar como hallazgos de la trazabilidad, con su medición antes y después:

1. Los riesgos siempre muestran "5 menciones": `consolidar_riesgos` compara palabras sueltas.
2. GPT-OSS-20B (Groq) solo responde la ronda 1; desde la ronda 2 cae a otro modelo por 413, y el panel pierde una familia.
3. El consenso es demasiado fácil con IQR ≤ 1 (≥ 96 % desde la ronda 1).
4. Las esperas de 30 s y 60 s ante 429 inflan la duración de cada run.

---

## 3. Contrato del día 1 (lo congelan los tres antes de separarse)

Cada llamada a un LLM y cada fase del motor escribe **una línea** en `outputs/runs/<run_id>/metricas.jsonl`. Es un archivo aparte de `eventos.jsonl`, para no inundar el frontend en vivo ni tocar `EventoDelphi`.

```jsonc
// Una línea por "span" (llamada a LLM, herramienta o fase)
{
  "run_id": "a1b2c3",
  "span_id": "s-0042",
  "padre": "s-0007",             // fase o ronda que lo contiene; null en la raíz
  "tipo": "llm" | "herramienta" | "fase",
  "nombre": "experto.seguridad" | "moderador.delegar" | "asesor.investigar" | "ronda_2" | ...,
  "ronda": 2,                     // null fuera de las rondas
  "escenario": "clinica_base",    // lo fija el script de escenarios; null si es un run manual
  "modelo": "gemini-2.5-flash",   // null si tipo != "llm"
  "proveedor": "google" | "groq" | "simulado",
  "inicio": "2026-11-24T15:02:11.123Z",
  "latencia_ms": 8423,
  "tokens_entrada": 3120,         // del proveedor si lo informa; si no, estimado (len/4) y "tokens_estimados": true
  "tokens_salida": 412,
  "tokens_estimados": false,
  "intento": 1,                   // 2, 3... en los reintentos
  "resultado": "ok" | "json_invalido" | "http_429" | "http_413" | "http_404" | "http_5xx" | "timeout" | "error",
  "espera_backoff_ms": 0,
  "cambio_modelo": null,          // {"de": "...", "a": "..."} si hubo cambio
  "cpu_pct": 12.5,                // muestra de psutil al cerrar el span
  "rss_mb": 412.0
}
```

Resumen agregado que expone la API (Juan) y consume el dashboard (Jenaro):

```
GET /runs/{id}/metricas          → lista de spans de un run (para la traza tipo cascada)
GET /metricas/resumen?escenario= → KPIs agregados por modelo, escenario y run (estructura en §4.1)
GET /metricas/calidad            → precisión y consistencia (lo calcula metricas.py de Pamela)
```

Hasta que existan los endpoints, Jenaro trabaja con un `metricas.jsonl` de ejemplo en `frontend/mocks/`, como en la EP2.

**Reglas del contrato:** los logs **nunca** guardan el prompt ni la respuesta completos, solo su longitud y un hash SHA-256 (ver §6, privacidad). Cambiar este formato requiere el visto bueno de los tres, igual que `models.py`.

---

## 4. Tareas por persona

### 👤 Juan: telemetría, latencia, recursos y escalabilidad (IE2, IE7)

**Rama:** `feat/obs-telemetria`

- [ ] `backend/delphi/observabilidad.py`:
  - Context manager `span(nombre, tipo, **atributos)` que mide la latencia con `time.perf_counter()`, enlaza `padre` mediante un `contextvars` y escribe la línea en `metricas.jsonl`.
  - Logging estructurado en JSON (`run_id` y `span_id` en cada línea) para reemplazar el formato de texto actual en `engine.py`, `api/main.py` y `cli.py`.
  - Muestreo de CPU y RAM del proceso con `psutil` (agregarlo a `requirements.txt`).
- [ ] Instrumentar las llamadas a los LLM:
  - **Opción A:** un listener del bus de eventos de CrewAI (eventos de inicio, fin y falla de cada llamada al LLM). Antes hay que comprobar qué eventos expone la versión instalada (1.15).
  - **Opción B (respaldo):** envolver la llamada en `config.py` (`crear_llm` / `ModelPool._llm`) y en `llm_io.llamar_y_validar`.
  - En ambos casos: registrar los tokens desde el `usage` del proveedor y, si no viene, estimarlos con `tokens_estimados: true`; clasificar el `resultado` (429, 413, JSON inválido…), las esperas de backoff y los `cambio_modelo`.
- [ ] Spans de **fase** en `engine.py` y `asesor.py`: asesor, cuestionario, cada ronda, agregación, decisión del Moderador e informe. Esto permite ver la ruta crítica.
- [ ] Endpoints `GET /runs/{id}/metricas` y `GET /metricas/resumen` en `api/main.py`, leyendo los `metricas.jsonl` de `RunStore`.
- [ ] `scripts/correr_escenarios.py`: corre la matriz de escenarios de §5 contra la API, etiqueta cada run con su `escenario` y consolida todo en `outputs/observabilidad/resumen.csv`.
- [ ] **Métricas IE2**, calculadas en el resumen:
  - L1: latencia por llamada p50, p95 y máx., por modelo y proveedor.
  - L2: duración por fase y experto más lento por ronda (ruta crítica).
  - L3: duración total del run según el escenario, el tamaño del panel (5 contra 7) y el paralelismo (`DELPHI_PARALELO` 1 contra 5).
  - L4: tiempo perdido en backoff, en segundos y como % del run.
  - R1: tokens de entrada y salida por agente, por run y por ronda, y su costo equivalente en USD según precios públicos (aunque usemos plan gratuito).
  - R2: llamadas al LLM por run, frente a las ≈ 50 estimadas en el README §8.
  - R3: CPU y RAM pico y promedio, y tamaño en disco de `outputs/`.
  - R4: % del límite de tokens por minuto (TPM) consumido por proveedor.
- [ ] Tests: `span` anidados, escritura concurrente desde los expertos en paralelo (con un lock) y endpoints con datos simulados.
- [ ] **IE7, propuesta de escalabilidad** (la escribe Juan y se respalda con números del dashboard), por ejemplo:
  - Caché de respuestas del Asesor o del RAG por hash del proyecto.
  - Enrutar a los expertos según la latencia p95 observada por modelo.
  - Presupuesto de tokens por run.
  - Cola de trabajos (Redis/RQ o Celery) en lugar de un análisis a la vez.
  - Rondas asíncronas y exportación a OpenTelemetry/Grafana en producción.

### 👤 Pamela: precisión, consistencia, errores y análisis de trazas (IE1, IE3, IE6, editora de IE5)

**Rama:** `feat/obs-metricas`

- [ ] `data/evaluacion/gold.json`: el **conjunto de referencia** con el veredicto esperado y la alternativa esperada por decisión para los 3 proyectos canónicos y sus variantes. Lo **validan los tres** en una reunión de 30 min. Esto cierra además el pendiente "Validación con criterio humano" del README §5.
- [ ] `data/proyectos/variantes/`: los escenarios con variabilidad de datos (§5), derivados de los 3 proyectos.
- [ ] `backend/delphi/metricas.py`: funciones puras, sin LLM y testeables, que leen `informe.json`, `rondas.json` y `metricas.jsonl`:
  - **Precisión:**
    - P1: % de respuestas con JSON válido al primer intento, por modelo.
    - P2: acierto del veredicto de viabilidad frente al gold.
    - P3: % de decisiones cuya alternativa recomendada coincide con el gold.
    - P4: precisión de citas del Asesor, es decir, citas verificadas sobre citas totales (`asesor.verificar_ficha`).
  - **Consistencia:**
    - C1: entre repeticiones (3 runs del mismo proyecto y configuración), % de decisiones con la misma recomendación y desviación estándar de las medianas.
    - C2: convergencia dentro del run, con el IQR medio por ronda y el % de consenso de la ronda 1 a la 2.
    - C3: robustez ante perturbaciones, es decir, si la variante parafraseada recomienda lo mismo que la base.
  - **Errores:**
    - E1: errores cada 100 llamadas, por tipo y por modelo.
    - E2: `cambio_modelo` y reintentos por run.
    - E3: % de runs que terminan en `error` o `cancelado`.
- [ ] `scripts/analizar_trazas.py`: recorre `eventos.jsonl` y `metricas.jsonl` y produce `docs/observabilidad/hallazgos.md` con los **puntos críticos**: cuellos de botella, anomalías por modelo, patrones de error y su causa raíz.
- [ ] **Correcciones con antes y después** (para IE3 e IE6). Se toma una línea base **antes** de tocar nada, se corrige y se vuelve a medir:
  1. Conteo de riesgos ("5 menciones"): comparar por similitud de embeddings o por bigramas en `consolidar_riesgos`.
  2. Umbral de consenso: comparar la discriminación entre proyectos con `umbral_iqr` 1 y 0,5.
  3. Pérdida de familia por 413 en GPT-OSS: recortar el prompt de la ronda k o asignar ese modelo solo a roles con prompts cortos.
  4. Lo que aparezca en las trazas (por ejemplo, un experto que siempre es el más lento o un modelo con JSON inválido recurrente).
- [ ] Tests de `metricas.py` con runs de ejemplo.
- [ ] **Editora del informe (IE5)**: arma el documento de 5 páginas (§7) con las secciones que entrega cada uno.

### 👤 Jenaro: dashboard, seguridad y uso responsable (IE4, IE8)

**Rama:** `feat/obs-dashboard-seguridad`

- [ ] **Dashboard** `frontend/pages/5_Observabilidad.py` en Streamlit + Plotly, que ya dominamos. La rúbrica acepta Streamlit.
  - **Filtros:** escenario, run, modelo, proveedor y rango de fechas.
  - **Fila de KPIs con semáforo:** latencia p95, errores cada 100 llamadas, tokens por run, precisión frente al gold y consistencia C1. Cada KPI con un umbral definido (verde, ámbar, rojo).
  - **Latencia:** boxplot por modelo y barras apiladas por fase.
  - **Traza de un run en cascada (*waterfall*/Gantt):** cada span como barra en el tiempo, con los expertos en paralelo y las esperas de backoff en otro color. Es la vista estrella para IE3 e IE6.
  - **Errores:** mapa de calor de modelo × tipo de error, más una línea de `cambio_modelo` por ronda.
  - **Recursos:** tokens de entrada y salida por agente, CPU y RAM en el tiempo, y costo equivalente.
  - **Calidad:** tabla de precisión frente al gold (P1–P4) y gráfico de consistencia entre repeticiones (C1–C3).
  - **Antes y después:** comparación de la línea base con la versión corregida para cada corrección de Pamela.
  - **Explorador de eventos:** tabla filtrable de `eventos.jsonl` con su payload, sin PII.
  - Desarrollo contra mocks (`frontend/mocks/metricas_ejemplo.jsonl`) y luego contra los endpoints de Juan.
- [ ] **Capturas** del dashboard en `docs/img/obs-*.png` para el informe y el README.
- [ ] **Seguridad y privacidad (IE8)**, implementadas en código y no solo descritas:
  - `backend/delphi/privacidad.py`: detecta y **redacta PII** (RUT chileno, correo, teléfono, nombres en campos de contacto) en el proyecto **antes** de enviarlo a un LLM externo y **antes** de escribir logs. Métrica: PII detectada y redactada por run.
  - **Minimización en logs:** los prompts y las respuestas no se guardan completos (hash + longitud); hay un modo `DELPHI_LOG_DEBUG=true` solo para desarrollo local. Test que verifique que ninguna key del `.env` aparece en los logs.
  - **Defensa ante *prompt injection*:** delimitar el input del usuario y detectar instrucciones sospechosas ("ignora las instrucciones…") en el proyecto, con un escenario de prueba (§5).
  - **Retención y supresión (Ley 21.719):** plazo de conservación configurable para `outputs/runs/`, y `DELETE /runs/{id}` que también borra el análisis de la memoria institucional (derecho de supresión). Lo implementa Jenaro y lo revisa Juan.
  - **Control de acceso mínimo en la API:** header `X-API-Key` opcional, activado en "producción".
  - **Ficha de uso responsable** (`docs/observabilidad/uso_responsable.md`): alcance y límites del sistema (las decisiones son recomendaciones y requieren revisión humana), sesgo por modelo (`bias.py`), verificación de citas y mapeo a la Ley 21.719, OWASP Top 10 for LLM Applications y NIST AI RMF.
- [ ] Tests de `privacidad.py`, del escenario de inyección y de que no se filtran keys.

### 👥 Conjuntas

- [ ] **Día 1:** congelar el contrato de §3, la matriz de escenarios (§5) y los umbrales del semáforo.
- [ ] **Reunión gold (30 min):** validar `gold.json` entre los tres.
- [ ] **Corrida de línea base** con la matriz completa **antes** de las correcciones (la lanza Juan y la guarda en `outputs/observabilidad/baseline/`).
- [ ] **Corrida final** después de las correcciones, con la misma matriz.
- [ ] README: nueva sección "Observabilidad" con cómo correr escenarios, el dashboard y los tests (cada uno escribe su parte).
- [ ] Presentación (§8) y ensayo cronometrado.
- [ ] **Reflexión individual de cada uno, escrita sin IA** (es obligatoria y la rúbrica prohíbe usar IA en ella).

---

## 5. Escenarios con variabilidad de datos

La rúbrica exige medir "en escenarios con variabilidad de datos". Proponemos esta matriz, que Juan corre con `correr_escenarios.py` y que Pamela crea en `data/proyectos/variantes/`:

| Escenario | Qué varía | Qué mide sobre todo |
|-----------|-----------|---------------------|
| `*_base` (×3) | Los 3 proyectos canónicos | Línea de referencia y precisión frente al gold |
| `*_repeticion` (×3 runs) | El mismo proyecto y la misma config, repetido | Consistencia C1 |
| `clinica_parafraseado` | El mismo contenido con otras palabras | Robustez C3 |
| `erp_incompleto` | Plantilla con secciones vacías | Errores y comportamiento ante datos faltantes |
| `marketplace_largo` | El proyecto ×3 de largo | Latencia, tokens y errores 413 |
| `clinica_con_pii` | Input con RUT, correos y teléfonos ficticios | Redacción de PII (IE8) |
| `erp_inyeccion` | Instrucciones maliciosas dentro de la descripción | Defensa ante inyección (IE8) |
| `panel_7` y `paralelo_1` | Tamaño del panel y paralelismo | Escalabilidad: latencia y recursos (IE2, IE7) |
| `mono` contra `auto` | Asignación de modelos | Consistencia y sesgo |

**Presupuesto de cuota:** la mayoría de las repeticiones corren en **modo simulado** (valida el pipeline y da volumen para el dashboard). Con **modelos reales** corren al menos los 3 base, 1 repetición de cada uno y los escenarios de PII, inyección y largo. El informe y el dashboard **siempre marcan qué datos son simulados**: con el simulador no se sacan conclusiones sobre los modelos.

---

## 6. Ética, privacidad y seguridad: argumento para la presentación (IE8)

El hilo para defender: *"la observabilidad también es un riesgo de privacidad"*. Los logs de un agente LLM pueden terminar guardando datos personales del proyecto analizado. Por eso:

1. **Minimización** (Ley 21.719): solo métricas, hash y longitud; nunca el prompt completo en producción.
2. **PII redactada** antes de salir hacia proveedores externos (Google, Groq). Es transferencia internacional de datos (art. 27, que el RAG ya cita).
3. **Finalidad y conservación:** plazo de retención y supresión real, que incluye la memoria institucional.
4. **Seguridad:** las keys nunca van a logs ni a Git, la API tiene control de acceso y hay defensa ante inyección.
5. **Uso responsable:** las decisiones son recomendaciones con evidencia Delphi y revisión humana; las citas legales se verifican por su origen, no por su interpretación; se mide el sesgo por modelo.

---

## 7. Informe técnico (máximo 5 páginas, Word/PDF)

| Sección | Págs. | Redacta | Evidencia |
|---------|:-----:|---------|-----------|
| 1. Contexto, arquitectura de observabilidad y escenarios | 0,5 | Juan | Diagrama de spans y matriz de §5 |
| 2. Métricas implementadas: definición, fórmula y resultados (IE1, IE2) | 1,25 | Pamela (P, C, E) y Juan (L, R) | Tablas y 2 gráficos |
| 3. Análisis de registros y trazabilidad: hallazgos y causa raíz (IE3) | 1 | Pamela | Captura de la traza en cascada y del mapa de errores |
| 4. Dashboard (IE4) | 0,5 | Jenaro | 2–3 capturas |
| 5. Seguridad, privacidad y uso responsable | 0,5 | Jenaro | Tabla de controles frente a la norma |
| 6. Recomendaciones, cada una justificada con una métrica (IE5, IE7) | 0,75 | Juan + Pamela | Antes y después |
| 7. Conclusiones + **3 reflexiones individuales (sin IA)** | 0,5 | Los tres | — |
| Referencias APA + declaración de uso de IA | Anexo | Pamela | — |

**Repositorio:** código, README actualizado con instrucciones para reproducir, tests pasando, capturas y bocetos del dashboard. Se envía por AVA y al correo del docente.

---

## 8. Presentación (10 min de exposición + 10 de preguntas)

| Min | Bloque | Expone | IE |
|-----|--------|--------|----|
| 0:00–1:00 | El sistema en 1 minuto y qué observamos | Juan | — |
| 1:00–4:00 | **Análisis crítico de ejecución:** demo del dashboard, la traza en cascada, los patrones y anomalías encontrados, y las correcciones con su antes y después | Pamela | IE6, IE9 |
| 4:00–6:40 | **Mejora y escalabilidad:** latencia, tokens y costo; cuellos de botella; rediseño propuesto con números | Juan | IE7, IE9 |
| 6:40–9:30 | **Ética y privacidad:** demo del escenario con PII y del de inyección; controles frente a la Ley 21.719 y OWASP LLM | Jenaro | IE8, IE9 |
| 9:30–10:00 | Cierre | Los tres | — |

**Regla para las preguntas:** cada uno debe poder explicar cualquier gráfico del dashboard, no solo el suyo. Hay un ensayo de preguntas cruzadas la semana 16.

Apoyo visual: el dashboard en vivo (con capturas de respaldo por si falla la red) + 6–8 diapositivas.

---

## 9. Cronograma

| Semana | Juan | Pamela | Jenaro |
|--------|------|--------|--------|
| **S14 (días 1–2)** | Contrato §3 congelado · `observabilidad.py` y `span` | Contrato · variantes de proyectos · borrador de `gold.json` | Contrato · mock `metricas_ejemplo.jsonl` · boceto del dashboard |
| **S14 (resto)** | Instrumentar LLM y fases · `correr_escenarios.py` · **corrida de línea base** | `metricas.py` (P, C, E) · reunión gold | Dashboard contra mocks: KPIs, latencia y traza en cascada |
| **S15** | Endpoints `/metricas` · psutil · métricas L y R · tests | `analizar_trazas.py` · `hallazgos.md` · correcciones 1–3 | `privacidad.py` · minimización de logs · defensa ante inyección · retención y supresión |
| **S16** | **Corrida final** · propuesta IE7 · secciones 1, 2 y 6 del informe | Antes y después · secciones 2 y 3 · edición del informe | Dashboard contra la API real · capturas · ficha de uso responsable · sección 4–5 |
| **S16 (cierre)** | Ensayo de la presentación con preguntas cruzadas (los tres) | | |
| **S17** | **Presentación** | | |
| **S18** | Ajustes según el feedback · reflexiones individuales · **entrega del informe y el repositorio** (los tres) | | |

Nadie espera a nadie después del día 1: Jenaro avanza con mocks, Pamela con los runs que ya existen en `outputs/runs/` y Juan en modo simulado.

---

## 10. Flujo de trabajo Git

- Ramas: `feat/obs-telemetria` (Juan), `feat/obs-metricas` (Pamela) y `feat/obs-dashboard-seguridad` (Jenaro).
- Revisión cruzada, igual que en la EP2: Juan revisa a Pamela, Pamela revisa a Jenaro y Jenaro revisa a Juan.
- Cambiar el contrato de §3 o `models.py` requiere el visto bueno de los tres.
- Nunca se commitean `.env`, keys ni `outputs/`. Las evidencias que vayan al informe se copian a `docs/observabilidad/`.

## 11. Definición de "terminado"

- [ ] Al menos 3 métricas por cada grupo de la rúbrica (precisión, consistencia, errores, latencia y recursos), medidas en ≥ 5 escenarios distintos.
- [ ] Al menos 3 hallazgos de las trazas con causa raíz y una corrección medida antes y después.
- [ ] Dashboard con filtros, semáforo, traza en cascada y comparación antes/después.
- [ ] Controles de privacidad implementados y con tests (PII, logs, inyección, retención).
- [ ] `pytest -q` pasa sin keys ni red.
- [ ] README con instrucciones para reproducir los escenarios y abrir el dashboard.
- [ ] Informe ≤ 5 páginas con capturas, APA, declaración de uso de IA y 3 reflexiones individuales escritas sin IA.

## 12. Referencias sugeridas (APA, a completar)

- Biblioteca del Congreso Nacional de Chile. (2024). *Ley N° 21.719*. https://www.bcn.cl/leychile
- National Institute of Standards and Technology. (2023). *Artificial Intelligence Risk Management Framework (AI RMF 1.0)* (NIST AI 100-1). https://doi.org/10.6028/NIST.AI.100-1
- OWASP Foundation. (2025). *OWASP Top 10 for Large Language Model Applications*. https://genai.owasp.org
- OpenTelemetry. (2025). *Semantic conventions for generative AI systems*. https://opentelemetry.io/docs/specs/semconv/gen-ai/
- Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (2016). *Site reliability engineering: How Google runs production systems*. O'Reilly Media.

> **Uso de IA:** este plan se armó con apoyo de Claude Code (Claude Opus 5.5) y hay que declararlo en el informe. Las conclusiones, las justificaciones técnicas y las reflexiones individuales las redacta el equipo sin IA, como exige la rúbrica.
