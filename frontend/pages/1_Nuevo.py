from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import streamlit as st
from frontend.mocks import ejemplos_proyectos
from frontend.ui import cliente
from frontend.validation import CORE, proyecto_a_markdown, validar_config

st.header("Nuevo análisis")
api = cliente()
catalogo = api.listar_expertos()
modelos = api.listar_modelos()
fuente = st.radio("Origen del proyecto", ["Ejemplo", "Formulario", "Archivo Markdown"], horizontal=True)
base = {"nombre": "", "objetivo": "", "usuarios_volumen": "", "equipo": "", "texto_original": ""}
identificador = "formulario"
if fuente == "Ejemplo":
    opciones = {}
    carpeta = Path(__file__).resolve().parents[2] / "data" / "proyectos"
    for archivo in sorted(carpeta.glob("*.md")):
        opciones[f"Archivo · {archivo.stem}"] = archivo
    if api.use_mocks or not opciones:
        opciones.update({f"Demo · {p['nombre']}": p for p in ejemplos_proyectos()})
    elegido = st.selectbox("Proyecto de ejemplo", list(opciones))
    dato = opciones[elegido]
    if isinstance(dato, Path):
        texto = dato.read_text(encoding="utf-8")
        cache_key = "parsed_" + sha256(texto.encode()).hexdigest()
        if cache_key not in st.session_state:
            st.session_state[cache_key] = api.parsear_proyecto(texto)
        base = st.session_state[cache_key]
    else:
        base = deepcopy(dato)
    identificador = elegido
elif fuente == "Archivo Markdown":
    archivo = st.file_uploader("Sube la descripción del proyecto", type=["md"])
    if archivo is None:
        st.info("Carga un archivo UTF-8 con las secciones de la plantilla del README.")
        st.stop()
    if archivo.size > 1_000_000:
        st.error("Usa un archivo de hasta 1 MB.")
        st.stop()
    try:
        texto = archivo.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        st.error("El archivo debe estar codificado en UTF-8.")
        st.stop()
    identificador = sha256(texto.encode()).hexdigest()
    if f"parsed_{identificador}" not in st.session_state:
        st.session_state[f"parsed_{identificador}"] = api.parsear_proyecto(texto)
    base = st.session_state[f"parsed_{identificador}"]

# Las claves dependen de la fuente para conservar las ediciones entre reruns.
prefijo = "project_" + sha256(identificador.encode()).hexdigest()[:12]


def campo(etiqueta, nombre, multilinea=True, lista=False):
    valor = base.get(nombre, [] if lista else "")
    if lista:
        valor = "\n".join(valor)
    funcion = st.text_area if multilinea else st.text_input
    texto = funcion(etiqueta, value=valor, key=f"{prefijo}_{nombre}")
    return [linea.strip().lstrip("- ") for linea in texto.splitlines() if linea.strip()] if lista else texto


proyecto = {}
proyecto["nombre"] = campo("Nombre del proyecto", "nombre", multilinea=False)
proyecto["objetivo"] = campo("Objetivo y contexto", "objetivo")
a, b = st.columns(2)
with a:
    proyecto["usuarios_volumen"] = campo("Usuarios y volumen", "usuarios_volumen")
    proyecto["requisitos_funcionales"] = campo("Requisitos funcionales · uno por línea", "requisitos_funcionales", lista=True)
    proyecto["restricciones"] = campo("Restricciones · presupuesto, plazo, normativa", "restricciones", lista=True)
    proyecto["decisiones_a_evaluar"] = campo("Decisiones a evaluar · opcional", "decisiones_a_evaluar", lista=True)
with b:
    proyecto["equipo"] = campo("Equipo y experiencia", "equipo")
    proyecto["requisitos_no_funcionales"] = campo("Requisitos no funcionales · uno por línea", "requisitos_no_funcionales", lista=True)
    proyecto["integraciones"] = campo("Integraciones · una por línea", "integraciones", lista=True)
with st.expander("Texto original y contexto adicional"):
    st.caption("Conserva aquí las secciones y detalles que el formulario no cubre.")
    proyecto["texto_original"] = st.text_area(
        "Documento completo del proyecto", value=base.get("texto_original") or proyecto_a_markdown(proyecto),
        key=f"{prefijo}_texto_original", height=260,
    )

