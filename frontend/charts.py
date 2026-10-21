"""Gráficos derivados de InformeDelphi; ninguna puntuación se inventa aquí."""
import plotly.graph_objects as go


def convergencia(informe, decision_id):
    fig = go.Figure()
    items = [i for i in informe["cuestionario"]["items"] if i.get("decision_id") == decision_id]
    for item in items:
        puntos = []
        for ronda in informe["rondas"]:
            for dato in ronda["estadisticas"]:
                if dato["item_id"] == item["id"]:
                    puntos.append((ronda["ronda"], dato))
        if not puntos:
            continue
        fig.add_trace(go.Scatter(
            x=[r for r, _ in puntos], y=[s["mediana"] for _, s in puntos],
            name=item.get("alternativa") or item["id"], mode="lines+markers",
            error_y=dict(type="data", symmetric=False,
                         array=[s["q3"] - s["mediana"] for _, s in puntos],
                         arrayminus=[s["mediana"] - s["q1"] for _, s in puntos]),
        ))
    fig.update_layout(xaxis_title="Ronda", yaxis_title="Mediana y rango Q1–Q3", yaxis_range=[.5, 5.5],
                      xaxis=dict(dtick=1), legend=dict(orientation="h"), margin=dict(t=30))
    return fig


def radar(informe):
    datos = informe.get("evaluacion_por_dimension", {})
    nombres, valores = list(datos), list(datos.values())
    fig = go.Figure()
    if nombres:
        fig.add_trace(go.Scatterpolar(r=valores + valores[:1], theta=nombres + nombres[:1],
                                     fill="toself", name="Mediana final"))
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 5], visible=True)), margin=dict(t=30))
    return fig


def matriz_riesgos(informe):
    riesgos = informe.get("riesgos", [])
    fig = go.Figure(go.Scatter(
        x=[r["probabilidad"] for r in riesgos], y=[r["impacto"] for r in riesgos],
        text=[f"R{i + 1}" for i in range(len(riesgos))],
        customdata=[r["descripcion"] for r in riesgos], mode="markers+text", textposition="top center",
        marker=dict(size=[12 + 2 * r["menciones"] for r in riesgos],
                    color=[r["probabilidad"] * r["impacto"] for r in riesgos],
                    colorscale="YlOrRd", cmin=1, cmax=25, showscale=True),
        hovertemplate="%{customdata}<br>Probabilidad: %{x}<br>Impacto: %{y}<extra></extra>",
    ))
    fig.update_layout(xaxis=dict(title="Probabilidad", range=[.5, 5.5], dtick=1),
                      yaxis=dict(title="Impacto", range=[.5, 5.5], dtick=1), margin=dict(t=30))
    return fig
