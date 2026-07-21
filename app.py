import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="SO Activity Dashboard", layout="wide",
                   initial_sidebar_state="expanded")

VISIT_TGT_PER_SO = 20

# ─────────────────────────────────────────────────────────────────
# Parsing
# ─────────────────────────────────────────────────────────────────
def parse_file(file):
    head = pd.read_excel(file, sheet_name="SO Activity", header=None, nrows=3)
    report_date = None
    for v in head.iloc[2]:
        if isinstance(v, pd.Timestamp):
            report_date = v.normalize()
            break

    df = pd.read_excel(file, sheet_name="SO Activity", header=3)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(subset=["Group", "SR Name"])
    df = df[df["Group"].isin(["Captain", "Kings", "Royals"])]

    for c in ["Total Outlet (Base Route)", "Total Outlet Visit", "Memo",
              "Order Amount", "As of Yesterday Visit", "As of yesterday Memo",
              "As of yesterday order Amount"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    df["AsOf Visit"] = df["As of Yesterday Visit"] + df["Total Outlet Visit"]
    df["AsOf Memo"] = df["As of yesterday Memo"] + df["Memo"]
    df["AsOf Order"] = df["As of yesterday order Amount"] + df["Order Amount"]
    return report_date, df

def summarize(d, by):
    g = d.groupby(by, as_index=False).agg(
        Total_SO=("SR Name", "count"),
        Total_Outlet=("Total Outlet (Base Route)", "sum"),
        Visit=("Total Outlet Visit", "sum"),
        Memo=("Memo", "sum"),
        Order=("Order Amount", "sum"),
        AsOf_Order=("AsOf Order", "sum"),
    )
    g["Visit TGT"] = g["Total_SO"] * VISIT_TGT_PER_SO
    g["Visit %"] = (g["Visit"] / g["Visit TGT"] * 100).round(1)
    g["Avg Visit"] = (g["Visit"] / g["Total_SO"]).round(1)
    g["Avg Memo"] = (g["Memo"] / g["Total_SO"]).round(1)
    g["Order Coverage %"] = (g["Memo"] / g["Total_Outlet"].where(g["Total_Outlet"] > 0)
                             * 100).round(1)
    g["Strike Rate %"] = (g["Memo"] / g["Visit"].where(g["Visit"] > 0) * 100).round(1)
    g["Order (k)"] = (g["Order"] / 1000).round(1)
    g["AsOf Order (k)"] = (g["AsOf_Order"] / 1000).round(1)
    return g

# ─────────────────────────────────────────────────────────────────
# Persistence — the GitHub repo's data/ folder is the permanent store.
# Deployed app: data/ files ship with the repo and auto-load on start.
# Uploading in the sidebar pushes the file to the repo via GitHub API
# (needs [github] token in secrets); the app then redeploys with it.
# ─────────────────────────────────────────────────────────────────
import os, base64, requests

DATA_DIR = "data"

def github_configured():
    try:
        return "github" in st.secrets and st.secrets["github"].get("token")
    except Exception:
        return False

def save_to_github(filename, file_bytes):
    cfg = st.secrets["github"]
    branch = cfg.get("branch", "main")
    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{DATA_DIR}/{filename}"
    headers = {"Authorization": f"Bearer {cfg['token']}",
               "Accept": "application/vnd.github+json"}
    r = requests.get(url, headers=headers, params={"ref": branch})
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {"message": f"Daily report: {filename}",
               "content": base64.b64encode(file_bytes).decode(),
               "branch": branch}
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=headers, json=payload)
    return r.status_code in (200, 201), r.json().get("message", "")

def load_from_folder(folder):
    datasets = {}
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".xlsx") and not name.startswith("~"):
                try:
                    dte, d = parse_file(os.path.join(folder, name))
                    if dte is not None:
                        datasets[dte] = d
                except Exception:
                    pass
    return datasets

if "datasets" not in st.session_state:
    st.session_state.datasets = {}
st.session_state.datasets.update(load_from_folder(DATA_DIR))

