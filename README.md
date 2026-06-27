# 📊 Taiwan Stock Analyst — AI 台股每日分析報告

每天早上 08:00（台灣時間）自動分析你的持股，透過 Gmail 發送 AI 分析報告。

---

## 🗂 專案結構

```
taiwan-stock-analyst/
├── .github/
│   └── workflows/
│       └── daily_report.yml   # GitHub Actions 排程
├── src/
│   └── analyst.py             # 主程式
├── stocks.json                # 你的持股清單（自行編輯）
├── requirements.txt
└── README.md
```

---

## ⚙️ 設定步驟

### Step 1：Fork 這個 Repository 到你的 GitHub

### Step 2：編輯 `stocks.json` 填入你的持股

```json
{
  "portfolio": [
    {
      "symbol": "2330.TW",
      "name": "台積電",
      "shares": 100,
      "avg_cost": 850.0,
      "sector": "半導體"
    }
  ]
}
```

> 台股代號格式：`{股票代號}.TW`（例如：台積電 = `2330.TW`）

### Step 3：設定 Gmail App Password

1. 前往 Google 帳號設定 → 安全性
2. 開啟「兩步驟驗證」
3. 前往「應用程式密碼」，建立一組新密碼
4. 記下這組 16 位數密碼（只顯示一次）

### Step 4：在 GitHub 設定 Secrets

進入你的 Repository → Settings → Secrets and variables → Actions → New repository secret

| Secret 名稱          | 說明                          |
|---------------------|-------------------------------|
| `ANTHROPIC_API_KEY` | 你的 Claude API 金鑰           |
| `GMAIL_USER`        | 你的 Gmail 地址                |
| `GMAIL_APP_PASSWORD`| 步驟 3 產生的應用程式密碼       |
| `RECIPIENT_EMAIL`   | 接收報告的 Email（可以是自己）  |

### Step 5：手動觸發測試

GitHub Repository → Actions → 台股每日分析報告 → Run workflow

---

## 📧 報告內容

每份報告包含：

- 🌏 **大盤環境**：台加權、費城半導體、S&P500、美元指數、匯率
- 📊 **持股快覽**：收盤價、今日漲跌、持倉損益、RSI
- 🤖 **AI 深度分析**（每檔個股）：
  - 今日方向（多/空/觀望）+ 信心指數
  - 目標價 / 出場停損價
  - 風險收益比
  - 技術面解讀（MA5/MA20/RSI/量價）
  - 具體操作建議
  - 主要風險提示
- 📋 **整體持倉健康度**：多空比、產業集中度、未來趨勢

---

## 🔧 自訂排程時間

修改 `.github/workflows/daily_report.yml` 中的 cron 設定：

```yaml
# 台灣時間 08:00 = UTC 00:00
- cron: "0 0 * * 1-5"
```

> [crontab.guru](https://crontab.guru) 可以幫你換算時間

---

## ⚠️ 免責聲明

本工具由 AI 自動生成分析報告，**僅供參考，不構成投資建議**。
投資有風險，請根據自身狀況獨立判斷。
