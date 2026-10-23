# Base de conocimiento: Ley 21.719

`ley_21719_chunks.json` son los **140 fragmentos de la Ley 21.719** (protección de datos personales, Chile) que produjo la
**Evaluación Parcial 1** del equipo (repositorio `INGENIERIA_DE_SOLUCIONES_CON-INTELIGENCIA-ARTIFICIAL_012V_OLS`,
`etapa1_datos/data/processed/chunks.json`). La estrategia de extracción, limpieza y fragmentación por artículo está
justificada en `etapa1_datos/justificacion_chunking.md` de ese repositorio. Fuente: Biblioteca del Congreso Nacional (leychile.cl).

`indice_ley_21719.json` + `.npz` es el índice vectorial que construye `python -m scripts.indexar_conocimiento`
(embeddings `gemini-embedding-001`). La EP1 guardaba los vectores en Postgres + pgvector con `mistral-embed`; aquí se guardan
en archivo para que la demo no dependa de Docker.
