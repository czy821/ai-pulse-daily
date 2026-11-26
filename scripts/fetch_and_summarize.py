"""
AI Pulse 07:00 — 每日多源抓取、20-30分钟阅读控时与深度分析生成脚本
信息源覆盖：
1. 机器之心 / 量子位 (RSS)
2. RadarAI / AI Radar (RSS/Web)
3. GitHub Trending AI Agents (GitHub Search API)
4. Hugging Face Daily Papers (Official JSON API)
5. arXiv cs.AI / cs.CL / cs.LG (Official Atom API)
6. AI News / The Batch (RSS)
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import feedparser
import requests
from openai import OpenAI

TIMEOUT = 20
HEADERS = {"User-Agent": "AI-Pulse-0700-Bot/1.0"}


def fetch_rss(url: str, source_name: str, limit: int = 5) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for entry in feed.entries[:limit]:
            items.append({
                "source": source_name,
                "title": entry.get("title", "").strip(),
                "summary": entry.get("summary", "")[:500].strip(),
                "url": entry.get("link", "").strip(),
                "publishedAt": entry.get("published", "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })
    except Exception as exc:
        print(f"[WARN] RSS fetch failed for {source_name}: {exc}", file=sys.stderr)
    return items


def fetch_arxiv(limit: int = 6) -> List[Dict[str, str]]:
    url = (
        "https://export.arxiv.org/api/query?"
        "search_query=cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.LG"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={limit}"
    )
    return fetch_rss(url, "arXiv (cs.AI/cs.CL/cs.LG)", limit=limit)


def fetch_huggingface_papers(limit: int = 5) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    try:
        resp = requests.get("https://huggingface.co/api/daily_papers", headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        for row in data[:limit]:
            paper = row.get("paper", {})
            pid = paper.get("id", "")
            items.append({
                "source": "Hugging Face",
                "title": paper.get("title", "").strip(),
                "summary": paper.get("summary", "")[:500].strip(),
                "url": f"https://huggingface.co/papers/{pid}" if pid else "https://huggingface.co/papers",
                "publishedAt": str(row.get("publishedAt", ""))[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })
    except Exception as exc:
        print(f"[WARN] Hugging Face API failed: {exc}", file=sys.stderr)
    return items


def fetch_github_trending(limit: int = 5) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        url = (
            "https://api.github.com/search/repositories"
            f"?q=topic:ai-agent+OR+topic:llm+pushed:>={since}&sort=stars&order=desc&per_page={limit}"
        )
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        for repo in resp.json().get("items", [])[:limit]:
            items.append({
                "source": "GitHub Trending",
                "title": f"{repo.get('full_name')} (★{repo.get('stargazers_count', 0)})",
                "summary": (repo.get("description") or "AI open-source repository")[:400],
                "url": repo.get("html_url", ""),
                "publishedAt": str(repo.get("pushed_at", ""))[:10],
            })
    except Exception as exc:
        print(f"[WARN] GitHub API failed: {exc}", file=sys.stderr)
    return items


def collect_all_sources() -> List[Dict[str, str]]:
    raw: List[Dict[str, str]] = []
    raw.extend(fetch_rss("https://www.qbitai.com/feed", "机器之心/量子位", limit=5))
    raw.extend(fetch_rss("https://www.jiqizhixin.com/rss", "机器之心/量子位", limit=4))
    raw.extend(fetch_rss("https://www.deeplearning.ai/the-batch/rss/", "AI News / The Batch", limit=4))
    raw.extend(fetch_rss("https://aicaramba.co.uk/feed", "RadarAI", limit=4))
    raw.extend(fetch_github_trending(limit=5))
    raw.extend(fetch_huggingface_papers(limit=5))
    raw.extend(fetch_arxiv(limit=6))
    return [item for item in raw if item.get("title") and item.get("url")]


def synthesize_briefing(raw_items: List[Dict[str, str]]) -> Dict[str, Any]:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing LLM_API_KEY environment variable.")

    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    client = OpenAI(api_key=api_key, base_url=base_url)

    cn_tz = timezone(timedelta(hours=8))
    today_label = datetime.now(cn_tz).strftime("%Y年%m月%d日 · 早间 07:00 已完成6源聚合")

    system_prompt = """你是 AI Pulse 07:00 主编。请从原始多源资讯中去重、筛选出 9-10 条最高信号价值的条目，严格满足：
1. 所有条目的 readMinutes（每篇 2 或 3 分钟）总和必须严格控制在 22 到 28 分钟之间（处于 20-30 分钟区间）；
2. 尽量覆盖 6 大信息源（机器之心/量子位、RadarAI、GitHub Trending、Hugging Face、arXiv (cs.AI/cs.CL/cs.LG)、AI News / The Batch）；
3. 每条必须严格保留原始 url，不可捏造链接；
4. 每条必须包含：problemSolved（这个新工具/技术解决什么问题）、beginnerAnalogy（小白一句话通俗类比）、beginnerSteps（3条具体可执行的零基础上手步骤数组）、industryImpact（对未来AI强相关产业的前瞻影响）；
5. 仅输出合法 JSON，格式：
{
  "editionDate": "字符串",
  "items": [
    {
      "id": "n1",
      "title": "中文标题",
      "source": "6大源标准名称之一",
      "category": "简短领域标签",
      "readMinutes": 3,
      "signal": "opportunity | watch | alert",
      "signalLabel": "🟢 高潜机遇 | 🟡 重点关注 | 🔴 风险/格局预警",
      "publishedAt": "YYYY-MM-DD",
      "quickPick": true,
      "url": "原始URL",
      "summary": "100-140字事实摘要",
      "problemSolved": "解决什么痛点",
      "beginnerAnalogy": "通俗类比",
      "beginnerSteps": ["第1步...", "第2步...", "第3步..."],
      "industryImpact": "未来产业影响"
    }
  ]
}"""

    response = client.chat.completions.create(
        model=model,
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"今日期号：{today_label}\n原始抓取条目（JSON）：\n{json.dumps(raw_items, ensure_ascii=False)}",
            },
        ],
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    data.setdefault("editionDate", today_label)
    if not data.get("items"):
        raise ValueError("LLM returned empty items array.")
    return data


def main() -> None:
    raw_items = collect_all_sources()
    print(f"[INFO] Collected {len(raw_items)} raw items from sources.")
    if not raw_items:
        raise RuntimeError("No items fetched from any source.")

    briefing = synthesize_briefing(raw_items)
    total_mins = sum(int(i.get("readMinutes", 2)) for i in briefing["items"])
    print(f"[INFO] Generated {len(briefing['items'])} curated items ({total_mins} min total).")

    os.makedirs("data", exist_ok=True)
    with open("data/daily_briefing.json", "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=2)
    print("[INFO] Saved data/daily_briefing.json successfully.")


if __name__ == "__main__":
    main()
