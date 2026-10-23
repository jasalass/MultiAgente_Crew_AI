import streamlit as st
from frontend.ui import cliente, formatear_fecha, tarjetas_decisiones, veredicto_viabilidad

st.header("Historial / Comparar")
api = cliente()
runs = api.listar_runs()
if not runs:
    st.info("Todavía no hay análisis guardados.")
    st.stop()
filas = [{"run_id": r["run_id"], "proyecto": r["config"]["proyecto"]["nombre"],
          "estado": r["estado"], "modo": r["config"]["asignacion_modelos"],
          "ronda": r["ronda_actual"], "creado": formatear_fecha(r["creado"])} for r in runs]
st.dataframe(filas, hide_index=True, width="stretch")
finalizados = [r for r in runs if r["estado"] == "finalizado"]
if len(finalizados) < 2:
    st.info("Finaliza al menos dos análisis para compararlos. Puedes contrastar uno mono y uno auto del mismo proyecto.")
    st.stop()
ids = [r["run_id"] for r in finalizados]
etiquetas = {r["run_id"]: f"{r['config']['proyecto']['nombre']} · {r['config']['asignacion_modelos']} · {r['run_id']}" for r in finalizados}
a, b = st.columns(2)
primero = a.selectbox("Primer análisis", ids, format_func=etiquetas.get)
segundo = b.selectbox("Segundo análisis", [i for i in ids if i != primero], format_func=etiquetas.get)
informes = [api.obtener_informe(i) for i in (primero, segundo)]
if informes[0]["proyecto"] != informes[1]["proyecto"]:
    st.warning("Los proyectos de entrada son distintos. Las diferencias no se pueden atribuir solo al modo de modelos.")
if informes[0]["cuestionario"] != informes[1]["cuestionario"]:
    st.warning("Los cuestionarios son distintos. Revisa las alternativas y preguntas antes de interpretar las diferencias.")
for columna, run_id, informe in zip((a, b), (primero, segundo), informes):
    with columna:
        estado = next(r for r in finalizados if r["run_id"] == run_id)
        st.subheader(informe["proyecto"]["nombre"])
        st.caption(f"Modo: {estado['config']['asignacion_modelos']} · panel: {', '.join(informe['panel'])}")
        veredicto_viabilidad(informe)
        rondas = informe.get("rondas", [])
        st.metric("Rondas ejecutadas", len(rondas))
        st.metric("Consenso final", f"{rondas[-1]['porcentaje_consenso']:.0%}" if rondas else "Sin datos")
        tarjetas_decisiones(informe)
        st.write("Evaluación por dimensión")
        st.dataframe([{"dimensión": k, "mediana": v} for k, v in informe.get("evaluacion_por_dimension", {}).items()], hide_index=True)
mapas = [{d["titulo"]: d for d in i["decisiones"]} for i in informes]
comparacion = []
for titulo in sorted(set(mapas[0]) | set(mapas[1])):
    d1, d2 = mapas[0].get(titulo), mapas[1].get(titulo)
    comparacion.append({"decisión": titulo,
                        "primero": d1.get("alternativa_recomendada") if d1 else "No evaluada",
                        "segundo": d2.get("alternativa_recomendada") if d2 else "No evaluada",
                        "cambia": "No comparable" if not d1 or not d2 else "Sí" if (d1["estado"], d1["alternativa_recomendada"]) != (d2["estado"], d2["alternativa_recomendada"]) else "No"})
st.subheader("Cambios en decisiones")
st.dataframe(comparacion, hide_index=True, width="stretch")
