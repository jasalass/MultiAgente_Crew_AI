"""Ejecutar desde el repositorio: streamlit run frontend/app.py."""
from pathlib import Path
import os
import sys

# Streamlit puede añadir únicamente frontend/ a sys.path al lanzar por ruta.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import streamlit as st
from frontend.api_client import ApiError
from frontend.ui import cliente

st.set_page_config(page_title="Panel Delphi · Decisiones TI", page_icon="◈", layout="wide")
st.title("Panel Delphi")
st.caption("Decisiones de proyecto con un panel de expertos TI")
try:
    api = cliente()
except ApiError as error:
    st.error(str(error))
    st.stop()
with st.sidebar:
    if api.use_mocks:
        st.info("DEMO · Datos simulados. No se consulta ningún LLM.")
    else:
        st.caption(f"API: {os.getenv('API_BASE_URL', 'http://localhost:8000')}")
    st.caption("Jenaro · Panel, sesgo y frontend")

paginas = [
    st.Page("pages/1_Nuevo.py", title="Nuevo análisis", icon="📝", default=True),
    st.Page("pages/2_En_vivo.py", title="Ejecución en vivo", icon="⏳"),
    st.Page("pages/3_Decisiones.py", title="Decisiones y resultados", icon="📊"),
    st.Page("pages/4_Historial.py", title="Historial / Comparar", icon="📚"),
]
try:
    st.navigation(paginas).run()
except ApiError as error:
    st.error(str(error))
    st.caption("Revisa que la API esté disponible o inicia la demo con USE_MOCKS=true.")
