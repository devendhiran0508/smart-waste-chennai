import streamlit as st
import paho.mqtt.client as mqtt
import json, time, random, math
from datetime import datetime, timezone
from influxdb_client import InfluxDBClient
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# ─── PAGE CONFIG ────────────────────────────────────────────
st.set_page_config(
    page_title="Chennai Smart Waste Management",
    page_icon="♻️",
    layout="wide"
)

# ─── CREDENTIALS ────────────────────────────────────────────
INFLUX_URL    = st.secrets["INFLUX_URL"]
INFLUX_TOKEN  = st.secrets["INFLUX_TOKEN"]
INFLUX_ORG    = st.secrets["INFLUX_ORG"]
INFLUX_BUCKET = st.secrets["INFLUX_BUCKET"]

# ─── HEADER ─────────────────────────────────────────────────
st.title("♻️ Chennai Smart Waste Management")
st.markdown("**Pilot Zone: T. Nagar** · Real-time bin monitoring & route optimization")
st.divider()

# ─── FETCH DATA FROM INFLUXDB ───────────────────────────────
@st.cache_data(ttl=30)
def fetch_bin_data():
    try:
        client = InfluxDBClient(
            url=INFLUX_URL,
            token=INFLUX_TOKEN,
            org=INFLUX_ORG
        )
        query_api = client.query_api()
        query = f'''
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: -1h)
          |> filter(fn: (r) => r._measurement == "bin_reading")
          |> last()
        '''
        tables = query_api.query(query, org=INFLUX_ORG)
        bins = []
        seen = set()
        for table in tables:
            for record in table.records:
                bin_id = record.values.get("bin_id")
                if bin_id and bin_id not in seen:
                    seen.add(bin_id)
                    bins.append({
                        "bin_id":   bin_id,
                        "zone":     record.values.get("zone", "Unknown"),
                        "type":     record.values.get("type", "dry"),
                        "fill_pct": record.values.get("fill_pct", 0),
                        "battery":  record.values.get("battery", 100),
                        "lat":      record.values.get("lat", 13.03),
                        "lon":      record.values.get("lon", 80.23),
                        "status":   record.values.get("status", "OK")
                    })
        return bins
    except Exception as e:
        st.error(f"InfluxDB error: {e}")
        return []

bins = fetch_bin_data()

