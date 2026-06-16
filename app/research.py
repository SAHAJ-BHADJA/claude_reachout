"""Company research: scrape the company site (+ optional Tavily news) and have
Claude synthesise a research package used by BOTH the email and (later) the resume."""
import httpx
from bs4 import BeautifulSoup
from .config import cfg
from .claude_client import complete_json

PAGES = ["", "/about", "/about-us", "/company", "/careers", "/mission"]


def _scrape(domain: str) -> str:
    if not domain:
        return ""
    base = domain if domain.startswith("http") else f"https://{domain}"
    parts = []
    try:
        with httpx.Client(timeout=18, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (research)"}) as cx:
            for path in PAGES:
                try:
                    r = cx.get(base + path)
                    if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                        continue
                    soup = BeautifulSoup(r.text, "html.parser")
                    for tag in soup(["script", "style", "nav", "footer", "header"]):
                        tag.decompose()
                    txt = " ".join(soup.get_text(" ").split())
                    if txt:
                        parts.append(f"[{path or '/'}] {txt[:2500]}")
                except Exception:
                    continue
                if len("".join(parts)) > 8000:
                    break
    except Exception:
        pass
    return "\n\n".join(parts)[:9000]


def _tavily(company: str) -> list[dict]:
    if not cfg.TAVILY_API_KEY:
        return []
    try:
        with httpx.Client(timeout=30) as cx:
            r = cx.post("https://api.tavily.com/search", json={
                "api_key": cfg.TAVILY_API_KEY,
                "query": f"{company} recent news announcements 2026",
                "search_depth": "basic", "max_results": 5, "topic": "news",
            })
            r.raise_for_status()
            return [{"title": x.get("title"), "content": (x.get("content") or "")[:500]}
                    for x in r.json().get("results", [])]
    except Exception:
        return []


SYSTEM = """You are a company-research analyst. From the website text and news snippets,
write concise, factual notes an applicant can reference in a personalised email and resume.
Never invent facts. Return JSON:
{
  "summary": "2-3 sentences on what the company does",
  "goals": "2-4 sentences on mission, current direction and goals",
  "recent_news": ["up to 3 short genuinely-recent bullets, or empty"],
  "hooks": ["2-3 specific things an applicant could authentically connect with"]
}"""


def research_company(company: str, domain: str = "") -> dict:
    site = _scrape(domain)
    news = _tavily(company)
    news_block = "\n".join(f"- {n['title']}: {n['content']}" for n in news)
    user = (f"COMPANY: {company}\nDOMAIN: {domain}\n\n"
            f"WEBSITE TEXT:\n{site or '(none)'}\n\nNEWS:\n{news_block or '(none)'}")
    try:
        return complete_json(SYSTEM, user, max_tokens=900)
    except Exception:
        return {"summary": "", "goals": "", "recent_news": [], "hooks": []}
