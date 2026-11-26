# AI Pulse 07:00 — 每天早上七点自动更新部署指南

本压缩包包含完整的**暖色调科技感前端网页**与**每天早上 07:00 自动抓取、去重、控时（20–30 分钟）并生成深度分析的后端工作流**，可直接零成本托管在 **GitHub Pages** 上。

## 目录结构
- `index.html`：暖阳晨读/暖夜护眼双主题单页应用（托管上线后自动读取 `data/daily_briefing.json`）
- `data/daily_briefing.json`：每日 07:00 自动更新的早报数据文件
- `scripts/fetch_and_summarize.py`：6 大信息源抓取与大模型结构化总结脚本
- `.github/workflows/daily-0700.yml`：GitHub Actions 定时任务（默认北京时间每天 07:00 自动执行）
- `requirements.txt`：Python 依赖清单

## 3 步上线（约 5 分钟，零服务器成本）

### 第 1 步：上传至 GitHub 仓库
1. 在 GitHub 新建一个公开仓库（例如 `ai-pulse-daily`）。
2. 将本压缩包解压后的全部文件（注意保留隐藏文件夹 `.github/workflows/daily-0700.yml`）推送到仓库根目录。

### 第 2 步：配置大模型 API 密钥
1. 进入仓库 **Settings → Secrets and variables → Actions → New repository secret**。
2. 添加以下 Secret：
   - `LLM_API_KEY`（必填）：你的 OpenAI / DeepSeek / Gemini OpenAI 兼容接口密钥。
   - `LLM_BASE_URL`（选填）：默认 `https://api.openai.com/v1`；如使用 DeepSeek 可填 `https://api.deepseek.com/v1`，如使用 Gemini 兼容端点可填 `https://generativelanguage.googleapis.com/v1beta/openai/`。
   - `LLM_MODEL`（选填）：默认 `gpt-4o-mini`；可按需改为 `deepseek-chat` 或 `gemini-2.5-flash`。

### 第 3 步：开启 GitHub Pages 并手动测试一次
1. 进入仓库 **Settings → Pages**，在 **Source** 选择 `Deploy from a branch`，分支选择 `main` / `/(root)`，点击 Save，1 分钟后即可获得你的专属网址 `https://<你的用户名>.github.io/ai-pulse-daily/`。
2. 进入仓库 **Actions → AI Pulse Daily 07:00 Update**，点击 **Run workflow** 立即测试一次抓取与更新。
3. 之后每天早上 07:00（默认北京时间 `cron: '0 23 * * *'`；如需美西时间 07:00，将 `.github/workflows/daily-0700.yml` 中的 cron 改为 `'0 15 * * *'`），网站会自动更新当日早报。
