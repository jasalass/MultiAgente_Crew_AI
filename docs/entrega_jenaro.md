# Entrega de Jenaro: panel de expertos, sesgo y frontend

Implementación local en `feat/panel-y-frontend`, basada en los contratos del README §4. No se creó ni modificó `backend/delphi/models.py`: ese archivo sigue siendo responsabilidad compartida. La API, ModelPool, estadísticas del motor y orquestación real corresponden a Juan y Pamela.

## Probar la demo

Desde PowerShell, en la raíz del repositorio:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-jenaro.txt
$env:USE_MOCKS = "true"
.venv\Scripts\python.exe -m streamlit run frontend/app.py
```

Abrir http://localhost:8501. La demo no necesita keys ni hace llamadas a LLM. Las dependencias ya están instaladas en el entorno `.venv` de esta copia.

Recorrido para presentar:

1. En **Nuevo análisis**, seleccionar un ejemplo, completar o importar Markdown, ajustar el panel y elegir la asignación de modelos. Los cinco expertos del núcleo son obligatorios y hay un máximo de dos opcionales.
2. Pulsar **Iniciar análisis**. En **Ejecución en vivo** se consultan eventos cada dos segundos, sin duplicados. El **modo auditor** muestra rol y modelo; también se puede cancelar.
3. En **Decisiones y resultados**, revisar decisiones firmes, condicionadas o abiertas, convergencia con Q1–Q3, radar, riesgos, argumentos y sesgo. Descargar Markdown, JSON o ADR ZIP.
4. Repetir el mismo proyecto en modo `mono`, finalizarlo y comparar ambos en **Historial / Comparar**.

Hay un análisis finalizado de clínicas precargado. Los runs simulados pertenecen a la sesión del navegador y se reinician al abrir otra sesión o reiniciar el servidor. Los resultados son ficticios, incluso cuando se cambia el proyecto; sirven para validar el flujo y los contratos. El cliente no simula un razonamiento real ni permite sacar conclusiones sobre familias de modelos.

## Archivos y responsabilidades

| Archivo | Qué aporta |
|---|---|
| `backend/delphi/experts.py` | Diez perfiles con prioridades, sesgos y preguntas explícitas. Sugerencia determinista de núcleo + opcionales con motivos. |
| `backend/delphi/prompts.py` | Prompts de primera ronda y posteriores; respuesta previa propia, feedback anónimo, justificación de outliers y validación del contexto. |
| `backend/delphi/anonymizer.py` | Agrupación temática de argumentos por ítem y postura. `AnonymizerTool` es un `BaseTool` cuando CrewAI está instalado. |
| `backend/delphi/bias.py` | Medias y preferencias por modelo respecto de la mediana del mismo ítem, sin duplicar rondas. |
| `scripts/experimento_sesgo.py` | Control mono/auto sobre tres proyectos, espera acotada y exportaciones CSV, Markdown y JSON. |
| `frontend/api_client.py` | Cliente HTTP del contrato §4.2 y selección de modo demo. |
| `frontend/mocks/` | Tres proyectos y ejecuciones completas con cola, cancelación, eventos, informe y ADR. |
| `frontend/app.py`, `frontend/pages/` | Las cuatro páginas de Streamlit. |
| `frontend/charts.py`, `ui.py`, `validation.py` | Gráficos, presentación, estado de sesión y validación del formulario. |
| `tests/` | Cálculos, aislamiento, HTTP, contratos del README y recorrido de interfaz con AppTest. |

## Integrar con Juan y Pamela

El frontend carga `.env` si existe. Usar las variables de `.env.frontend.example` en ese archivo o definirlas en PowerShell:

```powershell
$env:USE_MOCKS = "false"
$env:API_BASE_URL = "http://localhost:8000"
.venv\Scripts\python.exe -m streamlit run frontend/app.py
```

Esto exige que la API de Juan esté iniciada con los endpoints del README. `POST /proyectos/parsear` envía una cadena JSON con el documento Markdown completo. Las sugerencias son una lista de `{id, motivo}`. El cliente trata `desde` como cursor exclusivo: recibe los eventos con `seq > desde`.

Puntos de entrada del motor:

```python
from backend.delphi.experts import listar_expertos, get_experto, sugerir_panel
from backend.delphi.prompts import construir_prompt_ronda_1, construir_prompt_ronda_k
from backend.delphi.anonymizer import AnonymizerTool, sintetizar_argumentos
from backend.delphi.bias import calcular_sesgo

