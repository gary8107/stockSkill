"""
Taiwan Stock Analyst - 每日台股分析報告
使用 yfinance 抓資料 + Claude API 分析 + Gmail 發送報告
"""

import os
import json
import smtplib
import yfinance as yf
import anthropic
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

# ─── 設定 ────────────────────────────────────────────────
TW_TZ = ZoneInfo("Asia/Taipei")
TODAY = datetime.now(TW_TZ).strftime("%Y/%m/%d")
YESTERDAY = (datetime.now(TW_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


# ─── 1. 讀取持股清單 ─────────────────────────────────────
def load_portfolio(path: str = "stocks.json") -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["portfolio"]


# ─── 2. 抓 yfinance 資料 ─────────────────────────────────
def fetch_stock_data(symbol: str) -> dict:
    """抓單一股票昨日資料"""
    try:
        ticker = yf.Ticker(symbol)

        # 抓近 5 天資料（確保拿得到最新交易日）
        hist = ticker.history(period="5d")
        if hist.empty:
            return {"error": f"無法取得 {symbol} 資料"}

        latest = hist.iloc[-1]
        prev   = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]

        # 基本資訊
        info = ticker.info

        # 技術指標（簡易版）
        closes = hist["Close"].tolist()
        ma5    = sum(closes[-5:]) / min(5, len(closes))
        ma20_data = ticker.history(period="1mo")["Close"]
        ma20   = ma20_data.mean() if not ma20_data.empty else latest["Close"]

        # RSI（14日）
        rsi_data = ticker.history(period="3mo")["Close"]
        rsi = calculate_rsi(rsi_data.tolist()) if len(rsi_data) >= 14 else None

        return {
            "symbol": symbol,
            "close":  round(float(latest["Close"]), 2),
            "open":   round(float(latest["Open"]),  2),
            "high":   round(float(latest["High"]),  2),
            "low":    round(float(latest["Low"]),   2),
            "volume": int(latest["Volume"]),
            "change": round(float(latest["Close"] - prev["Close"]), 2),
            "change_pct": round(float((latest["Close"] - prev["Close"]) / prev["Close"] * 100), 2),
            "ma5":    round(ma5,  2),
            "ma20":   round(ma20, 2),
            "rsi":    round(rsi, 2) if rsi else "N/A",
            "52w_high": info.get("fiftyTwoWeekHigh", "N/A"),
            "52w_low":  info.get("fiftyTwoWeekLow",  "N/A"),
            "pe_ratio": info.get("trailingPE", "N/A"),
            "market_cap": info.get("marketCap", "N/A"),
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}


def calculate_rsi(closes: list[float], period: int = 14) -> float:
    """計算 RSI"""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def fetch_market_overview() -> dict:
    """抓大盤與相關指數"""
    indices = {
        "台灣加權指數": "^TWII",
        "費城半導體":   "^SOX",
        "美國標普500":  "^GSPC",
        "美元指數":     "DX-Y.NYB",
        "美元台幣":     "TWD=X",
    }
    result = {}
    for name, sym in indices.items():
        try:
            t    = yf.Ticker(sym)
            hist = t.history(period="2d")
            if len(hist) >= 2:
                close = hist["Close"].iloc[-1]
                prev  = hist["Close"].iloc[-2]
                chg   = round((close - prev) / prev * 100, 2)
                result[name] = {"value": round(close, 2), "change_pct": chg}
            elif len(hist) == 1:
                result[name] = {"value": round(hist["Close"].iloc[-1], 2), "change_pct": 0}
        except Exception:
            result[name] = {"value": "N/A", "change_pct": 0}
    return result


# ─── 3. Claude 分析 ──────────────────────────────────────
def analyze_with_claude(portfolio: list[dict], stocks_data: list[dict], market: dict) -> str:
    """呼叫 Claude API 進行深度分析"""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # 組合持股資訊（加入成本）
    enriched = []
    for stock_data in stocks_data:
        meta = next((p for p in portfolio if p["symbol"] == stock_data.get("symbol")), {})
        if "error" not in stock_data:
            cost       = meta.get("avg_cost", 0)
            close      = stock_data["close"]
            pnl_pct    = round((close - cost) / cost * 100, 2) if cost else "N/A"
            enriched.append({**stock_data, **meta, "pnl_pct": pnl_pct})
        else:
            enriched.append({**stock_data, **meta})

    prompt = f"""
你是一位專業的台股分析師，請根據以下資料，為投資人撰寫今日（{TODAY}）的個股分析報告。

## 大盤環境
{json.dumps(market, ensure_ascii=False, indent=2)}

## 持股資料
{json.dumps(enriched, ensure_ascii=False, indent=2)}

請針對每一檔持股，分別提供以下分析（用繁體中文）：

### 每檔個股分析格式：
**[股票代號] 股票名稱**
- 📊 **今日方向**：多/空/觀望（搭配信心指數 1-5 顆星）
- 🎯 **目標價**：若看多，給出近期目標價；若看空，給出支撐價
- 🚪 **出場價（停損）**：建議停損點位
- ⚖️ **風險收益比**：預估風險收益比（例如 1:2.5）
- 📈 **技術面**：MA5/MA20 位置、RSI 解讀、量價關係
- 💡 **操作建議**：具體的操作策略（持有/加碼/減碼/觀望）
- ⚠️ **主要風險**：1-2 個需注意的風險因子

### 最後加上：
**📋 整體持倉健康度評估**
- 持倉多空比例
- 產業集中度風險
- 今日最需要關注的個股（前兩名）
- 未來 1-2 週整體趨勢判斷

請保持客觀專業，數據要有所根據，不要過度樂觀。
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# ─── 4. 組合 HTML 報告 ───────────────────────────────────
def build_html_report(analysis: str, portfolio: list[dict], stocks_data: list[dict], market: dict) -> str:
    """把 Claude 分析結果包裝成漂亮的 HTML Email"""

    # 大盤摘要 HTML
    market_rows = ""
    for name, data in market.items():
        val = data["value"]
        chg = data["change_pct"]
        color = "#16a34a" if chg >= 0 else "#dc2626"
        arrow = "▲" if chg >= 0 else "▼"
        market_rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;">{name}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;text-align:right;font-weight:600;">{val}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;text-align:right;color:{color};font-weight:600;">{arrow} {abs(chg)}%</td>
        </tr>"""

    # 持股快覽 HTML
    stock_rows = ""
    for s in stocks_data:
        if "error" in s:
            continue
        meta   = next((p for p in portfolio if p["symbol"] == s["symbol"]), {})
        cost   = meta.get("avg_cost", 0)
        close  = s["close"]
        pnl    = round((close - cost) / cost * 100, 2) if cost else 0
        chg    = s["change_pct"]
        color  = "#16a34a" if chg >= 0 else "#dc2626"
        pcolor = "#16a34a" if pnl >= 0 else "#dc2626"
        arrow  = "▲" if chg >= 0 else "▼"
        stock_rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;">{s['symbol']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;">{meta.get('name','')}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;text-align:right;font-weight:600;">{close}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;text-align:right;color:{color};">{arrow} {abs(chg)}%</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;text-align:right;">{cost}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;text-align:right;color:{pcolor};font-weight:600;">{'+' if pnl>=0 else ''}{pnl}%</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;text-align:right;">{s.get('rsi','N/A')}</td>
        </tr>"""

    # Markdown → HTML（簡易轉換）
    import re
    analysis_html = analysis.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    analysis_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', analysis_html)
    analysis_html = re.sub(r'\*(.+?)\*',     r'<em>\1</em>',         analysis_html)
    analysis_html = re.sub(r'^### (.+)$',    r'<h3 style="color:#1e40af;margin-top:20px;">\1</h3>', analysis_html, flags=re.MULTILINE)
    analysis_html = re.sub(r'^## (.+)$',     r'<h2 style="color:#1e3a8a;border-bottom:2px solid #dbeafe;padding-bottom:6px;">\1</h2>', analysis_html, flags=re.MULTILINE)
    analysis_html = re.sub(r'^- (.+)$',      r'<li style="margin:4px 0;">\1</li>', analysis_html, flags=re.MULTILINE)
    analysis_html = analysis_html.replace("\n\n", "</p><p>").replace("\n", "<br>")
    analysis_html = f"<p>{analysis_html}</p>"

    return f"""
<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>台股每日分析報告 {TODAY}</title>
</head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:'Helvetica Neue',Arial,sans-serif;color:#1e293b;">
  <div style="max-width:680px;margin:0 auto;padding:24px 16px;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1e3a8a,#2563eb);border-radius:12px;padding:28px 32px;margin-bottom:24px;">
      <div style="color:#93c5fd;font-size:13px;margin-bottom:6px;">📅 {TODAY} · 台股每日分析</div>
      <h1 style="color:#ffffff;margin:0;font-size:24px;font-weight:700;">AI 持倉分析報告</h1>
      <p style="color:#bfdbfe;margin:8px 0 0;font-size:14px;">由 Claude AI 分析師自動生成</p>
    </div>

    <!-- 大盤環境 -->
    <div style="background:#ffffff;border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
      <h2 style="margin:0 0 16px;font-size:16px;color:#1e293b;">🌏 大盤環境</h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr style="background:#f8fafc;">
          <th style="padding:8px 12px;text-align:left;color:#64748b;font-weight:500;">指數</th>
          <th style="padding:8px 12px;text-align:right;color:#64748b;font-weight:500;">收盤</th>
          <th style="padding:8px 12px;text-align:right;color:#64748b;font-weight:500;">漲跌幅</th>
        </tr>
        {market_rows}
      </table>
    </div>

    <!-- 持股快覽 -->
    <div style="background:#ffffff;border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
      <h2 style="margin:0 0 16px;font-size:16px;color:#1e293b;">📊 持股快覽</h2>
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <tr style="background:#f8fafc;">
            <th style="padding:8px 12px;text-align:left;color:#64748b;font-weight:500;">代號</th>
            <th style="padding:8px 12px;text-align:left;color:#64748b;font-weight:500;">名稱</th>
            <th style="padding:8px 12px;text-align:right;color:#64748b;font-weight:500;">收盤價</th>
            <th style="padding:8px 12px;text-align:right;color:#64748b;font-weight:500;">今日漲跌</th>
            <th style="padding:8px 12px;text-align:right;color:#64748b;font-weight:500;">成本</th>
            <th style="padding:8px 12px;text-align:right;color:#64748b;font-weight:500;">損益%</th>
            <th style="padding:8px 12px;text-align:right;color:#64748b;font-weight:500;">RSI</th>
          </tr>
          {stock_rows}
        </table>
      </div>
    </div>

    <!-- Claude 分析 -->
    <div style="background:#ffffff;border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
      <h2 style="margin:0 0 20px;font-size:16px;color:#1e293b;">🤖 AI 深度分析</h2>
      <div style="font-size:14px;line-height:1.8;color:#334155;">
        {analysis_html}
      </div>
    </div>

    <!-- Footer -->
    <div style="text-align:center;color:#94a3b8;font-size:12px;padding:16px;">
      <p style="margin:0;">⚠️ 本報告由 AI 自動生成，僅供參考，不構成投資建議。投資有風險，請自行判斷。</p>
      <p style="margin:8px 0 0;">Taiwan Stock Analyst · Powered by Claude &amp; yfinance</p>
    </div>

  </div>
</body>
</html>
"""


# ─── 5. 發送 Email ───────────────────────────────────────
def send_email(html_content: str, subject: str):
    """透過 Gmail SMTP 發送 HTML 報告"""
    sender    = os.environ["GMAIL_USER"]
    password  = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"台股 AI 分析師 <{sender}>"
    msg["To"]      = recipient
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
    print(f"✅ 報告已發送至 {recipient}")


# ─── 主程式 ──────────────────────────────────────────────
def main():
    print(f"🚀 開始執行台股分析 [{TODAY}]")

    # 1. 讀取持股清單
    portfolio = load_portfolio("stocks.json")
    symbols   = [s["symbol"] for s in portfolio]
    print(f"📋 持股清單：{[s['name'] for s in portfolio]}")

    # 2. 抓大盤資料
    print("🌏 抓取大盤資料...")
    market = fetch_market_overview()

    # 3. 抓個股資料
    print("📈 抓取個股資料...")
    stocks_data = [fetch_stock_data(sym) for sym in symbols]

    # 4. Claude 分析
    print("🤖 Claude 分析中...")
    analysis = analyze_with_claude(portfolio, stocks_data, market)

    # 5. 組合報告
    print("📝 組合 HTML 報告...")
    html = build_html_report(analysis, portfolio, stocks_data, market)

    # 6. 發送 Email
    subject = f"📊 台股 AI 分析報告 {TODAY}"
    send_email(html, subject)
    print("✅ 完成！")


if __name__ == "__main__":
    main()
