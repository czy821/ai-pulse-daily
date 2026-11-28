"""
AI Pulse 07:00 — 每日多源抓取、时效过滤、20-30分钟阅读控时与全板块同步生成脚本
信息源覆盖：
1. 机器之心 / 量子位 (RSS)
2. RadarAI / Agents Radar (GitHub Issues API)
3. GitHub Trending AI Agents (GitHub Search API)
4. Hugging Face Daily Papers (Official JSON API)
5. arXiv cs.AI / cs.CL / cs.LG (Official Atom API)
6. AI News / The Batch (AINews RSS + Latent Space + TechCrunch AI + The Verge AI，严格按发布时间倒序并过滤旧闻)
"""

import calendar
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import feedparser
import requests
from openai import OpenAI

TIMEOUT = 20
MAX_AGE_DAYS = 10  # 严格过滤超过 10 天的过时旧闻
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, application/xml, text/html, */*",
}


def parse_entry_datetime(entry: Any) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        tp = getattr(entry, attr, None) or (entry.get(attr) if isinstance(entry, dict) else None)
        if tp:
            try:
                return datetime.fromtimestamp(calendar.timegm(tp), tz=timezone.utc)
            except Exception:
                continue
    return None


def fetch_rss(
    url: str,
    source_name: str,
    limit: int = 5,
    max_age_days: int = MAX_AGE_DAYS,
) -> List[Dict[str, str]]:
    items: List[Dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for entry in feed.entries:
            dt = parse_entry_datetime(entry)
            if dt is not None and dt < cutoff:
                continue
            summary_raw = entry.get("summary", "") or entry.get("description", "")
            summary_clean = re.sub(r"<[^>]+>", " ", summary_raw)
            summary_clean = re.sub(r"\s+", " ", summary_clean).strip()[:500]
            published_str = (
                dt.strftime("%Y-%m-%d")
                if dt is not None
                else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
            items.append({
                "_ts": dt.timestamp() if dt is not None else 0.0,
                "source": source_name,
                "title": entry.get("title", "").strip(),
                "summary": summary_clean,
                "url": entry.get("link", "").strip(),
                "publishedAt": published_str,
            })
        # 严格按发布时间从最新到最旧排序
        items.sort(key=lambda x: x["_ts"], reverse=True)
        for it in items:
            it.pop("_ts", None)
    except Exception as exc:
        print(f"[WARN] RSS fetch failed for {source_name} ({url}): {exc}", file=sys.stderr)
    return items[:limit]


def fetch_ai_news_sources(limit: int = 6) -> List[Dict[str, str]]:
    """聚合 AI News / The Batch 方向最新资讯，按发布时间倒序去重并剔除旧闻。"""
    feeds = [
        ("https://news.smol.ai/rss.xml", 4),
        ("https://www.latent.space/feed", 3),
        ("https://techcrunch.com/category/artificial-intelligence/feed/", 4),
        ("https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", 3),
    ]
    pool: List[Dict[str, str]] = []
    seen_urls = set()
    for feed_url, per_limit in feeds:
        for item in fetch_rss(feed_url, "AI News / The Batch", limit=per_limit, max_age_days=MAX_AGE_DAYS):
            u = item.get("url", "")
            if u and u not in seen_urls:
                seen_urls.add(u)
                pool.append(item)
    pool.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
    return pool[:limit]


def fetch_radar_ai(limit: int = 3) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    try:
        resp = requests.get(
            "https://api.github.com/repos/duanyytop/agents-radar/issues",
            params={"state": "open", "sort": "created", "direction": "desc", "per_page": limit},
            headers={**HEADERS, "Accept": "application/vnd.github+json"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        for issue in resp.json()[:limit]:
            items.append({
                "source": "RadarAI",
                "title": issue.get("title", "").strip(),
                "summary": (issue.get("body") or "")[:500].strip(),
                "url": issue.get("html_url", "").strip(),
                "publishedAt": str(issue.get("created_at", ""))[:10]
                or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })
    except Exception as exc:
        print(f"[WARN] RadarAI fetch failed: {exc}", file=sys.stderr)
    return items


def fetch_arxiv(limit: int = 6) -> List[Dict[str, str]]:
    url = (
        "https://export.arxiv.org/api/query?"
        "search_query=cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.LG"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={limit}"
    )
    return fetch_rss(url, "arXiv (cs.AI/cs.CL/cs.LG)", limit=limit, max_age_days=14)


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
                "publishedAt": str(row.get("publishedAt", ""))[:10]
                or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })
    except Exception as exc:
        print(f"[WARN] Hugging Face API failed: {exc}", file=sys.stderr)
    return items


def fetch_github_trending(limit: int = 5) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={
                "q": f"ai-agent pushed:>={since}",
                "sort": "stars",
                "order": "desc",
                "per_page": limit,
            },
            headers={**HEADERS, "Accept": "application/vnd.github+json"},
            timeout=TIMEOUT,
        )
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
    raw.extend(fetch_ai_news_sources(limit=6))
    raw.extend(fetch_radar_ai(limit=3))
    raw.extend(fetch_github_trending(limit=5))
    raw.extend(fetch_huggingface_papers(limit=5))
    raw.extend(fetch_arxiv(limit=6))
    return [item for item in raw if item.get("title") and item.get("url")]


def clean_json_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def synthesize_briefing(raw_items: List[Dict[str, str]]) -> Dict[str, Any]:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing LLM_API_KEY environment variable.")

    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    client = OpenAI(api_key=api_key, base_url=base_url)

    cn_tz = timezone(timedelta(hours=8))
    now_cn = datetime.now(cn_tz)
    today_iso = now_cn.strftime("%Y-%m-%d")
    today_label = now_cn.strftime("%Y年%m月%d日 · 早间 07:00 已完成6源聚合")

    system_prompt = f"""你是 AI Pulse 07:00 主编（当前日期：{today_iso}）。请从原始多源资讯中去重、筛选出 9-10 条最高信号价值的**最新**条目，并基于今日精选条目**同步生成**「主编核心研判」「产业前瞻」和「小白上手工坊」四个板块，严格满足：
1. **严格时效优先**：优先选用近 72 小时至 7 天内发布的最新资讯，严禁收录超过 14 天的过时旧闻，publishedAt 必须如实保留 YYYY-MM-DD；
2. 所有 items 的 readMinutes（每篇 2 或 3 分钟）总和必须严格控制在 22 到 28 分钟之间（处于 20-30 分钟区间）；
3. 尽量覆盖 6 大信息源（机器之心/量子位、RadarAI、GitHub Trending、Hugging Face、arXiv (cs.AI/cs.CL/cs.LG)、AI News / The Batch）；
4. 每条 items 和 workshops 必须严格保留原始 url，不可捏造链接；
5. editorialTakeaways 提炼 2 条今日核心主线；
6. foresightTracks 必须紧密围绕今日 items 归纳出 4 个未来 AI 强相关产业赛道（附 75-98 的热度评分、关联今日新闻短标题、核心逻辑、受益产业链与普通人切入建议）；
7. workshops 必须从今日 items 中挑出 4 个最值得零基础小白立刻体验的新工具/新方法，提供通俗类比、3 步实操清单和可直接一键复制的 Prompt 或命令模板；
8. 仅输出合法 JSON，严格遵循以下结构：
{{
  "editionDate": "字符串",
  "editorialTakeaways": [
    {{"label": "主线一（简短主题）", "text": "基于今日资讯的研判说明"}},
    {{"label": "主线二（简短主题）", "text": "基于今日资讯的研判说明"}}
  ],
  "items": [
    {{
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
      "summary": "100-140字中文事实摘要",
      "englishSummary": "2-3 sentences concise English executive summary covering the core facts and impact",
      "problemSolved": "解决什么痛点",
      "beginnerAnalogy": "通俗类比",
      "beginnerSteps": ["第1步...", "第2步...", "第3步..."],
      "industryImpact": "未来产业影响"
    }}
  ],
  "foresightTracks": [
    {{
      "title": "01. 赛道名称",
      "horizon": "3–12 个月 / 6–18 个月",
      "heatScore": 92,
      "relatedNews": ["今日关联新闻短标题1", "今日关联新闻短标题2"],
      "coreLogic": "核心演进逻辑",
      "beneficiaries": "强相关受益产业链",
      "beginnerOpportunity": "普通人/开发者切入建议"
    }}
  ],
  "workshops": [
    {{
      "id": "w1",
      "toolName": "今日工具/方法名称",
      "tag": "零门槛 · 5分钟上手",
      "problem": "解决什么问题",
      "analogy": "小白一句话听懂",
      "promptLabel": "一键复制 · 小白实操模板",
      "copyText": "可直接复制使用的 Prompt 或安装命令",
      "steps": ["第1步具体操作", "第2步具体操作", "第3步具体操作"],
      "link": "对应今日资讯的原始URL"
    }}
  ]
}}"""

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
    content = clean_json_text(response.choices[0].message.content or "{}")
    data = json.loads(content)
    data.setdefault("editionDate", today_label)
    if not data.get("items"):
        raise ValueError("LLM returned empty items array.")
    return data


def main() -> None:
    raw_items = collect_all_sources()
    print(f"[INFO] Collected {len(raw_items)} fresh raw items from sources.")
    if not raw_items:
        raise RuntimeError("No items fetched from any source.")

    briefing = synthesize_briefing(raw_items)
    total_mins = sum(int(i.get("readMinutes", 2)) for i in briefing["items"])
    print(
        f"[INFO] Generated {len(briefing['items'])} curated items ({total_mins} min), "
        f"{len(briefing.get('foresightTracks', []))} foresight tracks, "
        f"{len(briefing.get('workshops', []))} workshops."
    )

    os.makedirs("data", exist_ok=True)
    with open("data/daily_briefing.json", "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=2)
    print("[INFO] Saved data/daily_briefing.json successfully.")


if __name__ == "__main__":
    main()
