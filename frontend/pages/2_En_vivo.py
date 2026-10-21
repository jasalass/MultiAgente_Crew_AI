import streamlit as st
from frontend.api_client import ApiError
from frontend.ui import cliente, formatear_fecha, seleccionar_run

st.header("Ejecución en vivo")
run_id = seleccionar_run(key="live_run")
if run_id is None:
    st.stop()
auditor = st.toggle("Modo auditor", value=False,
                    help="Muestra el rol y el modelo. Los expertos reciben únicamente el feedback anónimo del motor.")
api = cliente()
activo = api.obtener_run(run_id)["estado"] in {"en_cola", "ejecutando"}


@st.fragment(run_every="2s" if activo else None)
def seguimiento():
    try:
        clave = f"eventos_{run_id}"
        previos = st.session_state.get(clave, [])
        desde = max((e["seq"] for e in previos), default=0)
        nuevos = api.obtener_eventos(run_id, desde=desde)
        eventos = {e["seq"]: e for e in previos + nuevos}
        st.session_state[clave] = ordenados = [eventos[k] for k in sorted(eventos)]
        estado = api.obtener_run(run_id)
        if activo and estado["estado"] not in {"en_cola", "ejecutando"}:
            st.rerun()  # Reconstruye el fragmento sin temporizador al finalizar.
        a, b, c = st.columns(3)
        a.metric("Estado", estado["estado"])
        b.metric("Ronda actual", estado["ronda_actual"])
        c.metric("Eventos recibidos", len(ordenados))
        if estado["estado"] in {"en_cola", "ejecutando"}:
            st.progress(min(estado["ronda_actual"] / (estado["config"]["max_rondas"] + 1), .99))
            if st.button("Cancelar análisis", key=f"cancel_{run_id}"):
                api.cancelar_run(run_id)
                st.info("Cancelación solicitada; se aplicará al terminar el paso en curso.")
                st.rerun()
        elif estado["estado"] == "finalizado":
            st.success("Análisis finalizado. El informe está disponible en Decisiones y resultados.")
            if st.button("Ver decisiones", key=f"results_{run_id}"):
                st.session_state.active_run = run_id
                st.switch_page("pages/3_Decisiones.py")
        elif estado["estado"] == "cancelado":
            st.warning("Análisis cancelado.")
        elif estado["estado"] == "error":
            st.error("La ejecución terminó con un error. Consulta la línea de tiempo.")
        st.subheader("Línea de tiempo")
        for evento in ordenados:
            etiqueta = f"{evento['seq']} · {evento['tipo'].replace('_', ' ')}"
            if evento.get("ronda"):
                etiqueta += f" · ronda {evento['ronda']}"
            with st.expander(etiqueta, expanded=evento["tipo"] in {"respuesta_experto", "decision_moderador", "error"}):
                st.caption(formatear_fecha(evento["timestamp"]))
                payload = evento.get("payload", {})
                if evento["tipo"] == "respuesta_experto":
                    respuesta = payload.get("respuesta", payload)
                    st.write(f"**{respuesta.get('experto_id', 'Experto anónimo')}**")
                    if auditor:
                        st.caption(f"Rol: {respuesta.get('rol', 'sin dato')} · Modelo: {respuesta.get('modelo', 'sin dato')}")
                    st.dataframe(respuesta.get("respuestas", []), hide_index=True)
                    for riesgo in respuesta.get("riesgos_detectados", []):
                        st.write(f"Riesgo: {riesgo}")
                elif evento["tipo"] in {"panel_confirmado", "cambio_modelo"} and not auditor:
                    st.write("Panel confirmado." if evento["tipo"] == "panel_confirmado" else "Se registró un cambio de modelo. Activa modo auditor para los detalles.")
                elif evento["tipo"] == "decision_moderador":
                    st.write(payload.get("motivo", payload.get("decision", "Decisión registrada.")))
                    if "continuar" in payload:
                        st.caption("Continúa a otra ronda" if payload["continuar"] else "Cierre de rondas")
                elif evento["tipo"] == "error":
                    st.error(str(payload.get("mensaje", payload.get("error", "Error en el motor."))))
                elif auditor:
                    st.json(payload)
                else:
                    st.write("Paso registrado.")
    except ApiError as error:
        st.error(str(error))


seguimiento()
