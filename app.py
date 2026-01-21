import streamlit as st
import yfinance as yf
import pandas as pd
import math

# --- 設定網頁與樣式 ---
st.set_page_config(page_title="台股行動戰情室", layout="centered", page_icon="📈")

# 【修正重點】CSS 樣式表
# 改用 rgba 半透明背景，自動適應深色/淺色模式，並增加邊框讓它更明顯
st.markdown("""
    <style>
    /* 修正：針對 Metric 卡片使用半透明背景，解決深色模式文字看不見的問題 */
    div[data-testid="stMetric"] {
        background-color: rgba(255, 255, 255, 0.05); /* 微透明背景 */
        border: 1px solid rgba(255, 255, 255, 0.1);  /* 微透明邊框 */
        padding: 15px;
        border-radius: 10px;
    }
    
    /* 讓漲停顯示紅色，跌停顯示綠色 (台股習慣) */
    .limit-up { color: #ff4b4b; font-weight: bold; font-size: 1.2em; }
    .limit-down { color: #09ab3b; font-weight: bold; font-size: 1.2em; }
    
    /* 調整標題間距 */
    .css-10trblm { margin-top: -2rem; }
    </style>
    """, unsafe_allow_html=True)

# --- 核心邏輯函數 ---

# 1. 台股升降單位 (Tick) 判斷
def get_tick_size(price):
    if price < 10: return 0.01
    if price < 50: return 0.05
    if price < 100: return 0.1
    if price < 500: return 0.5
    if price < 1000: return 1.0
    return 5.0

# 2. 計算漲跌停價
def calculate_limits(prev_close):
    tick = get_tick_size(prev_close)
    
    # 漲停：無條件捨去
    raw_up = prev_close * 1.10
    up_tick = get_tick_size(raw_up) 
    limit_up = math.floor(raw_up / up_tick) * up_tick
    
    # 跌停：無條件進位
    raw_down = prev_close * 0.90
    down_tick = get_tick_size(raw_down)
    limit_down = math.ceil(raw_down / down_tick) * down_tick
    
    return limit_up, limit_down

# --- 側邊欄設定 ---
with st.sidebar:
    st.header("⚙️ 設定")
    ticker_input = st.text_input("股票代號", value="3481.TW").upper()
    nav_input = st.number_input("每股淨值 (NAV)", value=26.5, step=0.1, help="請查閱最新財報")
    st.info("輸入代號後按 Enter 更新")

# --- 主程式 ---
st.title(f"📊 {ticker_input.replace('.TW', '')} 決策儀表板")

try:
    with st.spinner('連線 Yahoo Finance 抓取中...'):
        stock = yf.Ticker(ticker_input)
        hist = stock.history(period="3mo")
        
        if hist.empty:
            st.error(f"找不到 {ticker_input} 資料，請確認代號 (需加 .TW)")
            st.stop()

        latest = hist.iloc[-1]
        prev = hist.iloc[-2]
        
        current_price = latest['Close']
        prev_close = prev['Close']
        price_change = current_price - prev_close
        
        limit_up, limit_down = calculate_limits(prev_close)
        
        # 計算均線
        hist['MA5'] = hist['Close'].rolling(window=5).mean()
        hist['MA20'] = hist['Close'].rolling(window=20).mean()
        hist['MA60'] = hist['Close'].rolling(window=60).mean()
        
        ma5 = hist['MA5'].iloc[-1]
        ma20 = hist['MA20'].iloc[-1]
        ma60 = hist['MA60'].iloc[-1]

        # 計算 RSV
        last_9 = hist.iloc[-9:]
        high_9 = last_9['High'].max()
        low_9 = last_9['Low'].min()
        rsv = 50
        if high_9 != low_9:
            rsv = ((current_price - low_9) / (high_9 - low_9)) * 100

except Exception as e:
    st.error(f"發生錯誤: {e}")
    st.stop()

# --- 1. 價格與漲跌停區 ---
col1, col2 = st.columns([1.5, 1])

with col1:
    st.metric("目前股價", f"{current_price:.2f}", f"{price_change:.2f}")

with col2:
    st.markdown(f"🔥 漲停: <span class='limit-up'>{limit_up:.2f}</span>", unsafe_allow_html=True)
    st.markdown(f"🌲 跌停: <span class='limit-down'>{limit_down:.2f}</span>", unsafe_allow_html=True)
    st.caption(f"昨收: {prev_close}")

st.divider()

# --- 2. 技術指標快篩 ---
st.subheader("📈 技術指標 (Trend)")
c1, c2, c3 = st.columns(3)

def get_status(price, ma):
    if pd.isna(ma): return "計算中"
    return "🔴 站上" if price > ma else "🟢 跌破"

with c1:
    st.metric("MA5 (週)", f"{ma5:.2f}")
    st.caption(get_status(current_price, ma5))
with c2:
    st.metric("MA20 (月)", f"{ma20:.2f}")
    st.caption(get_status(current_price, ma20))
with c3:
    st.metric("MA60 (季)", f"{ma60:.2f}")
    st.caption(get_status(current_price, ma60))

# --- 3. 經理人估值邏輯 ---
st.divider()
st.subheader("💼 經理人估值 (Valuation)")

pb = current_price / nav_input
col_a, col_b = st.columns(2)

with col_a:
    st.write("#### 股價淨值比 P/B")
    st.write(f"**{pb:.2f}倍**")
    if pb < 0.6: st.error("★ 歷史超跌 (Buy)")
    elif pb > 0.85: st.success("★ 壓力區 (Sell)")
    else: st.warning("合理區間")

with col_b:
    st.write("#### 短線動能 (RSV)")
    st.write(f"**{rsv:.1f}%**")
    if rsv < 20: st.error("低檔鈍化 (反彈機會)")
    elif rsv > 80: st.success("高檔過熱 (拉回風險)")
    else: st.warning("中性震盪")

# --- 4. 歷史走勢圖 ---
st.line_chart(hist[['Close', 'MA20']])