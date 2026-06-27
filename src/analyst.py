"""
Taiwan Stock Analyst - 每日台股數據報告
使用 yfinance 抓資料 + Gmail 發送報告（純數據版，不需要 API Key）
"""

import os
import json
import smtplib
import yfinance as yf
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

# ─── 設定 ────────────────────────────────────────────────
TW_TZ = ZoneInfo("Asia/Taipei")
TODAY = datetime.now(TW_TZ).strftime("%Y/%m/%d")


# ─── 1. 讀取持股清單 ─────────────────────────────────────
def load_portfolio(path: str = "stocks.json") -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["portfolio"]


# ─── 2. 抓 yfinance 資料 ─────────────────────────────────
def fetch_stock_data(symbol: str) -> dict:
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d")
        if hist.empty:
            return {"error": f"無法取得 {symbol} 資料", "symbol": symbol}

        latest = hist.iloc[-1]
        prev   = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]

        info = ticker.info

        closes = hist["Close"].tolist()
        ma5    = sum(closes[-5:]) / min(5, len(closes))
        ma20_data = ticker.history(period="1mo")["Close"]
        ma20   = ma20_data.mean() if not ma20_data.empty else latest["Close"]

        rsi_data = ticker.history(period="3mo")["Close"]
        rsi = calculate_rsi(rsi_data.tolist()) if len(rsi_data) >= 14 else None

        return {
            "symbol":     symbol,
            "close":      round(float(latest["Close"]), 2),
            "open":       round(float(latest["Open"]),  2),
            "high":       round(float(latest["High"]),  2),
            "low":        round(float(latest["Low"]),   2),
            "volume":     int(latest["Volume"]),
            "change":     round(float(latest["Close"] - prev["Close"]), 2),
            "change_pct": round(float((latest["Close"] - prev["Close"]) / prev["Close"] * 100), 2),
            "ma5":        round(ma5,  2),
            "ma20":       round(ma20, 2),
            "rsi":        round(rsi, 2) if rsi else "N/A",
            "52w_high":   info.get("fiftyTwoWeekHigh", "N/A"),
            "52w_low":    info.get("fiftyTwoWeekLow",  "N/A"),
            "pe_ratio":   info.get("trailingPE", "N/A"),
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}


def calculate_rsi(closes: list[float], period: int = 14) -> float:
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


def rsi_label(rsi) -> str:
    if rsi == "N/A":
        return "N/A", "#64748b"
    if rsi >= 70:
        return f"{rsi} 超買", "#dc2626"
    if rsi <= 30:
        return f"{rsi} 超賣", "#16a34a"
    return f"{rsi} 中性", "#64748b"


def fetch_market_overview() -> dict:
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


