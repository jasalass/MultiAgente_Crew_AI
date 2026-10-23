import streamlit as st
from frontend.api_client import ApiError
from frontend.ui import cliente, formatear_fecha, seleccionar_run, sin_parpadeo

ESTADOS = {"en_cola": "⏳ En cola", "ejecutando": "▶️ Ejecutando", "finalizado": "✅ Finalizado",
           "cancelado": "⏹️ Cancelado", "error": "⛔ Error"}
MOTIVOS = {"min_rondas": "se exige un mínimo de rondas", "consenso": "se alcanzó el consenso",
           "estabilidad": "las opiniones dejaron de cambiar", "max_rondas": "se llegó al máximo de rondas",
           "moderador": "lo decidió el Moderador"}

st.header("Ejecución en vivo")
sin_parpadeo()
run_id = seleccionar_run(key="live_run")
if run_id is None:
    st.stop()
auditor = st.toggle("Modo auditor", value=False,
                    help="Muestra el rol y el modelo. Los expertos reciben únicamente el feedback anónimo del motor.")
api = cliente()
activo = api.obtener_run(run_id)["estado"] in {"en_cola", "ejecutando"}


def _respuesta(evento):
    payload = evento.get("payload", {})
    return payload.get("respuesta", payload)


ICONOS_HERRAMIENTA = {"consultar_ley_21719": "⚖️ Consultó la Ley 21.719", "buscar_analisis_anteriores":
                      "🧠 Buscó en la memoria institucional", "guardar_ficha": "📝 Guardó la ficha"}


def preparacion(eventos, en_curso):
    """Asesor normativo, panel y cuestionario. Abierto solo mientras se preparan."""
    cuestionario = next((e["payload"] for e in eventos if e["tipo"] == "cuestionario_generado"), None)
    panel = next((e["payload"] for e in eventos if e["tipo"] == "panel_confirmado"), {})
    contexto = next((e["payload"] for e in eventos if e["tipo"] == "contexto_preparado"), None)
    if cuestionario:
        etiqueta = "Preparación · ✔ ficha de contexto, panel y cuestionario listos"
    elif contexto:
        etiqueta = "Preparación · ⏳ el Moderador está escribiendo el cuestionario"
    else:
        etiqueta = "Preparación · ⏳ el Asesor normativo consulta la ley y la memoria"
    with st.expander(etiqueta, expanded=en_curso and not cuestionario):
        integrantes = panel.get("panel", panel.get("expertos", []))
        if integrantes:
            st.write("**Panel:** " + ", ".join(integrantes))
            if auditor and panel.get("modelos"):
                st.caption(" · ".join(f"{rol}: {modelo}" for rol, modelo in panel["modelos"].items()))
        if contexto:
            st.write("**Asesor normativo** (agentes con herramientas, antes de la ronda 1):")
            for consulta in contexto.get("consultas", []):
                st.write(f"{ICONOS_HERRAMIENTA.get(consulta['herramienta'], consulta['herramienta'])}: "
                         f"«{consulta['entrada']}»")
                detalle = [f"motivo: {consulta['motivo']}"] if consulta.get("motivo") else []
                if consulta.get("resultados"):
                    detalle.append(f"{consulta.get('modo', '')} → " + " · ".join(consulta["resultados"][:3]))
                if detalle:
                    st.caption(" | ".join(detalle))
            for advertencia in contexto.get("advertencias", []):
                st.warning(advertencia)
            with st.container(height=220):
                st.markdown(contexto.get("ficha", ""))
        if cuestionario:
            for decision in cuestionario.get("decisiones", []):
                st.write(f"**{decision['titulo']}:** " + " · ".join(decision["alternativas"]))
            evaluaciones = [i for i in cuestionario.get("items", []) if i["tipo"] == "evaluacion"]
            st.caption(f"{len(cuestionario.get('items', []))} preguntas: {len(cuestionario.get('decisiones', []))} "
                       f"decisiones con sus alternativas y {len(evaluaciones)} evaluaciones.")