panel = sugerir_panel(proyecto)  # [{"id": "arquitectura", "motivo": "..."}, ...]
perfil = get_experto("arquitectura")  # campos del contrato Experto
prompt = construir_prompt_ronda_1(perfil, proyecto, cuestionario)
feedback = sintetizar_argumentos(respuestas_de_una_ronda, cuestionario)
sesgos = calcular_sesgo(todas_las_respuestas, cuestionario)
```

Las funciones reciben diccionarios o instancias Pydantic y devuelven diccionarios con los campos acordados. Juan/Pamela pueden convertirlos con `Experto.model_validate(...)` y `SesgoModelo.model_validate(...)` cuando estén disponibles los modelos compartidos.

Para una ronda posterior:

```python
prompt = construir_prompt_ronda_k(
    perfil, proyecto, cuestionario,
    respuesta_anterior=respuesta_propia,
    feedback=resumen_ronda_anterior,
    ronda=2,
)
```

El JSON pedido al LLM contiene **solo** `respuestas` y `riesgos_detectados`. El motor agrega `experto_id`, `rol`, `modelo` y `ronda` antes de validar `RespuestaExperto`; el LLM no genera metadatos de auditoría. La respuesta propia debe cubrir todos los ítems y pertenecer al mismo rol y a la ronda anterior. El feedback requiere estadísticas completas de todos los ítems.

La herramienta anónima produce una cadena JSON de resúmenes. Pamela debe unirla por `item_id` a mediana, Q1, Q3, IQR y consenso calculados por `stats.py`. No se pasan a otro experto las respuestas de sus pares ni sus metadatos. El motor también debe crear las tareas sin `context`, desactivar memoria y delegación de los workers y conservar los originales solo para auditoría. El prompt y `guard_independencia` no reemplazan ese aislamiento.

La demo funciona sin CrewAI. La ruta de `BaseTool` real se verificó en un entorno aislado con **CrewAI 1.15.28**. Para usar esa herramienta en el motor, instalar CrewAI junto con las dependencias de integración que acuerde el equipo. Referencia de la API: [herramientas personalizadas de CrewAI](https://docs.crewai.com/en/learn/create-custom-tools).

## Experimento de control

Prueba funcional con seis análisis simulados:

```powershell
.venv\Scripts\python.exe -m scripts.experimento_sesgo --mock
```

Genera en `outputs/experimento_sesgo/` la tabla `comparacion.md`, `comparacion.csv`, los informes completos en `ejecuciones.json` y evidencia parcial ante fallos. Todos los archivos indican que son simulados. No son resultados empíricos que deban incorporarse como conclusiones del README.

Cuando la API, el motor y las credenciales estén configurados:

```powershell
.venv\Scripts\python.exe -m scripts.experimento_sesgo --api-url http://localhost:8000 --timeout 1800
# O bien usar los tres archivos de data/proyectos/:
.venv\Scripts\python.exe -m scripts.experimento_sesgo --api-url http://localhost:8000 --proyectos data/proyectos/clinica_reservas.md data/proyectos/migracion_erp.md data/proyectos/marketplace_ia.md
```

La segunda orden usa los tres proyectos de `data/proyectos/`. Se compara IQR medio de la primera ronda, primera ronda con consenso global, alternativas recomendadas y estados. Un cierre por estabilidad no se cuenta como consenso. Se informa si los cuestionarios difieren y si hay decisiones sin pareja. Se conserva el mismo proyecto y configuración de panel entre ambos modos.

## Pruebas y límites

```powershell
.venv\Scripts\python.exe -m pytest -q
```

`test_contracts.py` compila en memoria el bloque de contratos del README para validar catálogo, proyectos, estados, eventos e informes sin crear una segunda definición de `models.py`. AppTest recorre creación, polling, resultados, descargas, gráficos, auditoría y selección de un análisis recién creado. Las pruebas HTTP interceptan las solicitudes; no requieren un servidor externo.

La sugerencia de panel usa heurísticas y se puede editar. Maneja exclusiones simples como “sin IA”; las negaciones complejas pueden requerir revisión. La síntesis anónima usa vocabulario técnico cerrado y plantillas neutrales: evita reenviar citas y marcas de estilo, pero pierde cifras, condiciones y temas no reconocidos. Un panel pequeño aún puede permitir inferir una postura singular.

Las medidas de sesgo son descriptivas. Se toma el último voto de cada experto/ítem, incluso si cambió de modelo, y se compara con la mediana del mismo ítem. Para estudiar un efecto del modelo se necesitan repeticiones con roles/asignaciones rotadas; una sola comparación no separa causalmente esos factores.

Queda pendiente la integración de extremo a extremo con API/motor reales, ajustar prompts con modelos reales, ejecutar el control real y revisar los resultados con el equipo. Las claves personales van únicamente en `.env`; no se necesitan para presentar esta demo.
