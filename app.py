import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import math
import requests
import datetime
import time


# --- 設定網頁與樣式 ---
st.set_page_config(page_title="戰情室", layout="wide", page_icon="📈")
# --- 新增：籌碼面爬蟲 (抓取證交所最新資料) ---
@st.cache_data(ttl=3600)  # 設定快取 1 小時，避免頻繁請求被證交所封鎖
def get_twse_chips(stock_id):
    """
    抓取最近一交易日的三大法人與融資券數據
    """
    stock_id = stock_id.replace(".TW", "") # 去除 .TW
    
    # 嘗試回推最近 5 天 (尋找最近的交易日)
    date_cursor = datetime.datetime.now()
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    # 最多嘗試回推 5 天 (避開週末假日)
    for i in range(5):
        date_str = date_cursor.strftime('%Y%m%d')
        # 1. 抓取三大法人 (T86)
        url_investors = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALL&response=json"
        
        try:
            res = requests.get(url_investors, headers=headers, timeout=5)
            data = res.json()
            
            if data['stat'] == 'OK':
                # 找到該股票的資料
                # 格式通常為: [代號, 名稱, 外資買進, 外資賣出, 外資買賣超, ..., 投信..., 自營商...]
                # 注意：欄位索引可能會變，這裡抓取常見位置 (依據 TWSE 現行格式)
                for row in data['data']:
                    if row[0] == stock_id:
                        # 整理數據 (外資=4, 投信=10, 自營商=11(合計)) *索引須視證交所格式微調，此為經驗值
                        foreign_net = int(row[4].replace(',', '')) // 1000 # 換算成張
                        trust_net = int(row[10].replace(',', '')) // 1000
                        dealer_net = int(row[11].replace(',', '')) // 1000
                        
                        return {
                            "date": date_cursor.strftime('%Y-%m-%d'),
                            "foreign": foreign_net, # 外資
                            "trust": trust_net,     # 投信
                            "dealer": dealer_net,   # 自營商
                            "found": True
                        }
        except Exception as e:
            print(f"Error fetching {date_str}: {e}")
            pass
        
        # 往回推一天
        date_cursor -= datetime.timedelta(days=1)
        time.sleep(1) # 禮貌性延遲

    return {"found": False, "msg": "近期無資料或連線失敗"}
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