def ronda(numero, eventos, total, es_actual):
    """Una ronda: quién respondió, cuántos faltan y cómo cerró. Abierta solo si está en curso."""
    respuestas = [_respuesta(e) for e in eventos if e["tipo"] == "respuesta_experto"]
    agregada = next((e["payload"] for e in eventos if e["tipo"] == "ronda_agregada"), None)
    decision = next((e["payload"] for e in eventos if e["tipo"] == "decision_moderador"), None)
    cambios = [e["payload"] for e in eventos if e["tipo"] == "cambio_modelo"]
    if agregada:
        etiqueta = f"Ronda {numero} · ✔ terminada · consenso {agregada.get('porcentaje_consenso', 0):.0%}"
    else:
        etiqueta = f"Ronda {numero} · ⏳ en curso · {len(respuestas)} de {total} respuestas"
    with st.expander(etiqueta, expanded=es_actual):
        if respuestas:
            filas = [{"Experto": r.get("experto_id", "—"),
                      **({"Rol": r.get("rol", "—"), "Modelo": r.get("modelo", "—")} if auditor else {}),
                      "Ítems respondidos": len(r.get("respuestas", [])),
                      "Riesgos señalados": len(r.get("riesgos_detectados", []))} for r in respuestas]
            st.dataframe(filas, hide_index=True, width="stretch")
        if not agregada and len(respuestas) < total:
            st.caption(f"⏳ Esperando a {total - len(respuestas)} experto(s). Responden en paralelo, sin ver a los demás.")
        if cambios:
            if auditor:
                for c in cambios:
                    st.caption(f"🔁 {c.get('experto')}: {c.get('anterior')} → {c.get('nuevo')} ({c.get('motivo')})")
            else:
                st.caption(f"🔁 {len(cambios)} cambio(s) de modelo por límites del proveedor. Activa el modo auditor para verlos.")
        if respuestas:
            ids = [r.get("experto_id", "—") for r in respuestas]
            elegido = st.selectbox("Ver las respuestas de", ids, key=f"ver_{run_id}_{numero}")
            detalle = respuestas[ids.index(elegido)]
            if auditor:
                st.caption(f"Rol: {detalle.get('rol', 'sin dato')} · Modelo: {detalle.get('modelo', 'sin dato')}")
            st.dataframe(detalle.get("respuestas", []), hide_index=True, width="stretch")
            for riesgo in detalle.get("riesgos_detectados", []):
                st.write(f"• Riesgo: {riesgo}")
        if decision:
            motivo = MOTIVOS.get(decision.get("motivo"), decision.get("motivo", ""))
            if decision.get("continuar"):
                st.info(f"Continúa a la ronda {numero + 1}: {motivo}.")
            else:
                st.success(f"Se cierran las rondas: {motivo}.")


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
        en_curso = estado["estado"] in {"en_cola", "ejecutando"}
        total = len(estado["config"]["expertos"])
        maximo = estado["config"]["max_rondas"]
        rondas = sorted({e["ronda"] for e in ordenados if e.get("ronda")})
        actual = rondas[-1] if rondas else 0
        respondidas = sum(1 for e in ordenados if e["tipo"] == "respuesta_experto" and e.get("ronda") == actual)

        a, b, c = st.columns(3)
        a.metric("Estado", ESTADOS.get(estado["estado"], estado["estado"]))
        b.metric("Ronda", f"{actual} de {maximo}" if actual else "—")
        c.metric("Respuestas de la ronda", f"{respondidas} de {total}" if actual else "—")
        if en_curso:
            st.progress(min(((actual - 1 if actual else 0) + respondidas / total) / maximo, .99))
            if st.button("Cancelar análisis", key=f"cancel_{run_id}"):
                api.cancelar_run(run_id)
                st.info("Cancelación solicitada; se aplicará al terminar el paso en curso.")
                st.rerun()

        preparacion(ordenados, en_curso)
        for numero in rondas:
            ronda(numero, [e for e in ordenados if e.get("ronda") == numero], total,
                  es_actual=en_curso and numero == actual)

        if estado["estado"] == "finalizado":
            st.success(f"Análisis finalizado ({formatear_fecha(estado.get('finalizado'))}). "
                       "El veredicto y el informe están en Decisiones y resultados.")
            if st.button("Ver decisiones", key=f"results_{run_id}"):
                st.session_state.active_run = run_id
                st.switch_page("pages/3_Decisiones.py")
        elif estado["estado"] == "cancelado":
            st.warning("Análisis cancelado.")
        elif estado["estado"] == "error":
            mensaje = next((e["payload"].get("mensaje") for e in reversed(ordenados) if e["tipo"] == "error"), None)
            st.error(f"La ejecución terminó con un error: {mensaje or 'sin detalle'}")
    except ApiError as error:
        st.error(str(error))


seguimiento()
