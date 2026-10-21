"""Estado compartido y presentación de informes, sin ejecutar el motor."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from frontend.api_client import ApiClient
from frontend.charts import convergencia, matriz_riesgos, radar


def formatear_fecha(valor):
    if not valor:
        return "—"
    fecha = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    if fecha.tzinfo is None:
        return str(valor)
    return fecha.astimezone(ZoneInfo("America/Santiago")).strftime("%d/%m/%Y %H:%M:%S %Z")


def cliente():
    if "api_client" not in st.session_state:
        st.session_state.api_client = ApiClient()
    return st.session_state.api_client


def seleccionar_run(solo_finalizados=False, key="run_selector"):
    runs = cliente().listar_runs()
    if solo_finalizados:
        runs = [r for r in runs if r["estado"] == "finalizado"]
    if not runs:
        st.info("Todavía no hay análisis finalizados." if solo_finalizados else "Crea un análisis para comenzar.")
        return None
    opciones = [r["run_id"] for r in runs]
    etiquetas = {r["run_id"]: f"{r['config']['proyecto']['nombre']} · {r['estado']} · {r['run_id']}" for r in runs}
    activo = st.session_state.get("active_run")
    indice = opciones.index(activo) if activo in opciones else 0
    if activo in opciones and st.session_state.get(f"{key}_active") != activo:
        st.session_state[key] = activo
        st.session_state[f"{key}_active"] = activo
    elif st.session_state.get(key) not in opciones:
        st.session_state[key] = opciones[indice]
    return st.selectbox("Análisis", opciones, index=indice, format_func=etiquetas.get, key=key)


def tarjetas_decisiones(informe):
    estados = {"firme": "✅ Firme", "condicionada": "⚠️ Condicionada", "abierta": "❓ Abierta"}
    for decision in informe.get("decisiones", []):
        with st.container(border=True):
            st.subheader(decision["titulo"])
            st.markdown(f"**{estados[decision['estado']]}** · {decision.get('alternativa_recomendada') or 'Pendiente de resolver'}")
            a, b, c = st.columns(3)
            a.metric("Mediana", f"{decision['mediana']:.1f}")
            b.metric("IQR", f"{decision['iqr']:.1f}")
            c.metric("Margen sobre segunda", f"{decision['margen_vs_segunda']:.1f}")
            for condicion in decision.get("condiciones", []):
                st.write(f"• {condicion}")
            if decision.get("poc_sugerida"):
                st.info(f"Prueba de concepto: {decision['poc_sugerida']}")


def mostrar_informe(informe):
    for aviso in informe.get("avisos", []):
        st.warning(aviso)
    tarjetas_decisiones(informe)
    decisiones = informe.get("cuestionario", {}).get("decisiones", [])
    if decisiones:
        seleccion = st.selectbox("Convergencia de una decisión", decisiones,
                                format_func=lambda d: d["titulo"])
        st.plotly_chart(convergencia(informe, seleccion["id"]), width="stretch")
        st.caption("Las barras muestran Q1–Q3; los puntos, la mediana. Escala Likert 1–5.")
    izquierda, derecha = st.columns(2)
    with izquierda:
        st.subheader("Evaluación por dimensión")
        st.plotly_chart(radar(informe), width="stretch")
    with derecha:
        st.subheader("Matriz de riesgos")
        st.plotly_chart(matriz_riesgos(informe), width="stretch")
    for i, riesgo in enumerate(informe.get("riesgos", []), 1):
        with st.expander(f"R{i} · {riesgo['descripcion']}"):
            st.write(f"{riesgo['dimension']} · probabilidad {riesgo['probabilidad']}/5 · impacto {riesgo['impacto']}/5")
            st.write(riesgo["mitigacion"])
    st.subheader("Argumentos y disensos")
    preguntas = {i["id"]: i.get("alternativa") or i["pregunta"] for i in informe.get("cuestionario", {}).get("items", [])}
    rondas = informe.get("rondas", [])
    if rondas:
        for item in rondas[-1]["estadisticas"]:
            with st.expander(preguntas.get(item["item_id"], item["item_id"])):
                a, b = st.columns(2)
                a.write("A favor")
                for argumento in item.get("argumentos_a_favor", []):
                    a.write(f"• {argumento}")
                b.write("En contra")
                for argumento in item.get("argumentos_en_contra", []):
                    b.write(f"• {argumento}")
    for texto in informe.get("disensos", []):
        st.write(f"• {texto}")
    st.subheader("Sesgo por modelo")
    st.caption("Estas diferencias describen las puntuaciones del panel; la asignación de roles también puede influir.")
    sesgos = informe.get("sesgo_por_modelo", [])
    if sesgos:
        st.dataframe([{k: v for k, v in s.items() if k != "preferencias"} for s in sesgos], hide_index=True)
        for sesgo in sesgos:
            with st.expander(f"Preferencias · {sesgo['modelo']}"):
                st.dataframe([{"alternativa": k, "desviación respecto del grupo": v}
                              for k, v in sesgo.get("preferencias", {}).items()], hide_index=True)
    for recomendacion in informe.get("recomendaciones", []):
        st.write(f"• {recomendacion}")


def descargas(run_id, informe):
    api = cliente()
    a, b, c = st.columns(3)
    a.download_button("Descargar informe.md", api.obtener_informe(run_id, "md"),
                      file_name=f"{run_id}-informe.md", mime="text/markdown")
    b.download_button("Descargar informe.json", json.dumps(informe, ensure_ascii=False, indent=2),
                      file_name=f"{run_id}-informe.json", mime="application/json")
    c.download_button("Descargar ADR.zip", api.descargar_adrs(run_id),
                      file_name=f"{run_id}-adr.zip", mime="application/zip")