with st.sidebar:
    st.title("📊 SO Activity")
    if st.session_state.datasets:
        st.success(f"💾 {len(st.session_state.datasets)} day(s) in permanent store")

    st.subheader("➕ Upload new report")
    files = st.file_uploader("Daily SO Activity Report", type=["xlsx"],
                             accept_multiple_files=True,
                             label_visibility="collapsed")
    for f in files or []:
        try:
            dte, d = parse_file(f)
            if dte is None:
                st.error(f"{f.name}: report date not found in sheet")
                continue
            already = dte in st.session_state.datasets
            st.session_state.datasets[dte] = d
            if github_configured() and not already:
                fname = f"SO_Activity_{dte.strftime('%Y-%m-%d')}.xlsx"
                ok, msg = save_to_github(fname, f.getvalue())
                if ok:
                    st.success(f"✅ {dte.strftime('%d %b')} saved permanently "
                               "(live for everyone in ~1 min)")
                else:
                    st.warning(f"Loaded for this session, but permanent save "
                               f"failed: {msg}")
        except Exception as e:
            st.error(f"{f.name}: {e}")

    if not st.session_state.datasets:
        st.info("Upload a report to begin.")
        st.stop()

    st.subheader("2️⃣ Select date")
    dates = sorted(st.session_state.datasets.keys(), reverse=True)
    sel_date = st.selectbox("Report date", dates,
                            format_func=lambda d: d.strftime("%d %b %Y"),
                            label_visibility="collapsed")

    df_full = st.session_state.datasets[sel_date]

    st.subheader("3️⃣ Filters")
    groups = st.multiselect("Group", sorted(df_full["Group"].unique()),
                            default=sorted(df_full["Group"].unique()))
    regions = st.multiselect("Region", sorted(df_full["Region Name"].dropna().unique()),
                             default=sorted(df_full["Region Name"].dropna().unique()))

df = df_full[df_full["Group"].isin(groups) & df_full["Region Name"].isin(regions)]
if df.empty:
    st.warning("No rows match the selected filters.")
    st.stop()

# ─────────────────────────────────────────────────────────────────
# Header + KPI cards
# ─────────────────────────────────────────────────────────────────
st.title("SO Activity Dashboard")
st.caption(f"Showing: **{sel_date.strftime('%d %b %Y')}**  ·  "
           f"{len(df)} SOs  ·  {len(st.session_state.datasets)} day(s) loaded")

# Previous stored date (for day-over-day growth on KPI cards)
all_dates = sorted(st.session_state.datasets.keys())
idx = all_dates.index(sel_date)
prev_df = None
if idx > 0:
    p = st.session_state.datasets[all_dates[idx - 1]]
    prev_df = p[p["Group"].isin(groups) & p["Region Name"].isin(regions)]

def delta_vs_prev(cur, prev_val):
    if prev_val in (None, 0):
        return None
    return f"{(cur - prev_val) / prev_val * 100:+.1f}% vs prev day"

tot_so = len(df)
tot_visit = df["Total Outlet Visit"].sum()
tot_tgt = tot_so * VISIT_TGT_PER_SO
tot_memo = df["Memo"].sum()
tot_order = df["Order Amount"].sum() / 1000
strike = (tot_memo / tot_visit * 100) if tot_visit else 0

pv = pm = po = None
if prev_df is not None and len(prev_df):
    pv = prev_df["Total Outlet Visit"].sum()
    pm = prev_df["Memo"].sum()
    po = prev_df["Order Amount"].sum() / 1000

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total SO", f"{tot_so}")
c2.metric("Visits", f"{tot_visit:,.0f}", delta_vs_prev(tot_visit, pv))
c3.metric("Memos", f"{tot_memo:,.0f}", delta_vs_prev(tot_memo, pm))
c4.metric("Strike Rate", f"{strike:.1f}%")
c5.metric("Order Amount", f"{tot_order:,.1f}K", delta_vs_prev(tot_order, po))

st.divider()

tabs = st.tabs(["🏆 Rankings", "📍 Zone Summary", "🏢 National",
                "📈 Trend", "👤 SO Detail", "📥 Summary & Download"])