# ─── KPI METRICS ROW ────────────────────────────────────────
if bins:
    total      = len(bins)
    full_bins  = [b for b in bins if b["status"] == "FULL"]
    half_bins  = [b for b in bins if b["status"] == "HALF"]
    ok_bins    = [b for b in bins if b["status"] == "OK"]
    avg_fill   = sum(b["fill_pct"] for b in bins) / total
    avg_batt   = sum(b["battery"]  for b in bins) / total

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Bins",     total)
    col2.metric("🔴 Full Bins",   len(full_bins),
                delta=f"{len(full_bins)/total*100:.0f}% need collection",
                delta_color="inverse")
    col3.metric("🟡 Half Full",   len(half_bins))
    col4.metric("🟢 OK Bins",     len(ok_bins))
    col5.metric("Avg Fill Level", f"{avg_fill:.1f}%")
    st.divider()

    # ─── TWO COLUMN LAYOUT ──────────────────────────────────
    left, right = st.columns([3, 2])

    with left:
        # ── BIN MAP ─────────────────────────────────────────
        st.subheader("📍 Live Bin Map — T. Nagar, Chennai")
        m = folium.Map(
            location=[13.0300, 80.2300],
            zoom_start=14,
            tiles="CartoDB positron"
        )

        color_map = {"FULL": "red", "HALF": "orange", "OK": "green"}
        icon_map  = {"FULL": "exclamation-sign",
                     "HALF": "info-sign",
                     "OK":   "ok-sign"}

        for b in bins:
            folium.Marker(
                location=[b["lat"], b["lon"]],
                popup=folium.Popup(
                    f"""<b>{b['bin_id']}</b><br>
                    Fill: {b['fill_pct']:.1f}%<br>
                    Type: {b['type']}<br>
                    Zone: {b['zone']}<br>
                    Battery: {b['battery']:.1f}%<br>
                    Status: {b['status']}""",
                    max_width=200
                ),
                icon=folium.Icon(
                    color=color_map[b["status"]],
                    icon=icon_map[b["status"]],
                    prefix="glyphicon"
                )
            ).add_to(m)

        # Draw collection route for full bins
        if len(full_bins) >= 2:
            depot = [13.0350, 80.2400]
            route_coords = [depot]
            for b in full_bins:
                route_coords.append([b["lat"], b["lon"]])
            route_coords.append(depot)
            folium.PolyLine(
                route_coords,
                color="blue",
                weight=2.5,
                opacity=0.7,
                dash_array="5",
                tooltip="Optimized collection route"
            ).add_to(m)
            folium.Marker(
                location=depot,
                popup="Collection Depot",
                icon=folium.Icon(color="blue", icon="home", prefix="glyphicon")
            ).add_to(m)

        st_folium(m, width=700, height=450)

    with right:
        # ── FILL LEVEL CHART ────────────────────────────────
        st.subheader("📊 Bin Fill Distribution")
        df = pd.DataFrame(bins)
        fig_hist = px.histogram(
            df, x="fill_pct",
            nbins=10,
            color_discrete_sequence=["#1D9E75"],
            labels={"fill_pct": "Fill Level (%)"},
        )
        fig_hist.update_layout(
            height=200,
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False
        )
        st.plotly_chart(fig_hist, use_container_width=True)

        # ── STATUS PIE CHART ────────────────────────────────
        st.subheader("🗂️ Bin Status Breakdown")
        fig_pie = go.Figure(go.Pie(
            labels=["Full", "Half", "OK"],
            values=[len(full_bins), len(half_bins), len(ok_bins)],
            marker_colors=["#E24B4A", "#EF9F27", "#1D9E75"],
            hole=0.4
        ))
        fig_pie.update_layout(
            height=220,
            margin=dict(l=0, r=0, t=10, b=0)
        )
        st.plotly_chart(fig_pie, use_container_width=True)

        # ── ZONE BREAKDOWN ──────────────────────────────────
        st.subheader("🗺️ Fill by Zone")
        zone_df = df.groupby("zone")["fill_pct"].mean().reset_index()
        fig_zone = px.bar(
            zone_df, x="zone", y="fill_pct",
            color="fill_pct",
            color_continuous_scale=["green", "orange", "red"],
            labels={"fill_pct": "Avg Fill %", "zone": "Zone"}
        )
        fig_zone.update_layout(
            height=200,
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False
        )
        st.plotly_chart(fig_zone, use_container_width=True)

    st.divider()

    # ─── KPI SAVINGS SECTION ────────────────────────────────
    st.subheader("📈 Route Optimization KPI Report")

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a  = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return R * 2 * math.asin(math.sqrt(a))

    if len(full_bins) >= 2:
        DEPOT_LAT, DEPOT_LON = 13.0350, 80.2400
        optimized  = sum(
            haversine(full_bins[i]["lat"], full_bins[i]["lon"],
                      full_bins[i+1]["lat"], full_bins[i+1]["lon"])
            for i in range(len(full_bins)-1)
        )
        baseline   = sum(
            haversine(DEPOT_LAT, DEPOT_LON, b["lat"], b["lon"]) * 2
            for b in full_bins
        )
        saved_dist = baseline - optimized
        fuel_saved = (saved_dist / 1000) * 0.35
        co2_saved  = fuel_saved * 2.68
        cost_saved = fuel_saved * 100
        pct_saved  = (saved_dist / baseline * 100) if baseline > 0 else 0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Distance Saved",      f"{saved_dist/1000:.2f} km")
        k2.metric("Fuel Saved",          f"{fuel_saved:.2f} L")
        k3.metric("CO₂ Reduced",         f"{co2_saved:.2f} kg")
        k4.metric("Cost Saved",          f"₹{cost_saved:.0f}")

        st.progress(int(pct_saved),
                    text=f"Route efficiency improvement: {pct_saved:.1f}%")

    st.divider()

    # ─── BIN DATA TABLE ─────────────────────────────────────
    st.subheader("🗃️ All Bin Readings")
    display_df = df[["bin_id","zone","type","fill_pct","battery","status"]].copy()
    display_df.columns = ["Bin ID","Zone","Type","Fill %","Battery %","Status"]
    display_df = display_df.sort_values("Fill %", ascending=False)
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )

    # ─── AUTO REFRESH ───────────────────────────────────────
    st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')} · Auto-refreshes every 30s")
    time.sleep(30)
    st.rerun()

else:
    st.warning("⚠️ No bin data found in InfluxDB. Make sure your simulator is running!")
    st.info("Run your Colab simulator (Layer 2) and InfluxDB writer (Layer 3) first.")
    if st.button("🔄 Retry"):
        st.rerun()
