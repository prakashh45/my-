import os
import pandas as pd
import altair as alt
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="VISTORE Dashboard", layout="wide")

STATUS_FILE = "order_status.csv"   # manual status updates
REVIEW_FILE = "reviews.csv"        # reviews data
STOCK_FILE = "stock.csv"           # merged stock

STATUS_OPTIONS = ["Pending", "Placed", "Delivered", "Returned", "Cancelled"]

# ---------- helpers ----------
def clean_text(s):
    """Flipkart CSVs often have values like SKU:"abc" or ="123"."""
    if pd.isna(s):
        return s
    s = str(s).strip()
    s = s.replace('="', '').replace('SKU:', '').replace('"', '').strip()
    return s

@st.cache_data
def load_orders(files):
    frames = []
    for f in files:
        df = pd.read_csv(f, dtype=str)
        df.columns = [c.strip() for c in df.columns]
        df["Source File"] = f.name
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    for col in ["Order Id", "ORDER ITEM ID", "Shipment ID", "SKU", "Tracking ID", "FSN"]:
        if col in df.columns:
            df[col] = df[col].map(clean_text)
    for col in ["Invoice Amount", "Selling Price Per Item", "Quantity"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "Ordered On" in df.columns:
        df["Ordered On"] = pd.to_datetime(df["Ordered On"], errors="coerce")
    if "State" in df.columns:
        df["State"] = df["State"].str.strip().str.title()
    if "ORDER ITEM ID" in df.columns:
        df = df.drop_duplicates(subset=["ORDER ITEM ID"], keep="last")
    return df

def load_status():
    if os.path.exists(STATUS_FILE):
        return pd.read_csv(STATUS_FILE, dtype=str).fillna("")
    return pd.DataFrame(columns=["ORDER ITEM ID", "Status", "Note", "Updated At"])

def save_status(df):
    df.to_csv(STATUS_FILE, index=False)

def load_csv(path, cols):
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame(columns=cols)

def read_id_file(uploaded):
    """Read order IDs (and optional Status column) from a csv/txt file."""
    raw = pd.read_csv(uploaded, dtype=str, header=None, sep=None, engine="python").fillna("")
    first = raw.iloc[0].astype(str).str.strip().str.lower().tolist()
    has_header = any(x in ("order id", "orderid", "order_id", "order item id") for x in first)
    if has_header:
        raw.columns = [c.strip() for c in raw.iloc[0].astype(str)]
        raw = raw.iloc[1:].reset_index(drop=True)
        id_col = next((c for c in raw.columns if c.lower() in ("order id", "orderid", "order_id", "order item id")), raw.columns[0])
        status_col = next((c for c in raw.columns if c.lower() == "status"), None)
        out = pd.DataFrame({"id": raw[id_col].map(clean_text)})
        out["status"] = raw[status_col].str.strip().str.title() if status_col else ""
    else:
        out = pd.DataFrame({"id": raw.iloc[:, 0].map(clean_text)})
        out["status"] = raw.iloc[:, 1].str.strip().str.title() if raw.shape[1] > 1 else ""
    out = out[out["id"].astype(str).str.strip() != ""]
    return out.drop_duplicates(subset=["id"])

# ---------- sidebar uploads ----------
st.sidebar.title("VISTORE")
order_files = st.sidebar.file_uploader("Upload order CSVs (multiple)", type="csv", accept_multiple_files=True)

if not order_files:
    st.info("Upload one or more order CSV files from the sidebar to start.")
    st.stop()

orders = load_orders(order_files)
status_df = load_status()
orders = orders.merge(status_df[["ORDER ITEM ID", "Status", "Note"]], on="ORDER ITEM ID", how="left")
orders["Status"] = orders["Status"].replace("", pd.NA).fillna("Pending")
orders["Note"] = orders["Note"].fillna("")

st.title("VISTORE Order Dashboard")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total orders", orders["Order Id"].nunique())
m2.metric("Total units", int(orders["Quantity"].sum()))
m3.metric("Revenue", f"₹{orders['Invoice Amount'].sum():,.0f}")
m4.metric("Pending", int((orders["Status"] == "Pending").sum()))
m5.metric("Returned", int((orders["Status"] == "Returned").sum()))

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["🔎 Search & Update", "📥 Bulk Update", "🗺️ State-wise", "📊 Analytics", "⭐ Reviews", "📦 Stock"]
)