# ─── 3. 組合個股詳細卡片 ─────────────────────────────────
def build_stock_cards(portfolio: list[dict], stocks_data: list[dict]) -> str:
    cards = ""
    for s in stocks_data:
        meta  = next((p for p in portfolio if p["symbol"] == s.get("symbol")), {})
        name  = meta.get("name", s.get("symbol", ""))
        sym   = s.get("symbol", "")

        if "error" in s:
            cards += f"""
            <div style="background:#fff7f7;border:1px solid #fecaca;border-radius:10px;padding:16px;margin-bottom:12px;">
              <strong style="color:#dc2626;">{sym} {name}</strong>
              <p style="color:#dc2626;margin:4px 0 0;font-size:13px;">⚠️ 資料抓取失敗：{s['error']}</p>
            </div>"""
            continue

        cost    = meta.get("avg_cost", 0)
        shares  = meta.get("shares", 0)
        sector  = meta.get("sector", "")
        close   = s["close"]
        chg     = s["change_pct"]
        pnl     = round((close - cost) / cost * 100, 2) if cost else 0
        pnl_tw  = round((close - cost) * shares, 0) if cost and shares else 0

        chg_color  = "#16a34a" if chg >= 0  else "#dc2626"
        pnl_color  = "#16a34a" if pnl >= 0  else "#dc2626"
        chg_arrow  = "▲" if chg >= 0 else "▼"
        pnl_sign   = "+" if pnl >= 0 else ""

        # MA 訊號
        ma_signal = ""
        if s["ma5"] > s["ma20"]:
            ma_signal = '<span style="color:#16a34a;font-size:12px;">● MA5 > MA20 多頭排列</span>'
        else:
            ma_signal = '<span style="color:#dc2626;font-size:12px;">● MA5 < MA20 空頭排列</span>'

        # RSI
        rsi_val = s.get("rsi", "N/A")
        if rsi_val != "N/A":
            if rsi_val >= 70:
                rsi_html = f'<span style="color:#dc2626;">{rsi_val} ⚠️ 超買區</span>'
            elif rsi_val <= 30:
                rsi_html = f'<span style="color:#16a34a;">{rsi_val} 💡 超賣區</span>'
            else:
                rsi_html = f'<span style="color:#64748b;">{rsi_val} 中性</span>'
        else:
            rsi_html = "N/A"

        # 52週位置
        w52h = s.get("52w_high", "N/A")
        w52l = s.get("52w_low",  "N/A")
        if w52h != "N/A" and w52l != "N/A":
            try:
                pct_from_high = round((close - w52h) / w52h * 100, 1)
                w52_html = f'{w52l} ~ {w52h}（距高點 {pct_from_high}%）'
            except:
                w52_html = f'{w52l} ~ {w52h}'
        else:
            w52_html = "N/A"

        cards += f"""
        <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:20px;margin-bottom:16px;">
          <!-- 標題列 -->
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;flex-wrap:wrap;gap:8px;">
            <div>
              <span style="font-size:17px;font-weight:700;color:#1e293b;">{sym}</span>
              <span style="font-size:15px;color:#475569;margin-left:6px;">{name}</span>
              <span style="font-size:11px;color:#94a3b8;margin-left:8px;background:#f1f5f9;padding:2px 6px;border-radius:4px;">{sector}</span>
            </div>
            <div style="text-align:right;">
              <span style="font-size:22px;font-weight:700;color:#1e293b;">{close}</span>
              <span style="font-size:14px;color:{chg_color};font-weight:600;margin-left:8px;">{chg_arrow} {abs(chg)}%</span>
            </div>
          </div>

          <!-- 數據格線 -->
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px;">
            <div style="background:#f8fafc;border-radius:6px;padding:10px;text-align:center;">
              <div style="font-size:11px;color:#94a3b8;margin-bottom:3px;">開盤</div>
              <div style="font-size:14px;font-weight:600;">{s['open']}</div>
            </div>
            <div style="background:#f8fafc;border-radius:6px;padding:10px;text-align:center;">
              <div style="font-size:11px;color:#94a3b8;margin-bottom:3px;">最高</div>
              <div style="font-size:14px;font-weight:600;color:#16a34a;">{s['high']}</div>
            </div>
            <div style="background:#f8fafc;border-radius:6px;padding:10px;text-align:center;">
              <div style="font-size:11px;color:#94a3b8;margin-bottom:3px;">最低</div>
              <div style="font-size:14px;font-weight:600;color:#dc2626;">{s['low']}</div>
            </div>
          </div>

          <!-- 技術指標 -->
          <div style="border-top:1px solid #f1f5f9;padding-top:12px;font-size:13px;color:#475569;">
            <div style="display:flex;justify-content:space-between;margin-bottom:6px;flex-wrap:wrap;gap:4px;">
              <span>📈 MA5：<strong>{s['ma5']}</strong> ／ MA20：<strong>{s['ma20']}</strong> &nbsp;{ma_signal}</span>
            </div>
            <div style="display:flex;justify-content:space-between;margin-bottom:6px;flex-wrap:wrap;gap:4px;">
              <span>📊 RSI(14)：<strong>{rsi_html}</strong></span>
              <span>P/E：{round(s['pe_ratio'], 1) if s['pe_ratio'] != 'N/A' else 'N/A'}</span>
            </div>
            <div style="margin-bottom:6px;">
              <span>📅 52週區間：{w52_html}</span>
            </div>
          </div>

          <!-- 持倉損益 -->
          <div style="background:#f8fafc;border-radius:6px;padding:12px;margin-top:12px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;">
            <div style="font-size:13px;color:#64748b;">
              持股 <strong>{shares}</strong> 張 ／ 成本 <strong>{cost}</strong>
            </div>
            <div style="font-size:14px;font-weight:700;color:{pnl_color};">
              {pnl_sign}{pnl}%　（{pnl_sign}{int(pnl_tw):,} 元）
            </div>
          </div>
        </div>"""
    return cards


