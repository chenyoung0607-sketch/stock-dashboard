import streamlit as st
import yfinance as yf
import pandas as pd

# 設定網頁標題與佈局
st.set_page_config(page_title="群創操盤儀表板", layout="centered")

# 標題
st.title("📊 群創 (3481) 決策系統")
st.caption("Auto-updated via Python & Yahoo Finance")

# --- 1. 數據抓取區 ---
@st.cache_data(ttl=60) # 設定快取 60 秒，避免頻繁請求
def get_stock_data():
    stock = yf.Ticker("3481.TW")
    # 抓取近一個月資料以計算 9 日指標
    df = stock.history(period="1mo")
    return df

try:
    with st.spinner('正在抓取最新股價...'):
        df = get_stock_data()
        
    # 取得最新一筆與前一筆資料
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    current_price = latest['Close']
    price_change = current_price - prev['Close']
    
    # 計算 9 日高低點 (RSV 用)
    last_9_days = df.iloc[-9:]
    high_9 = last_9_days['High'].max()
    low_9 = last_9_days['Low'].min()
    
except Exception as e:
    st.error(f"資料抓取失敗: {e}")
    st.stop()

# --- 2. 參數設定區 (側邊欄或上方) ---
with st.expander("⚙️ 參數設定 (可手動微調)", expanded=True):
    col1, col2 = st.columns(2)
    # 淨值通常抓不到準的，建議手動設定或寫死
    nav = col1.number_input("每股淨值 (NAV)", value=26.5, step=0.1)
    # 股價允許微調 (以防 API 延遲)
    live_price = col2.number_input("目前股價", value=float(current_price), step=0.05)

# --- 3. 邏輯運算 ---
# P/B Ratio
pb = live_price / nav
pb_score = 0
if pb < 0.6: pb_score = 2
elif pb > 0.85: pb_score = -2
else: pb_score = 1 if pb < 0.75 else -1

# RSV (KD 的 K)
rsv = 50
if high_9 != low_9:
    rsv = ((live_price - low_9) / (high_9 - low_9)) * 100
rsv = max(0, min(100, rsv))

# --- 4. 視覺化呈現 (手機友善介面) ---

# 顯示即時股價
st.metric(label="群創 (3481)", value=f"{live_price}", delta=f"{price_change:.2f}")

st.markdown("---")

# 顯示決策燈號
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("P/B 估值")
    st.write(f"**{pb:.2f}x**")
    if pb < 0.6:
        st.success("🟢 超跌 (Buy)")
    elif pb > 0.85:
        st.error("🔴 昂貴 (Sell)")
    else:
        st.warning("🟡 觀望 (Hold)")

with col_b:
    st.subheader("9日動能")
    st.write(f"位置: **{rsv:.1f}%**")
    if rsv < 20:
        st.success("🟢 低檔鈍化")
    elif rsv > 80:
        st.error("🔴 高檔過熱")
    else:
        st.warning("🟡 中性震盪")

st.markdown("---")

# 最終建議
st.subheader("經理人評級")
final_score = pb_score + (1 if rsv < 20 else (-1 if rsv > 80 else 0))

if final_score >= 2:
    st.balloons() # 噴氣球特效
    st.error("## 🔥 強力買進 (STRONG BUY)") # Streamlit 的 error 是紅色，適合台股漲
    st.write("估值便宜且位於技術低檔")
elif final_score <= -2:
    st.success("## 🌲 建議賣出 (SELL)") # 台股跌是綠色
    st.write("估值過高或短線過熱")
else:
    st.info("## 👀 觀望 (WAIT)")

# 顯示數據表格
st.caption("近期 9 日數據：")
st.dataframe(last_9_days[['Open', 'High', 'Low', 'Close']].sort_index(ascending=False))