# ─────────────────────────────────────────────────────────────────
# Tab 1 — Rankings (highest / lowest)
# ─────────────────────────────────────────────────────────────────
with tabs[0]:
    zone = summarize(df, ["Group", "Zone Name"])
    zone["Zone"] = zone["Zone Name"] + " (" + zone["Group"].str[0] + ")"

    # Overall Performance Score — blends Visit %, Strike Rate %, Order
    # Coverage % and Order value into one 0-100 score (each metric scaled
    # relative to today's zones), so Top 5 and Bottom 5 always compare
    # zones on the SAME basis instead of different metrics.
    score_metrics = ["Visit %", "Strike Rate %", "Order Coverage %", "Order (k)"]
    norm_cols = []
    for m in score_metrics:
        col = zone[m]
        mn, mx = col.min(), col.max()
        ncol = f"_n_{m}"
        zone[ncol] = 50.0 if pd.isna(mx - mn) or mx == mn else (col - mn) / (mx - mn) * 100
        norm_cols.append(ncol)
    zone["Overall Score"] = zone[norm_cols].mean(axis=1).round(1)
    zone = zone.drop(columns=norm_cols)

    metric = st.radio("Rank by",
                      ["Overall Performance", "Visit %", "Strike Rate %",
                       "Order (k)", "Avg Memo"],
                      horizontal=True, index=0)
    rank_col = "Overall Score" if metric == "Overall Performance" else metric

    ranked = zone.dropna(subset=[rank_col]).sort_values(rank_col, ascending=False)
    top5, bottom5 = ranked.head(5), ranked.tail(5)

    left, right = st.columns(2)
    with left:
        st.subheader(f"🟢 Top 5 zones — {metric}")
        fig = px.bar(top5.sort_values(rank_col), x=rank_col, y="Zone",
                     orientation="h", text=rank_col,
                     color_discrete_sequence=["#1D9E75"])
        fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                          yaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader(f"🔴 Bottom 5 zones — {metric}")
        fig = px.bar(bottom5.sort_values(rank_col, ascending=False),
                     x=rank_col, y="Zone", orientation="h", text=rank_col,
                     color_discrete_sequence=["#E24B4A"])
        fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                          yaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)
    if metric == "Overall Performance":
        st.caption("Overall Score blends Visit %, Strike Rate %, Order Coverage % "
                   "and Order value — each scaled 0-100 relative to today's zones, "
                   "then averaged. Same score ranks both Top 5 and Bottom 5.")

    st.subheader("SO-level extremes — overall performance")
    so = df.copy()
    so["Order (k)"] = (so["Order Amount"] / 1000).round(1)
    so_nz = so[so["Total Outlet Visit"] > 0].copy()
    so_metrics = ["Total Outlet Visit", "Memo", "Order (k)"]
    so_norm_cols = []
    for m in so_metrics:
        col = so_nz[m]
        mn, mx = col.min(), col.max()
        ncol = f"_n_{m}"
        so_nz[ncol] = 50.0 if mx == mn else (col - mn) / (mx - mn) * 100
        so_norm_cols.append(ncol)
    so_nz["SO Score"] = so_nz[so_norm_cols].mean(axis=1).round(1)
    so_nz = so_nz.drop(columns=so_norm_cols)

    so_cols = ["SR Name", "Zone Name", "Group", "Total Outlet Visit",
              "Memo", "Order (k)", "SO Score"]
    a, b = st.columns(2)
    with a:
        st.markdown("**Top 5 SOs**")
        st.dataframe(so_nz.nlargest(5, "SO Score")[so_cols],
                     use_container_width=True, hide_index=True)
    with b:
        st.markdown("**Bottom 5 SOs** (excl. zero-visit — see alert below)")
        st.dataframe(so_nz.nsmallest(5, "SO Score")[so_cols],
                     use_container_width=True, hide_index=True)
    st.caption("SO Score blends Visits, Memos and Order value — same basis for "
               "both Top 5 and Bottom 5.")

    zero = df[df["Total Outlet Visit"] == 0]
    if len(zero):
        st.error(f"⚠️ {len(zero)} SO(s) with ZERO visits — priority follow-up")
        st.dataframe(zero[["Group", "Zone Name", "Base Name", "SR Name"]],
                     use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────────────────────────
# Tab 2 — Zone Summary
# ─────────────────────────────────────────────────────────────────
with tabs[1]:
    zone = summarize(df, ["Group", "Region Name", "Zone Code", "Zone Name"])
    st.dataframe(
        zone[["Group", "Region Name", "Zone Name", "Total_SO", "Total_Outlet",
              "Visit", "Visit TGT", "Visit %", "Avg Visit", "Memo", "Avg Memo",
              "Order Coverage %", "Strike Rate %", "Order (k)", "AsOf Order (k)"]],
        use_container_width=True, hide_index=True)
    csel = st.selectbox("Chart metric",
                        ["Visit %", "Strike Rate %", "Order (k)", "Order Coverage %"])
    fig = px.bar(zone.sort_values(csel, ascending=False),
                 x="Zone Name", y=csel, color="Group", barmode="group")
    if csel == "Visit %":
        fig.add_hline(y=100, line_dash="dash", line_color="gray")
    st.plotly_chart(fig, use_container_width=True)

# ─────────────────────────────────────────────────────────────────
# Tab 3 — National
# ─────────────────────────────────────────────────────────────────
with tabs[2]:
    nat = summarize(df, ["Group", "NSM/RSM"])
    st.dataframe(
        nat[["Group", "NSM/RSM", "Total_SO", "Visit", "Visit TGT", "Visit %",
             "Avg Visit", "Memo", "Avg Memo", "Order Coverage %",
             "Strike Rate %", "Order (k)"]],
        use_container_width=True, hide_index=True)
    fig = px.bar(nat, x="NSM/RSM", y="Visit %", color="Group",
                 barmode="group", text="Visit %")
    fig.add_hline(y=100, line_dash="dash", line_color="gray")
    st.plotly_chart(fig, use_container_width=True)

# ─────────────────────────────────────────────────────────────────
# Tab 4 — Trend across uploaded dates
# ─────────────────────────────────────────────────────────────────
with tabs[3]:
    if len(st.session_state.datasets) < 2:
        st.info("Upload files from 2+ different dates to see day-over-day trends.")
    else:
        rows = []
        for dte, d in sorted(st.session_state.datasets.items()):
            d2 = d[d["Group"].isin(groups) & d["Region Name"].isin(regions)]
            v = d2["Total Outlet Visit"].sum()
            m = d2["Memo"].sum()
            rows.append({"Date": dte, "Visits": v, "Memos": m,
                         "Order (k)": round(d2["Order Amount"].sum() / 1000, 1),
                         "Visit %": round(v / (len(d2) * VISIT_TGT_PER_SO) * 100, 1),
                         "Strike Rate %": round(m / v * 100, 1) if v else 0})
        trend = pd.DataFrame(rows)

        tmetric = st.selectbox("Trend metric",
                               ["Visits", "Memos", "Order (k)", "Visit %",
                                "Strike Rate %"])
        trend["Growth %"] = (trend[tmetric].pct_change() * 100).round(1)

        st.subheader("📅 Daily trend")
        fig = px.line(trend, x="Date", y=tmetric, markers=True)
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Day-over-day growth")
        gfig = px.bar(trend.dropna(subset=["Growth %"]), x="Date", y="Growth %",
                      text="Growth %",
                      color=trend.dropna(subset=["Growth %"])["Growth %"] >= 0,
                      color_discrete_map={True: "#1D9E75", False: "#E24B4A"})
        gfig.update_layout(showlegend=False)
        gfig.add_hline(y=0, line_color="gray")
        st.plotly_chart(gfig, use_container_width=True)
        st.dataframe(trend, use_container_width=True, hide_index=True)

        # Monthly comparison — activates when data spans 2+ months
        trend["Month"] = trend["Date"].dt.strftime("%b %Y")
        if trend["Month"].nunique() >= 2:
            st.subheader("🗓️ Monthly comparison")
            monthly = trend.groupby("Month", sort=False).agg(
                Days=("Date", "count"),
                Visits=("Visits", "sum"),
                Memos=("Memos", "sum"),
                **{"Order (k)": ("Order (k)", "sum")},
            ).reset_index()
            monthly["Strike Rate %"] = (monthly["Memos"] / monthly["Visits"]
                                        * 100).round(1)
            mm = tmetric if tmetric in monthly.columns else "Order (k)"
            monthly["MoM Growth %"] = (monthly[mm].pct_change() * 100).round(1)
            st.dataframe(monthly, use_container_width=True, hide_index=True)
            mfig = px.bar(monthly, x="Month", y=mm, text=mm)
            st.plotly_chart(mfig, use_container_width=True)
            st.caption("Note: months with different day counts aren't directly "
                       "comparable on totals — check the Days column, or compare "
                       "rate metrics like Strike Rate %.")

# ─────────────────────────────────────────────────────────────────
# Tab 5 — SO Detail with zone highlight
# ─────────────────────────────────────────────────────────────────
with tabs[4]:
    zones = ["(All)"] + sorted(df["Zone Name"].dropna().unique().tolist())
    zsel = st.selectbox("Highlight zone", zones)

    detail = df[["Group", "Region Name", "Zone Name", "Base Name", "SR Name",
                 "Total Outlet (Base Route)", "Total Outlet Visit", "Memo",
                 "Order Amount", "AsOf Visit", "AsOf Memo"]].copy()
    detail["Order Amount"] = (detail["Order Amount"] / 1000).round(1)
    detail = detail.rename(columns={"Order Amount": "Order (k)"})

    def hl(row):
        return ["background-color: #fff3b0" if row["Zone Name"] == zsel else ""
                ] * len(row)

    if zsel == "(All)":
        st.dataframe(detail, use_container_width=True, hide_index=True, height=560)
    else:
        st.dataframe(detail.style.apply(hl, axis=1),
                     use_container_width=True, hide_index=True, height=560)

# ─────────────────────────────────────────────────────────────────
# Tab 6 — Summary & Download (Excel export of the selected day)
# ─────────────────────────────────────────────────────────────────
with tabs[5]:
    date_str = sel_date.strftime("%d %b %Y")
    st.subheader(f"Daily summary — {date_str}")

    nat = summarize(df, ["Group", "NSM/RSM"])
    zone = summarize(df, ["Group", "Region Name", "Zone Code", "Zone Name"])
    zero = df[df["Total Outlet Visit"] == 0]

    kpi_rows = [
        ("Report Date", date_str),
        ("Total SO", tot_so),
        ("Total Visits", int(tot_visit)),
        ("Visit Target", int(tot_tgt)),
        ("Visit Achievement %", round(tot_visit / tot_tgt * 100, 1) if tot_tgt else 0),
        ("Total Memos", int(tot_memo)),
        ("Strike Rate %", round(strike, 1)),
        ("Order Amount (k)", round(tot_order, 1)),
        ("Zero-Visit SOs", len(zero)),
    ]
    kpi_df = pd.DataFrame(kpi_rows, columns=["Metric", "Value"])
    st.dataframe(kpi_df, use_container_width=True, hide_index=True)

    zone_cols = ["Group", "Region Name", "Zone Name", "Total_SO", "Visit",
                 "Visit TGT", "Visit %", "Avg Visit", "Memo", "Avg Memo",
                 "Order Coverage %", "Strike Rate %", "Order (k)"]
    nat_cols = ["Group", "NSM/RSM", "Total_SO", "Visit", "Visit TGT", "Visit %",
                "Avg Visit", "Memo", "Avg Memo", "Strike Rate %", "Order (k)"]

    def build_excel():
        from io import BytesIO
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            kpi_df.to_excel(xw, sheet_name="KPI Summary", index=False)
            nat[nat_cols].to_excel(xw, sheet_name="National", index=False)
            zone[zone_cols].to_excel(xw, sheet_name="Zone Summary", index=False)
            if len(zero):
                zero[["Group", "Region Name", "Zone Name", "Base Name",
                      "SR Name"]].to_excel(xw, sheet_name="Zero Visit SOs",
                                           index=False)
            for ws in xw.book.worksheets:
                for col in ws.columns:
                    width = max(len(str(c.value)) for c in col if c.value
                                is not None)
                    ws.column_dimensions[col[0].column_letter].width = min(
                        width + 3, 30)
        return buf.getvalue()

    st.download_button(
        label=f"📥 Download summary — {date_str} (.xlsx)",
        data=build_excel(),
        file_name=f"SO_Summary_{sel_date.strftime('%Y-%m-%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet",
        type="primary",
    )
    st.caption("Workbook contains: KPI Summary, National, Zone Summary"
               + (", Zero Visit SOs" if len(zero) else "")
               + ". Respects the sidebar Group/Region filters.")
