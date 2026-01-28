import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import math
import requests
import datetime
import time

# --- 1. 初始化與樣式設定 ---
st.set_page_config(page_title="台股全方位戰情室", layout="wide", page_icon="📈")

st.markdown("""
    <style>
    div[data-testid="stMetric"] {
        background-color: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 10px;
        border-radius: 8px;
    }
    .trend-up { color: #ff4b4b; font-weight: bold; }
    .trend-down { color: #09ab3b; font-weight: bold; }
    .badge-bull { background-color: rgba(255, 75, 75, 0.2); color: #ff4b4b; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
    .badge-bear { background-color: rgba(9, 171, 59, 0.2); color: #09ab3b; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心數據函數 ---

# [新增] 從 secrets 讀取 Token 並抓取 FinMind 估值資料
@st.cache_data(ttl=3600)
def get_finmind_indicators(stock_id):
    stock_id = stock_id.replace(".TW", "")
    # 從 st.secrets 自動讀取，不需要手動輸入
    try:
        token = st.secrets["FINMIND_TOKEN"]
    except:
        return pd.DataFrame(), "未偵測到 Secrets 設定"

    url = "https://api.finmindtrade.com/api/v4/data"
    start_date = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
    
    params = {
        "dataset": "TaiwanStockPER",
        "data_id": stock_id,
        "start_date": start_date,
        "token": token,
    }
    
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if data['msg'] == 'success':
            df_fm = pd.DataFrame(data['data'])
            df_fm['date'] = pd.to_datetime(df_fm['date'])
            df_fm.set_index('date', inplace=True)
            return df_fm, "OK"
    except Exception as e:
        return pd.DataFrame(), str(e)
    return pd.DataFrame(), "無資料回傳"

@st.cache_data(ttl=3600)
def get_twse_chips(stock_id):
    stock_id = stock_id.replace(".TW", "") 
    date_cursor = datetime.datetime.now()
    headers = {'User-Agent': 'Mozilla/5.0'}
    for i in range(5):
        date_str = date_cursor.strftime('%Y%m%d')
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALL&response=json"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            data = res.json()
            if data['stat'] == 'OK':
                for row in data['data']:
                    if row[0] == stock_id:
                        return {"date": date_cursor.strftime('%Y-%m-%d'), "foreign": int(row[4].replace(',', '')) // 1000, "trust": int(row[10].replace(',', '')) // 1000, "dealer": int(row[11].replace(',', '')) // 1000, "found": True}
        except: pass
        date_cursor -= datetime.timedelta(days=1)
    return {"found": False}

def calculate_indicators(df):
    df = df.sort_index()
    for days in [5, 10, 20, 60]:
        df[f'MA{days}'] = df['Close'].rolling(window=days).mean()
    # KD
    df['Low_9'] = df['Low'].rolling(window=9).min()
    df['High_9'] = df['High'].rolling(window=9).max()
    df['RSV'] = 100 * (df['Close'] - df['Low_9']) / (df['High_9'] - df['Low_9'])
    k, d = [50], [50]
    for r in df['RSV'].fillna(50).tolist()[1:]:
        k.append((2/3) * k[-1] + (1/3) * r)
        d.append((2/3) * d[-1] + (1/3) * k[-1])
    df['K'], df['D'] = k, d
    # MACD
    exp12 = df['Close'].ewm(span=12, adjust=False).mean()
    exp26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = exp12 - exp26
    df['MACD_Signal'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['DIF'] - df['MACD_Signal']
    # RSI & Bias
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + gain/loss))
    df['Bias_20'] = ((df['Close'] - df['MA20']) / df['MA20']) * 100
    return df

def get_tick_size(price):
    if price < 10: return 0.01
    if price < 50: return 0.05
    if price < 100: return 0.1
    if price < 500: return 0.5
    return 1.0

def calculate_limits(prev_close):
    tick = get_tick_size(prev_close)
    limit_up = math.floor((prev_close * 1.10) / tick) * tick
    limit_down = math.ceil((prev_close * 0.90) / tick) * tick
    return limit_up, limit_down

# --- 3. 側邊欄 ---
with st.sidebar:
    st.header("⚙️ 股票設定")
    ticker_input = st.text_input("股票代號", value="2330.TW").upper()
    st.caption("自動從 secrets.toml 讀取 FinMind Token")
    st.divider()
    st.info("💡 貼心提醒：若更換 Token 需重啟或清除快取")

# --- 4. 主程式 UI ---
st.title(f"📊 {ticker_input.replace('.TW', '')} 全方位戰情儀表板")

try:
    stock = yf.Ticker(ticker_input)
    hist = stock.history(period="1y")
    if hist.empty:
        st.error("找不到資料，請確認代號。")
        st.stop()
        
    df = calculate_indicators(hist)
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    limit_up, limit_down = calculate_limits(prev['Close'])

    # Row 1: 核心指標
    c1, c2, c3 = st.columns(3)
    c1.metric("目前股價", f"{latest['Close']:.2f}", f"{latest['Close']-prev['Close']:.2f} ({(latest['Close']-prev['Close'])/prev['Close']*100:.2f}%)")
    c2.metric("漲停價", f"{limit_up:.2f}")
    c3.metric("跌停價", f"{limit_down:.2f}")

    st.divider()

    # Row 2: 多維度分析 Tabs
    tabs = st.tabs(["📈 均線趨勢", "🌊 估值位階 (P/E)", "📊 技術指標", "🏦 籌碼動向"])
    
    with tabs[0]:
        st.subheader("均線排列與乖離率")
        st.line_chart(df[['Close', 'MA5', 'MA20', 'MA60']].iloc[-100:])
        ma_cols = st.columns(3)
        ma_cols[0].metric("MA5 (週)", f"{latest['MA5']:.2f}")
        ma_cols[1].metric("MA20 (月)", f"{latest['MA20']:.2f}", f"乖離 {latest['Bias_20']:.2f}%")
        ma_cols[2].metric("MA60 (季)", f"{latest['MA60']:.2f}")


    # --- 修改後的 Tab 1 內容 (🌊 估值位階) ---
    with tabs[1]:
        st.subheader("💡 法人評價與診斷 (FinMind 數據)")
        fm_df, status = get_finmind_indicators(ticker_input)
        
        if not fm_df.empty:
            # 1. 數據診斷邏輯
            current_per = fm_df['PER'].iloc[-1]
            current_pbr = fm_df['PBR'].iloc[-1]
            
            # 計算分位數 (20% 為便宜區, 80% 為昂貴區)
            per_p20 = fm_df['PER'].quantile(0.2)
            per_p80 = fm_df['PER'].quantile(0.8)
            pbr_p20 = fm_df['PBR'].quantile(0.2)
            pbr_p80 = fm_df['PBR'].quantile(0.8)
            
            # 2. 顯示診斷卡片
            diag_col1, diag_col2 = st.columns(2)
            
            with diag_col1:
                if current_per < per_p20:
                    st.success(f"✅ PER 診斷：估值偏低 ({current_per:.2f}x)")
                elif current_per > per_p80:
                    st.error(f"⚠️ PER 診斷：估值偏高 ({current_per:.2f}x)")
                else:
                    st.info(f"觀察中：PER 處於合理區間 ({current_per:.2f}x)")
                    
            with diag_col2:
                if current_pbr < pbr_p20:
                    st.success(f"✅ PBR 診斷：股價淨值比偏低 ({current_pbr:.2f})")
                elif current_pbr > pbr_p80:
                    st.error(f"⚠️ PBR 診斷：股價淨值比偏高 ({current_pbr:.2f})")
                else:
                    st.info(f"觀察中：PBR 處於合理區間 ({current_pbr:.2f})")

            st.divider()

            # 3. 圖表顯示
            fc1, fc2 = st.columns(2)
            with fc1:
                st.write("#### 歷史本益比 (PER) 趨勢")
                st.line_chart(fm_df['PER'])
            with fc2:
                st.write("#### 歷史股價淨值比 (PBR) 趨勢")
                st.line_chart(fm_df['PBR'])

            # 4. 新增：解讀方式教學區 (數據派投資指南)
            with st.expander("📚 如何解讀這張表？ (投資新手必讀)"):
                st.markdown(f"""
                ### 1. 本益比 (PER) - 買的是「成長」
                * **解讀方式**：代表回本年限。目前數值為 **{current_per:.2f}** 倍。
                * **診斷標準**：
                    * **低於 {per_p20:.2f} (P20)**：歷史低位，若公司獲利沒衰退，這可能是「撿便宜」的機會。
                    * **高於 {per_p80:.2f} (P80)**：歷史高位，代表市場熱度極高，需慎防回檔。
                
                ### 2. 股價淨值比 (PBR) - 買的是「價值」
                * **解讀方式**：股價相對於公司資產的倍數。目前數值為 **{current_pbr:.2f}**。
                * **診斷標準**：
                    * 對於景氣循環股（如航運、面板），PBR 比 PER 更具參考價值。
                    * **低於 1**：代表股價比公司清算價值還低，通常具有極強支撐力。
                    
                ### 3. 交叉驗證邏輯
                * **最佳買點**：股價在均線底部的「支撐區」+ PER 處於「歷史低位 (P20)」。
                * **避開陷阱**：股價噴發 + PER 衝破 P80。除非公司 EPS 發生爆發性成長，否則不建議追高。
                """)
        else:
            st.warning(f"無法載入估值資料：{status}")

    with tabs[2]:
        tc1, tc2 = st.columns(2)
        with tc1:
            st.write("#### KD (9,3,3)")
            st.line_chart(df[['K', 'D']].iloc[-60:])
        with tc2:
            st.write("#### MACD 柱狀圖")
            st.bar_chart(df['MACD_Hist'].iloc[-60:])

    with tabs[3]:
        st.subheader("三大法人買賣超")
        chips = get_twse_chips(ticker_input)
        if chips["found"]:
            st.caption(f"資料日期：{chips['date']} (單位：張)")
            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("外資", f"{chips['foreign']:,}")
            cc2.metric("投信", f"{chips['trust']:,}")
            cc3.metric("自營商", f"{chips['dealer']:,}")
        else:
            st.warning("暫無今日籌碼資料")

except Exception as e:
    st.error(f"執行發生錯誤: {e}")

st.caption("⚠️ 免責聲明：本工具僅供參考，投資前請審慎評估風險。")