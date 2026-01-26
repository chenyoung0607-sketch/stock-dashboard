import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import math
import requests
import datetime
import time

# --- 設定網頁與樣式 ---
st.set_page_config(page_title="台股全方位戰情室", layout="wide", page_icon="📈")

# CSS 樣式優化
st.markdown("""
    <style>
    /* Metric 卡片樣式 */
    div[data-testid="stMetric"] {
        background-color: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 10px;
        border-radius: 8px;
    }
    
    /* 漲跌顏色定義 (台股紅漲綠跌) */
    .trend-up { color: #ff4b4b; font-weight: bold; }
    .trend-down { color: #09ab3b; font-weight: bold; }
    .trend-neutral { color: #888888; }
    
    /* 標籤樣式 */
    .badge-bull { background-color: rgba(255, 75, 75, 0.2); color: #ff4b4b; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
    .badge-bear { background-color: rgba(9, 171, 59, 0.2); color: #09ab3b; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
    </style>
    """, unsafe_allow_html=True)

# --- 核心邏輯函數 ---

# 0. 籌碼面爬蟲 (抓取證交所最新資料)
@st.cache_data(ttl=3600)  # 設定快取 1 小時
def get_twse_chips(stock_id):
    stock_id = stock_id.replace(".TW", "") 
    date_cursor = datetime.datetime.now()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    # 最多回推 5 天找交易日
    for i in range(5):
        date_str = date_cursor.strftime('%Y%m%d')
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALL&response=json"
        
        try:
            res = requests.get(url, headers=headers, timeout=5)
            data = res.json()
            if data['stat'] == 'OK':
                for row in data['data']:
                    if row[0] == stock_id:
                        return {
                            "date": date_cursor.strftime('%Y-%m-%d'),
                            "foreign": int(row[4].replace(',', '')) // 1000,
                            "trust": int(row[10].replace(',', '')) // 1000,
                            "dealer": int(row[11].replace(',', '')) // 1000,
                            "found": True
                        }
        except: pass
        date_cursor -= datetime.timedelta(days=1)
        time.sleep(1)
    return {"found": False}

