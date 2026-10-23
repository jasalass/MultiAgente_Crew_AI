# Validación de Jenaro — 23 de octubre de 2026

Revisión posterior a incorporar `main` hasta `4c973b6` en `feat/panel-y-frontend`. Se revisaron las tareas de Jenaro del README §5 y su integración con los contratos, API y motor nuevos. No se modificaron los contratos compartidos ni se llamaron proveedores externos.

## Correcciones

- La demo del frontend incorpora `VIA-E1` y calcula el veredicto de viabilidad desde sus respuestas y estadísticas. El informe JSON y la descarga Markdown lo incluyen.
- El parser de la demo ignora comentarios de la plantilla y viñetas vacías, conservando el documento original; se verifica su equivalencia con el parser de la API para los tres proyectos canónicos.
- En Nuevo análisis se priorizan los ejemplos de `data/proyectos/`. Las pantallas En vivo y Comparar muestran correctamente el cuestionario del motor, datos antiguos del mock y el veredicto de viabilidad.
- El experimento utiliza por defecto los tres archivos canónicos. Se puede fijar `--modelo-mono`; las exportaciones identifican de forma destacada una **API SIMULADA**, además del mock local del frontend.
- Los IDs estructurados con cero inicial o alternativas en mayúscula se aceptan tanto al construir prompts como al agregar respuestas. Los IDs fuera del formato se rechazan antes de consultar expertos.
- Los fixtures del motor usan un endpoint compatible explícito, igual que ModelPool. Esto permite probar modelos ficticios con CrewAI 1.15.28 sin añadir la dependencia opcional LiteLLM. La construcción del LLM de producción con un nombre de modelo ajeno al catálogo nativo tiene su propia regresión, sin peticiones externas.

## Pruebas ejecutadas

La suite incluye las pruebas existentes y regresiones de estos fallos. La prueba nueva `tests/test_integracion_frontend.py` levanta FastAPI en un puerto local efímero y recorre la ruta completa con el cliente HTTP real y el motor Delphi; solo las respuestas LLM son ficticias.

**Resultado final: 175 pruebas y 32 subpruebas aprobadas.** Las 182 advertencias corresponden a deprecaciones internas de CrewAI, sin fallos. La comprobación de dependencias también pasó: 150 paquetes instalados compatibles.

Se comprobaron:

- Catálogo, sugerencia del panel, prompts, independencia, síntesis y medición de sesgo.
- Asignación auto/manual/mono/seed, errores y cambios de modelo mediante dobles de prueba.
- Tres proyectos canónicos procesados por HTTP, eventos sin duplicados y cursor exclusivo.
- Informes válidos contra `InformeDelphi`, Markdown, ADR ZIP y recuperación desde una nueva instancia del almacén en disco.
- Rechazo de configuraciones inválidas y cancelación sin producir un informe final.
- Streamlit conectado a la API: crear, seguir rondas, modo auditor, veredicto, tres gráficos, tres descargas y comparación de análisis.

Reproducir la suite:

```powershell
.venv\Scripts\python.exe -m pytest -q --tb=short --junitxml=outputs/validacion_jenaro/pruebas.xml
```

El experimento adicional completó **seis ejecuciones HTTP**: tres proyectos × mono/auto. El control utilizó `simulado-b`; el panel auto utilizó `simulado-a`, `simulado-b` y `simulado-c`. Todos terminaron en tres rondas. El resultado describe exclusivamente la simulación y no demuestra diferencias entre modelos reales.

Reproducirlo con la API iniciada en modo simulado:

```powershell
$env:DELPHI_SIMULADO = "true"
$env:DELPHI_PAUSA_SIMULADO = "0"
.venv\Scripts\python.exe -m uvicorn backend.api.main:app
```

En otra terminal, desde la misma carpeta:

```powershell
.venv\Scripts\python.exe -m scripts.experimento_sesgo --api-url http://localhost:8000 --modelo-mono simulado-b --timeout 60 --intervalo 0.1 --salida outputs/validacion_jenaro/experimento_api
```

Evidencia local (excluida de Git):

- `outputs/validacion_jenaro/pruebas.xml`: resultado de la suite.
- `outputs/validacion_jenaro/experimento_api/comparacion.md` y `.csv`: tabla de los tres proyectos, identificada como API SIMULADA.
- `outputs/validacion_jenaro/experimento_api/ejecuciones.json`: configuraciones e informes completos.
- `outputs/validacion_jenaro/runs/`: persistencia de los seis análisis HTTP.

## Pendientes

1. Configurar las credenciales y verificar de nuevo el flujo con los modelos reales elegidos por el equipo. `ModelPool.desde_env().listar_modelos()` devolvió cero modelos configurados en esta copia.
2. Ejecutar el control real mono/auto, revisar comparabilidad de cuestionarios y agregar los resultados empíricos al README. La tabla simulada no sustituye ese experimento.
3. Revisar entre los tres si las decisiones son razonables y si el proyecto débil recibe una evaluación adecuada. Los LLM ficticios del backend no evalúan semánticamente la viabilidad de cada proyecto.
4. Preparar y ensayar la demo y presentación. Los acuerdos y credenciales del Día 1 que siguen sin marcar en el README requieren confirmación del equipo; no pueden verificarse con el código.

La evidencia detallada de las pruebas se conserva localmente en `outputs/`, excluida de Git. Este informe documenta la validación de la integración y no publica una conclusión experimental sobre modelos reales.