# 1. 計算技術指標 (KD, MACD, RSI, MA)
def calculate_indicators(df):
    # 確保資料按時間排序
    df = df.sort_index()
    
    # --- 移動平均線 (MA) ---
    for days in [5, 10, 20, 60]:
        df[f'MA{days}'] = df['Close'].rolling(window=days).mean()
    
    # --- KD 指標 (台股參數 9, 3, 3) ---
    # RSV 計算
    rsv_period = 9
    df['Low_9'] = df['Low'].rolling(window=rsv_period).min()
    df['High_9'] = df['High'].rolling(window=rsv_period).max()
    df['RSV'] = 100 * (df['Close'] - df['Low_9']) / (df['High_9'] - df['Low_9'])
    df['RSV'] = df['RSV'].fillna(50)
    
    # K, D 值平滑運算 (迭代計算)
    k_values = [50] # 初始值
    d_values = [50]
    rsv_list = df['RSV'].tolist()
    
    for i in range(1, len(rsv_list)):
        # K = 2/3 * Prev_K + 1/3 * RSV
        k = (2/3) * k_values[-1] + (1/3) * rsv_list[i]
        # D = 2/3 * Prev_D + 1/3 * K
        d = (2/3) * d_values[-1] + (1/3) * k
        k_values.append(k)
        d_values.append(d)
        
    df['K'] = k_values
    df['D'] = d_values
    
    # --- MACD (12, 26, 9) ---
    exp12 = df['Close'].ewm(span=12, adjust=False).mean()
    exp26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = exp12 - exp26
    df['MACD_Signal'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['DIF'] - df['MACD_Signal']
    
    # --- RSI (14) ---
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # --- 乖離率 (Bias) ---
    df['Bias_20'] = ((df['Close'] - df['MA20']) / df['MA20']) * 100
    df['Bias_60'] = ((df['Close'] - df['MA60']) / df['MA60']) * 100

    return df

# 2. K線型態識別
def identify_patterns(row, prev_row):
    signals = []
    
    # 實體與影線計算
    body = abs(row['Close'] - row['Open'])
    upper_shadow = row['High'] - max(row['Close'], row['Open'])
    lower_shadow = min(row['Close'], row['Open']) - row['Low']
    total_len = row['High'] - row['Low']
    
    # A. 十字線 (Doji): 實體極小
    if total_len > 0 and body <= total_len * 0.1:
        signals.append("十字線 (變盤訊號)")
        
    # B. 吞噬 (Engulfing)
    # 多頭吞噬 (Bullish Engulfing): 昨跌今漲，且今日實體包覆昨日實體
    if (prev_row['Close'] < prev_row['Open']) and (row['Close'] > row['Open']): # 昨綠今紅
        if row['Open'] < prev_row['Close'] and row['Close'] > prev_row['Open']:
            signals.append("🔥 多頭吞噬 (強烈買訊)")
            
    # 空頭吞噬 (Bearish Engulfing): 昨漲今跌，且今日實體包覆昨日實體
    if (prev_row['Close'] > prev_row['Open']) and (row['Close'] < row['Open']): # 昨紅今綠
        if row['Open'] > prev_row['Close'] and row['Close'] < prev_row['Open']:
            signals.append("🌲 空頭吞噬 (賣出訊號)")
            
    # C. 鎚頭/吊人 (Hammer/Hanging Man)
    if total_len > 0 and lower_shadow > body * 2 and upper_shadow < body * 0.5:
        if row['Close'] < row['Open']: signals.append("吊人線 (高檔需慎)")
        else: signals.append("鎚頭線 (低檔支撐)")
        
    return signals

# 3. 漲跌停計算 (維持原邏輯)
def get_tick_size(price):
    if price < 10: return 0.01
    if price < 50: return 0.05
    if price < 100: return 0.1
    if price < 500: return 0.5
    if price < 1000: return 1.0
    return 5.0

def calculate_limits(prev_close):
    tick = get_tick_size(prev_close)
    raw_up = prev_close * 1.10
    up_tick = get_tick_size(raw_up) 
    limit_up = math.floor(raw_up / up_tick) * up_tick
    
    raw_down = prev_close * 0.90
    down_tick = get_tick_size(raw_down)
    limit_down = math.ceil(raw_down / down_tick) * down_tick
    return limit_up, limit_down

# --- 側邊欄設定 ---
with st.sidebar:
    st.header("⚙️ 股票設定")
    ticker_input = st.text_input("股票代號", value="3481.TW").upper()
    
    st.divider()
    st.caption("說明：數據來自 Yahoo Finance，延遲約 15 分鐘。")
    st.info("輸入代號後按 Enter 更新")

# --- 主程式 ---
st.title(f"📊 {ticker_input.replace('.TW', '')} 戰情儀表板")

try:
    with st.spinner('正在進行深度技術分析...'):
        # 1. 抓取較長歷史資料以計算長期均線 (至少1年)
        stock = yf.Ticker(ticker_input)
        hist = stock.history(period="1y")
        
        if hist.empty:
            st.error(f"找不到 {ticker_input} 資料，請確認代號 (台股需加 .TW)")
            st.stop()
            
        # 2. 計算所有指標
        df = calculate_indicators(hist)
        
        # 3. 取得最新數據
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_price = latest['Close']
        price_change = current_price - prev['Close']
        pct_change = (price_change / prev['Close']) * 100
        
        limit_up, limit_down = calculate_limits(prev['Close'])
        
        # 4. 取得型態訊號
        patterns = identify_patterns(latest, prev)

except Exception as e:
    st.error(f"發生錯誤: {e}")
    st.stop()

# --- 版面配置 ---

# Row 1: 核心報價
col1, col2, col3 = st.columns([1.5, 1, 1.5])

with col1:
    st.metric("目前股價", f"{current_price:.2f}", f"{price_change:.2f} ({pct_change:.2f}%)")

with col2:
    st.write("#### 區間")
    st.markdown(f"🔥 <span class='trend-up'>{limit_up:.2f}</span>", unsafe_allow_html=True)
    st.markdown(f"🌲 <span class='trend-down'>{limit_down:.2f}</span>", unsafe_allow_html=True)

with col3:
    st.write("#### K線型態訊號")
    if patterns:
        for p in patterns:
            st.write(f"👉 **{p}**")
    else:
        st.caption("無特殊反轉型態")

st.divider()

# Row 2: 技術指標儀表板
st.subheader("🛠 技術指標健檢")
tab1, tab2, tab3 , tab4= st.tabs(["均線與趨勢", "KD 與 RSI", "MACD 動能", "籌碼透視 (法人/融資)"])

# Tab 1: 均線系統
with tab1:
    c1, c2, c3, c4 = st.columns(4)
    
    # 判斷多頭/空頭排列
    ma_trend = "盤整"
    if latest['MA5'] > latest['MA20'] > latest['MA60']:
        ma_trend = "🐂 多頭排列"
    elif latest['MA5'] < latest['MA20'] < latest['MA60']:
        ma_trend = "🐻 空頭排列"
        
    st.markdown(f"**目前趨勢：{ma_trend}**")
    
    def ma_metric(label, val, bias):
        color = "red" if bias > 0 else "green"
        return st.metric(label, f"{val:.2f}", f"乖離 {bias:.2f}%", delta_color="off")

    with c1: ma_metric("MA5 (週)", latest['MA5'], (current_price/latest['MA5']-1)*100)
    with c2: ma_metric("MA10 (雙週)", latest['MA10'], (current_price/latest['MA10']-1)*100)
    with c3: ma_metric("MA20 (月)", latest['MA20'], latest['Bias_20'])
    with c4: ma_metric("MA60 (季)", latest['MA60'], latest['Bias_60'])
    
    # 繪製均線圖
    chart_data = df[['Close', 'MA5', 'MA20', 'MA60']].iloc[-120:] # 只看近半年
    st.line_chart(chart_data, color=["#ffffff", "#ffff00", "#ff00ff", "#00ffff"])

# Tab 2: KD & RSI
with tab2:
    k_val, d_val = latest['K'], latest['D']
    rsi_val = latest['RSI']
    
    col_kd, col_rsi = st.columns(2)
    
    with col_kd:
        st.write(f"#### KD 指標 (9,3,3)")
        st.write(f"K: **{k_val:.2f}** | D: **{d_val:.2f}**")
        
        # KD 判讀邏輯
        if k_val > 80: st.warning("⚠️ KD 超買區 (可能拉回)")
        elif k_val < 20: st.success("✅ KD 超賣區 (醞釀反彈)")
        
        if k_val > d_val and prev['K'] < prev['D']:
            st.markdown("<span class='badge-bull'>黃金交叉 (買進訊號)</span>", unsafe_allow_html=True)
        elif k_val < d_val and prev['K'] > prev['D']:
            st.markdown("<span class='badge-bear'>死亡交叉 (賣出訊號)</span>", unsafe_allow_html=True)
            
    with col_rsi:
        st.write(f"#### RSI (14)")
        st.metric("RSI 強弱", f"{rsi_val:.2f}")
        if rsi_val > 70: st.warning("過熱 (>70)")
        elif rsi_val < 30: st.success("超跌 (<30)")
        else: st.info("中性區間")

# Tab 3: MACD
with tab3:
    dif, macd_sig, osc = latest['DIF'], latest['MACD_Signal'], latest['MACD_Hist']
    
    c_m1, c_m2 = st.columns([1, 2])
    with c_m1:
        st.write("#### 數值")
        st.write(f"DIF: {dif:.2f}")
        st.write(f"MACD: {macd_sig:.2f}")
        st.write(f"OSC (柱狀): {osc:.2f}")
        
        if osc > 0 and prev['MACD_Hist'] < 0:
            st.success("MACD 翻紅 (轉強)")
        elif osc < 0 and prev['MACD_Hist'] > 0:
            st.error("MACD 翻綠 (轉弱)")
            
    with c_m2:
        # 簡單模擬 MACD 柱狀圖 (Streamlit 原生圖表限制較多，這裡用 Bar chart 示意)
        macd_data = df[['MACD_Hist']].iloc[-60:]
        st.bar_chart(macd_data)
        st.caption("近 60 日 MACD 柱狀圖變化")
# 新增 Tab 4

with tab4: # 或者直接寫 st.header("籌碼透視")
    st.subheader("🏦 三大法人動向 (最新交易日快照)")
    
    # 呼叫爬蟲
    chip_data = get_twse_chips(ticker_input)
    
    if chip_data.get("found"):
        st.caption(f"資料日期: {chip_data['date']} (單位: 張)")
        
        col_f, col_t, col_d = st.columns(3)
        
        def color_metric(val):
            return "normal" # Streamlit 會自動處理正負紅綠
            
        with col_f:
            st.metric("外資 (Foreign)", f"{chip_data['foreign']:,} 張", delta=chip_data['foreign'])
        with col_t:
            st.metric("投信 (Trust)", f"{chip_data['trust']:,} 張", delta=chip_data['trust'])
        with col_d:
            st.metric("自營商 (Dealer)", f"{chip_data['dealer']:,} 張", delta=chip_data['dealer'])
            
        # 簡易解讀邏輯
        st.markdown("---")
        st.markdown("#### 🤖 AI 籌碼解讀")
        
        score = 0
        reasons = []
        
        if chip_data['foreign'] > 1000:
            reasons.append("★ **外資大買**：國際資金進駐，趨勢有利多方。")
            score += 2
        elif chip_data['foreign'] < -1000:
            reasons.append("⚠️ **外資大賣**：提款壓力大，需留意權值股修正。")
            score -= 2
            
        if chip_data['trust'] > 0:
            reasons.append("★ **投信買超**：內資作帳或認養，中小型股易有表現。")
            score += 1
        elif chip_data['trust'] < 0:
            reasons.append("⚠️ **投信結帳**：內資獲利了結。")
            score -= 1
            
        if score > 0:
            st.success(f"籌碼偏多 (分數 {score})：{' '.join(reasons)}")
        elif score < 0:
            st.error(f"籌碼偏空 (分數 {score})：{' '.join(reasons)}")
        else:
            st.warning("籌碼中性：法人多空互抵或觀望。")
            
    else:
        st.warning("無法取得籌碼資料，可能是盤中尚未更新或證交所連線忙碌中。")
# --- 頁尾 ---
st.markdown("---")
st.caption("⚠️ 免責聲明：本工具僅供技術分析研究，不代表投資建議。股市有風險，投資需謹慎。")