import streamlit as st
from frontend.ui import cliente, descargas, mostrar_informe, seleccionar_run

st.header("Decisiones y resultados")
run_id = seleccionar_run(solo_finalizados=True, key="report_run")
if run_id is not None:
    informe = cliente().obtener_informe(run_id)
    st.subheader(informe["proyecto"]["nombre"])
    st.write(informe["proyecto"]["objetivo"])
    descargas(run_id, informe)
    mostrar_informe(informe)