# ─── 4. 組合 HTML 報告 ───────────────────────────────────
def build_html_report(portfolio: list[dict], stocks_data: list[dict], market: dict) -> str:

    # 大盤列
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

    # 持倉總損益
    total_pnl = 0
    for s in stocks_data:
        if "error" not in s:
            meta  = next((p for p in portfolio if p["symbol"] == s["symbol"]), {})
            cost  = meta.get("avg_cost", 0)
            shares = meta.get("shares", 0)
            if cost and shares:
                total_pnl += (s["close"] - cost) * shares
    total_color = "#16a34a" if total_pnl >= 0 else "#dc2626"
    total_sign  = "+" if total_pnl >= 0 else ""

    stock_cards = build_stock_cards(portfolio, stocks_data)

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>台股每日報告 {TODAY}</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Helvetica Neue',Arial,sans-serif;color:#1e293b;">
<div style="max-width:680px;margin:0 auto;padding:24px 16px;">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#0f172a,#1e40af);border-radius:14px;padding:28px 32px;margin-bottom:20px;">
    <div style="color:#93c5fd;font-size:13px;margin-bottom:6px;">📅 {TODAY} · 台股每日數據報告</div>
    <h1 style="color:#ffffff;margin:0 0 4px;font-size:22px;font-weight:700;">持倉數據報告</h1>
    <p style="color:#bfdbfe;margin:0;font-size:13px;">由 yfinance 自動抓取 · 每個交易日 08:00 發送</p>
  </div>

  <!-- 總損益 -->
  <div style="background:#ffffff;border-radius:12px;padding:20px 24px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.06);display:flex;justify-content:space-between;align-items:center;">
    <div style="color:#64748b;font-size:14px;">📋 持倉總損益（未實現）</div>
    <div style="font-size:22px;font-weight:700;color:{total_color};">{total_sign}{int(total_pnl):,} 元</div>
  </div>

  <!-- 大盤環境 -->
  <div style="background:#ffffff;border-radius:12px;padding:20px 24px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
    <h2 style="margin:0 0 14px;font-size:15px;color:#1e293b;font-weight:600;">🌏 大盤環境</h2>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <tr style="background:#f8fafc;">
        <th style="padding:8px 12px;text-align:left;color:#64748b;font-weight:500;">指數</th>
        <th style="padding:8px 12px;text-align:right;color:#64748b;font-weight:500;">收盤</th>
        <th style="padding:8px 12px;text-align:right;color:#64748b;font-weight:500;">漲跌幅</th>
      </tr>
      {market_rows}
    </table>
  </div>

  <!-- 個股卡片 -->
  <div style="margin-bottom:16px;">
    <h2 style="font-size:15px;color:#1e293b;font-weight:600;margin:0 0 12px;">📊 個股詳細數據</h2>
    {stock_cards}
  </div>

  <!-- Footer -->
  <div style="text-align:center;color:#94a3b8;font-size:12px;padding:16px 0;">
    <p style="margin:0;">⚠️ 本報告為自動抓取的數據彙整，不構成投資建議。投資有風險，請自行判斷。</p>
    <p style="margin:6px 0 0;">Taiwan Stock Analyst · Powered by yfinance</p>
  </div>

</div>
</body>
</html>"""


# ─── 5. 發送 Email ───────────────────────────────────────
def send_email(html_content: str, subject: str):
    sender    = os.environ["GMAIL_USER"]
    password  = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"台股數據報告 <{sender}>"
    msg["To"]      = recipient
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
    print(f"✅ 報告已發送至 {recipient}")


# ─── 主程式 ──────────────────────────────────────────────
def main():
    print(f"🚀 開始執行台股報告 [{TODAY}]")

    portfolio = load_portfolio("stocks.json")
    print(f"📋 持股清單：{[s['name'] for s in portfolio]}")

    print("🌏 抓取大盤資料...")
    market = fetch_market_overview()

    print("📈 抓取個股資料...")
    stocks_data = [fetch_stock_data(s["symbol"]) for s in portfolio]

    print("📝 組合 HTML 報告...")
    html = build_html_report(portfolio, stocks_data, market)

    subject = f"📊 台股數據報告 {TODAY}"
    send_email(html, subject)
    print("✅ 完成！")


if __name__ == "__main__":
    main()