if st.button("Sugerir panel según este proyecto"):
    sugerencias = api.sugerir_panel(proyecto)
    st.session_state[f"{prefijo}_sugerencias"] = sugerencias
    for experto in catalogo:
        st.session_state[f"{prefijo}_panel_{experto['id']}"] = any(s["id"] == experto["id"] for s in sugerencias)
sugerencias = st.session_state.get(f"{prefijo}_sugerencias")
if sugerencias is None:
    sugerencias = api.sugerir_panel(proyecto)
motivos = {s["id"]: s["motivo"] for s in sugerencias}
st.subheader("Panel de expertos")
st.caption("Cinco perfiles del núcleo y hasta dos opcionales. Puedes revisar la sugerencia al editar el proyecto.")
panel = []
columnas = st.columns(2)
for i, experto in enumerate(catalogo):
    with columnas[i % 2]:
        elegido = st.checkbox(experto["nombre"], value=experto["id"] in motivos or experto["id"] in CORE,
                              disabled=experto["id"] in CORE, key=f"{prefijo}_panel_{experto['id']}",
                              help=experto["goal"])
        st.caption(motivos.get(experto["id"], "Opcional: puedes añadirlo según las necesidades del proyecto."))
        if elegido:
            panel.append(experto["id"])

st.subheader("Asignación de modelos")
if not modelos:
    st.error("La API no tiene modelos disponibles. Configura ModelPool antes de iniciar.")
    st.stop()
st.dataframe(modelos, hide_index=True, width="stretch")
modo = st.selectbox("Modo", ["auto", "seed", "manual", "mono"],
                    help="Auto equilibra modelos; seed rota con una semilla; manual permite elegir; mono es el control.")
nombres = [m["nombre"] for m in modelos]
manual, seed = None, None
if modo == "seed":
    seed = int(st.number_input("Semilla", min_value=0, max_value=2**31 - 1, value=42, step=1))
elif modo == "manual":
    manual = {}
    parejas = (("arquitectura", "desarrollo"), ("cloud", "devops"), ("seguridad", "datos"))
    for i, rol in enumerate(panel):
        usados_por_afines = {manual.get(b if rol == a else a) for a, b in parejas if rol in (a, b)}
        candidatos = [n for n in nombres if n not in usados_por_afines] or nombres
        predeterminado = min(candidatos, key=lambda n: sum(v == n for v in manual.values()))
        manual[rol] = st.selectbox(f"Modelo de {rol}", nombres, index=nombres.index(predeterminado), key=f"model_{rol}")
elif modo == "mono":
    seleccionado = st.selectbox("Modelo para todo el panel", nombres)
    manual = {rol: seleccionado for rol in panel}
    st.warning("Panel mono-modelo: riesgo de falso consenso. Úsalo para el experimento de control.")
if len({m.get("familia") for m in modelos}) < 2:
    st.warning("Hay menos de dos familias de modelos disponibles: riesgo de falso consenso.")

with st.expander("Reglas Delphi", expanded=True):
    a, b, c, d = st.columns(4)
    minimo = int(a.number_input("Mínimo de rondas", min_value=2, max_value=3, value=2, step=1))
    maximo = int(b.number_input("Máximo de rondas", min_value=2, max_value=3, value=3, step=1))
    iqr = c.number_input("Umbral IQR", min_value=0., max_value=4., value=1., step=.25)
    consenso = d.slider("Consenso global (%)", min_value=1, max_value=100, value=80)
    st.caption("Escala Likert 1–5. La API y el motor vuelven a validar los límites.")
config = dict(proyecto=proyecto, expertos=panel, asignacion_modelos=modo, modelos_manual=manual,
              seed=seed, min_rondas=minimo, max_rondas=maximo, umbral_iqr=iqr,
              umbral_consenso_global=consenso / 100)
if st.button("Iniciar análisis", type="primary", key="iniciar_analisis"):
    errores = validar_config(config, modelos)
    if errores:
        for error in errores:
            st.error(error)
    else:
        creado = api.crear_run(config)
        st.session_state.active_run = creado["run_id"]
        st.switch_page("pages/2_En_vivo.py")