# 1. 計算技術指標 (KD, MACD, RSI, MA)
def calculate_indicators(df):
    df = df.sort_index()
    # MA
    for days in [5, 10, 20, 60]:
        df[f'MA{days}'] = df['Close'].rolling(window=days).mean()
    
    # KD (9, 3, 3)
    rsv_period = 9
    df['Low_9'] = df['Low'].rolling(window=rsv_period).min()
    df['High_9'] = df['High'].rolling(window=rsv_period).max()
    df['RSV'] = 100 * (df['Close'] - df['Low_9']) / (df['High_9'] - df['Low_9'])
    df['RSV'] = df['RSV'].fillna(50)
    
    k_values, d_values = [50], [50]
    rsv_list = df['RSV'].tolist()
    for i in range(1, len(rsv_list)):
        k = (2/3) * k_values[-1] + (1/3) * rsv_list[i]
        d = (2/3) * d_values[-1] + (1/3) * k
        k_values.append(k)
        d_values.append(d)
    df['K'], df['D'] = k_values, d_values
    
    # MACD (12, 26, 9)
    exp12 = df['Close'].ewm(span=12, adjust=False).mean()
    exp26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = exp12 - exp26
    df['MACD_Signal'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['DIF'] - df['MACD_Signal']
    
    # RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Bias
    df['Bias_20'] = ((df['Close'] - df['MA20']) / df['MA20']) * 100
    df['Bias_60'] = ((df['Close'] - df['MA60']) / df['MA60']) * 100

    return df

# 2. K線型態識別
def identify_patterns(row, prev_row):
    signals = []
    body = abs(row['Close'] - row['Open'])
    total_len = row['High'] - row['Low']
    
    if total_len > 0 and body <= total_len * 0.1:
        signals.append("十字線 (變盤訊號)")
        
    if (prev_row['Close'] < prev_row['Open']) and (row['Close'] > row['Open']): 
        if row['Open'] < prev_row['Close'] and row['Close'] > prev_row['Open']:
            signals.append("🔥 多頭吞噬 (強烈買訊)")
            
    if (prev_row['Close'] > prev_row['Open']) and (row['Close'] < row['Open']): 
        if row['Open'] > prev_row['Close'] and row['Close'] < prev_row['Open']:
            signals.append("🌲 空頭吞噬 (賣出訊號)")
            
    return signals

# 3. 漲跌停計算
def get_tick_size(price):
    if price < 10: return 0.01
    if price < 50: return 0.05
    if price < 100: return 0.1
    if price < 500: return 0.5
    else: return 1.0

def calculate_limits(prev_close):
    tick = get_tick_size(prev_close)
    raw_up = prev_close * 1.10
    limit_up = math.floor(raw_up / get_tick_size(raw_up)) * get_tick_size(raw_up)
    raw_down = prev_close * 0.90
    limit_down = math.ceil(raw_down / get_tick_size(raw_down)) * get_tick_size(raw_down)
    return limit_up, limit_down

# --- 側邊欄 ---
with st.sidebar:
    st.header("⚙️ 股票設定")
    ticker_input = st.text_input("股票代號", value="3481.TW").upper()
    st.caption("輸入代號後按 Enter 更新 (如 2330.TW)")

# --- 主程式 ---
st.title(f"📊 {ticker_input.replace('.TW', '')} 戰情儀表板")

try:
    with st.spinner('AI 正在分析大數據...'):
        stock = yf.Ticker(ticker_input)
        hist = stock.history(period="1y")
        
        if hist.empty:
            st.error("找不到資料，請確認代號。")
            st.stop()
            
        df = calculate_indicators(hist)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_price = latest['Close']
        price_change = current_price - prev['Close']
        pct_change = (price_change / prev['Close']) * 100
        limit_up, limit_down = calculate_limits(prev['Close'])
        patterns = identify_patterns(latest, prev)

except Exception as e:
    st.error(f"發生錯誤: {e}")
    st.stop()

# Row 1: 核心報價
col1, col2, col3 = st.columns([1.5, 1, 1.5])
with col1:
    st.metric("目前股價", f"{current_price:.2f}", f"{price_change:.2f} ({pct_change:.2f}%)")
with col2:
    st.markdown(f"**🔥 漲停**: <span class='trend-up'>{limit_up:.2f}</span>", unsafe_allow_html=True)
    st.markdown(f"**🌲 跌停**: <span class='trend-down'>{limit_down:.2f}</span>", unsafe_allow_html=True)
with col3:
    st.write("#### K線訊號")
    if patterns:
        for p in patterns: st.write(f"👉 **{p}**")
    else: st.caption("無特殊反轉型態")

st.divider()

# Row 2: 技術指標儀表板 (含教學)
st.subheader("🛠 技術指標深度分析")
tab1, tab2, tab3, tab4 = st.tabs(["均線與趨勢", "KD 與 RSI", "MACD 動能", "籌碼透視"])

# Tab 1: 均線
with tab1:
    st.info("💡 **均線 (MA)**：代表過去 N 天大家的平均成本。")
    c1, c2, c3, c4 = st.columns(4)
    
    ma_trend = "盤整"
    if latest['MA5'] > latest['MA20'] > latest['MA60']: ma_trend = "🐂 多頭排列 (強勢)"
    elif latest['MA5'] < latest['MA20'] < latest['MA60']: ma_trend = "🐻 空頭排列 (弱勢)"
    st.write(f"**目前趨勢：{ma_trend}**")

    with c1: st.metric("MA5 (週)", f"{latest['MA5']:.2f}")
    with c2: st.metric("MA10 (雙週)", f"{latest['MA10']:.2f}")
    with c3: st.metric("MA20 (月)", f"{latest['MA20']:.2f}", f"乖離 {latest['Bias_20']:.2f}%")
    with c4: st.metric("MA60 (季)", f"{latest['MA60']:.2f}", f"乖離 {latest['Bias_60']:.2f}%")
    
    st.line_chart(df[['Close', 'MA5', 'MA20', 'MA60']].iloc[-120:], color=["#ffffff", "#ffff00", "#ff00ff", "#00ffff"])
    
    with st.expander("📚 教學：如何看懂均線與乖離率？"):
        st.markdown("""
        * **多頭排列**：短天期 > 長天期 (如 5日 > 20日 > 60日)，代表短期買氣強，適合順勢操作。
        * **空頭排列**：短天期 < 長天期，代表上面全是套牢賣壓，反彈易受阻。
        * **乖離率 (Bias)**：股價與均線的距離。
            * **正乖離過大**：股價衝太快，容易拉回 (獲利了結)。
            * **負乖離過大**：股價跌太深，容易反彈 (搶短)。
        """)

# Tab 2: KD & RSI
with tab2:
    col_kd, col_rsi = st.columns(2)
    with col_kd:
        st.write("#### KD 指標 (9,3,3)")
        st.write(f"K: **{latest['K']:.2f}** | D: **{latest['D']:.2f}**")
        if latest['K'] > 80: st.warning("⚠️ 超買區 (>80)")
        elif latest['K'] < 20: st.success("✅ 超賣區 (<20)")
        
        if latest['K'] > latest['D'] and prev['K'] < prev['D']:
            st.markdown("<span class='badge-bull'>黃金交叉 (買進)</span>", unsafe_allow_html=True)
        elif latest['K'] < latest['D'] and prev['K'] > prev['D']:
            st.markdown("<span class='badge-bear'>死亡交叉 (賣出)</span>", unsafe_allow_html=True)
            
    with col_rsi:
        st.write("#### RSI (14)")
        st.metric("RSI 強弱", f"{latest['RSI']:.2f}")
        if latest['RSI'] > 70: st.warning("🔥 過熱區 (隨時可能拉回)")
        elif latest['RSI'] < 30: st.success("❄️ 超跌區 (隨時可能反彈)")
        
    with st.expander("📚 教學：什麼是 KD 與 RSI？"):
        st.markdown("""
        * **KD 指標**：判斷短線轉折最靈敏的指標。
            * **黃金交叉**：K 值由下往上穿過 D 值，視為買點。
            * **鈍化**：當 K 值連續 3 天在 80 以上 (高檔鈍化)，代表趨勢極強，不要亂放空；反之為低檔鈍化。
        * **RSI (相對強弱指標)**：
            * **> 70**：買盤過熱，可能回檔。
            * **< 30**：賣盤過度，可能反彈。
            * **50**：多空分界線，50 以上屬強勢區。
        """)

# Tab 3: MACD
with tab3:
    osc = latest['MACD_Hist']
    c_m1, c_m2 = st.columns([1, 2])
    with c_m1:
        st.metric("OSC (柱狀圖)", f"{osc:.2f}")
        if osc > 0 and prev['MACD_Hist'] < 0: st.success("MACD 翻紅 (轉強)")
        elif osc < 0 and prev['MACD_Hist'] > 0: st.error("MACD 翻綠 (轉弱)")
    with c_m2:
        st.bar_chart(df[['MACD_Hist']].iloc[-60:])
        
    with st.expander("📚 教學：MACD 波段操作法"):
        st.markdown("""
        * **MACD**：適合判斷中長線趨勢，比 KD 慢但穩定。
        * **柱狀圖 (OSC)**：
            * **由負轉正 (翻紅)**：空頭力道耗盡，多頭開始控盤 (波段買點)。
            * **由正轉負 (翻綠)**：多頭力道耗盡，空頭開始控盤 (波段賣點)。
        * **0 軸**：MACD 在 0 軸以上為多頭市場，0 軸以下為空頭市場。
        """)

# Tab 4: 籌碼
with tab4:
    st.subheader("🏦 三大法人動向")
    chip_data = get_twse_chips(ticker_input)
    
    if chip_data.get("found"):
        st.caption(f"資料日期: {chip_data['date']} (單位: 張)")
        c1, c2, c3 = st.columns(3)
        with c1: st.metric("外資", f"{chip_data['foreign']:,}")
        with c2: st.metric("投信", f"{chip_data['trust']:,}")
        with c3: st.metric("自營商", f"{chip_data['dealer']:,}")
    else:
        st.warning("⚠️ 無法取得籌碼資料 (可能是盤中或假日)")
        
    with st.expander("📚 教學：誰是主力？"):
        st.markdown("""
        * **外資 (Foreign)**：資金部位最大，通常操作權值股 (如台積電、群創)，趨勢延續性強。外資連續買超是波段大漲的保證。
        * **投信 (Trust)**：國內基金經理人。喜歡操作中小型股，季底會有「作帳行情」。
        * **自營商 (Dealer)**：券商自己的錢，操作偏短線，參考價值較低。
        """)

st.markdown("---")
st.caption("⚠️ 免責聲明：本工具僅供教學與研究，投資盈虧自負。")