# ---------- TAB 1: search + manual update ----------
with tab1:
    c1, c2 = st.columns([2, 1])
    q = c1.text_input("Search by Order ID (or Order Item ID / Tracking ID)")
    flt = c2.selectbox("Filter by status", ["All"] + STATUS_OPTIONS)

    view = orders.copy()
    if q:
        q = q.strip()
        mask = (
            view["Order Id"].str.contains(q, case=False, na=False)
            | view["ORDER ITEM ID"].str.contains(q, case=False, na=False)
            | view["Tracking ID"].str.contains(q, case=False, na=False)
        )
        view = view[mask]
    if flt != "All":
        view = view[view["Status"] == flt]

    st.caption(f"{len(view)} rows")
    show_cols = ["Order Id", "ORDER ITEM ID", "Ordered On", "SKU", "Product", "Quantity",
                 "Invoice Amount", "Buyer name", "City", "State", "Tracking ID", "Status", "Note"]
    show_cols = [c for c in show_cols if c in view.columns]

    edited = st.data_editor(
        view[show_cols],
        use_container_width=True,
        hide_index=True,
        disabled=[c for c in show_cols if c not in ("Status", "Note")],
        column_config={"Status": st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS)},
        key="orders_editor",
    )

    if st.button("💾 Save status updates"):
        upd = edited[["ORDER ITEM ID", "Status", "Note"]].copy()
        upd["Updated At"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        base = status_df[~status_df["ORDER ITEM ID"].isin(upd["ORDER ITEM ID"])]
        save_status(pd.concat([base, upd], ignore_index=True))
        st.success("Saved!")
        st.rerun()

# ---------- TAB 2: bulk update by uploading order IDs ----------
with tab2:
    st.subheader("Bulk update orders by Order ID")
    st.caption("Upload a file or paste Order IDs, choose the status, then click Apply. "
               "The file can have just one column of IDs, or two columns: Order Id, Status.")

    left, right = st.columns(2)
    id_file = left.file_uploader("Upload Order ID file (csv / txt)", type=["csv", "txt"], key="idfile")
    pasted = right.text_area("...or paste Order IDs (one per line or comma separated)", height=140)
    b1, b2 = st.columns([1, 2])
    new_status = b1.selectbox("Set status to", STATUS_OPTIONS, index=STATUS_OPTIONS.index("Placed"))
    bulk_note = b2.text_input("Note (optional)")

    ids = pd.DataFrame(columns=["id", "status"])
    if id_file is not None:
        ids = read_id_file(id_file)
    elif pasted.strip():
        items = [clean_text(x) for x in pasted.replace(",", "\n").splitlines() if x.strip()]
        ids = pd.DataFrame({"id": items, "status": ""}).drop_duplicates(subset=["id"])

    if len(ids):
        # use status from file if given, else the dropdown choice
        ids["final_status"] = ids["status"].where(ids["status"].isin(STATUS_OPTIONS), new_status)
        key_cols = ["Order Id", "ORDER ITEM ID", "Tracking ID"]
        matched_rows = []
        not_found = []
        for _, r in ids.iterrows():
            hit = orders[(orders["Order Id"] == r["id"]) | (orders["ORDER ITEM ID"] == r["id"])
                         | (orders["Tracking ID"] == r["id"])]
            if len(hit):
                matched_rows.append(hit.assign(NewStatus=r["final_status"]))
            else:
                not_found.append(r["id"])

        st.write(f"**{len(ids)}** IDs read, **{len(matched_rows)}** matched, **{len(not_found)}** not found")

        if matched_rows:
            preview = pd.concat(matched_rows).drop_duplicates(subset=["ORDER ITEM ID"], keep="last")
            st.dataframe(preview[["Order Id", "ORDER ITEM ID", "SKU", "State", "Status", "NewStatus"]],
                         use_container_width=True, hide_index=True)

            if st.button("✅ Apply status to these orders", type="primary"):
                upd = preview[["ORDER ITEM ID", "NewStatus"]].rename(columns={"NewStatus": "Status"})
                upd["Note"] = bulk_note
                upd["Updated At"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                base = status_df[~status_df["ORDER ITEM ID"].isin(upd["ORDER ITEM ID"])]
                save_status(pd.concat([base, upd], ignore_index=True))
                st.success(f"Updated {len(upd)} order items")
                st.rerun()

        if not_found:
            with st.expander(f"IDs not found ({len(not_found)})"):
                st.write(not_found)

# ---------- TAB 3: state-wise ----------
with tab3:
    g = (orders.groupby("State")
         .agg(Orders=("Order Id", "nunique"), Units=("Quantity", "sum"),
              Revenue=("Invoice Amount", "sum"),
              Returned=("Status", lambda s: (s == "Returned").sum()),
              Delivered=("Status", lambda s: (s == "Delivered").sum()))
         .reset_index().sort_values("Orders", ascending=False))
    st.subheader("Orders by state")
    st.bar_chart(g.set_index("State")["Orders"])
    st.dataframe(g, use_container_width=True, hide_index=True)

    st.subheader("City drill-down")
    state = st.selectbox("Select state", g["State"].dropna().tolist())
    cg = (orders[orders["State"] == state].groupby("City")
          .agg(Orders=("Order Id", "nunique"), Units=("Quantity", "sum"),
               Revenue=("Invoice Amount", "sum"))
          .reset_index().sort_values("Orders", ascending=False))
    st.dataframe(cg, use_container_width=True, hide_index=True)

# ---------- TAB 4: analytics ----------
with tab4:
    a1, a2 = st.columns(2)

    with a1:
        st.subheader("Orders per day")
        daily = (orders.dropna(subset=["Ordered On"])
                 .assign(Day=lambda d: d["Ordered On"].dt.date)
                 .groupby("Day")["Order Id"].nunique())
        st.line_chart(daily)

    with a2:
        st.subheader("Order status split")
        sc = orders["Status"].value_counts().reset_index()
        sc.columns = ["Status", "Count"]
        donut = (alt.Chart(sc).mark_arc(innerRadius=60)
                 .encode(theta="Count:Q",
                         color=alt.Color("Status:N", scale=alt.Scale(
                             domain=STATUS_OPTIONS,
                             range=["#f5a623", "#3498db", "#2ecc71", "#e74c3c", "#95a5a6"])),
                         tooltip=["Status", "Count"]))
        st.altair_chart(donut, use_container_width=True)

    b1, b2 = st.columns(2)

    with b1:
        st.subheader("Top selling SKUs")
        top_n = st.slider("Show top", 5, 30, 10)
        top = (orders.groupby("SKU")["Quantity"].sum()
               .sort_values(ascending=False).head(top_n))
        st.bar_chart(top)

    with b2:
        st.subheader("Return rate % by state")
        rr = (orders.groupby("State")
              .agg(Total=("ORDER ITEM ID", "count"),
                   Returned=("Status", lambda s: (s == "Returned").sum())))
        rr["Return %"] = (rr["Returned"] / rr["Total"] * 100).round(1)
        min_orders = st.number_input("Min orders in state", 1, 100, 5)
        rr = rr[rr["Total"] >= min_orders].sort_values("Return %", ascending=False)
        st.bar_chart(rr["Return %"])
        st.dataframe(rr, use_container_width=True)

# ---------- TAB 5: reviews ----------
with tab5:
    st.subheader("All reviews")
    rev_cols = ["Order Id", "SKU", "Rating", "Review", "Date"]
    rev_up = st.file_uploader("Upload reviews CSV (optional, adds to existing)", type="csv", key="rev")
    reviews = load_csv(REVIEW_FILE, rev_cols)
    if rev_up is not None and st.button("Add uploaded reviews"):
        new = pd.read_csv(rev_up)
        reviews = pd.concat([reviews, new], ignore_index=True).drop_duplicates()
        reviews.to_csv(REVIEW_FILE, index=False)
        st.rerun()

    edited_rev = st.data_editor(reviews, num_rows="dynamic", use_container_width=True, key="rev_editor")
    if st.button("💾 Save reviews"):
        edited_rev.to_csv(REVIEW_FILE, index=False)
        st.success("Reviews updated")
    if "Rating" in edited_rev.columns and len(edited_rev):
        st.metric("Average rating", round(pd.to_numeric(edited_rev["Rating"], errors="coerce").mean(), 2))

# ---------- TAB 6: stock ----------
with tab6:
    st.subheader("Upload stock (multiple CSVs)")
    stock_files = st.file_uploader("Stock CSVs", type="csv", accept_multiple_files=True, key="stock")
    if stock_files:
        sdf = pd.concat([pd.read_csv(f, dtype=str) for f in stock_files], ignore_index=True)
        sdf.columns = [c.strip() for c in sdf.columns]
        a, b = st.columns(2)
        sku_col = a.selectbox("SKU column", sdf.columns)
        qty_col = b.selectbox("Quantity column", sdf.columns, index=min(1, len(sdf.columns) - 1))
        sdf = sdf[[sku_col, qty_col]].rename(columns={sku_col: "SKU", qty_col: "Stock"})
        sdf["SKU"] = sdf["SKU"].map(clean_text)
        sdf["Stock"] = pd.to_numeric(sdf["Stock"], errors="coerce").fillna(0)
        sdf = sdf.groupby("SKU", as_index=False)["Stock"].sum()
        if st.button("💾 Save stock"):
            sdf.to_csv(STOCK_FILE, index=False)
            st.success("Stock saved")

    stock = load_csv(STOCK_FILE, ["SKU", "Stock"])
    if len(stock):
        sold = orders[orders["Status"] != "Cancelled"].groupby("SKU", as_index=False)["Quantity"].sum()
        sold = sold.rename(columns={"Quantity": "Ordered"})
        m = stock.merge(sold, on="SKU", how="outer").fillna(0)
        m["Remaining"] = m["Stock"] - m["Ordered"]
        st.dataframe(m.sort_values("Remaining"), use_container_width=True, hide_index=True)
        low = m[m["Remaining"] <= 5]
        if len(low):
            st.warning(f"{len(low)} SKUs are low or out of stock")  