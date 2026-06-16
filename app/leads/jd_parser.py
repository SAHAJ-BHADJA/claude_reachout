"""Claude turns a free-text JD into structured search filters + the people to contact."""
from ..claude_client import complete_json

SENIORITY = ["Founder", "Chairman", "President", "CEO", "CXO", "Vice President",
             "Director", "Head", "Manager", "Senior", "Junior", "Entry Level", "Executive"]
DEPARTMENTS = ["Engineering", "Product Management", "Data Engineering", "Devops", "IT",
               "Marketing", "Sales", "HR", "Hiring", "Research", "Operations", "Finance",
               "Analytics", "Design", "Security", "Cyber Security", "Cloud", "Applications"]

SYSTEM = """You are a recruiting-intelligence parser. Given a job description, identify
the hiring company and the people most worth contacting about the role — the people
who INFLUENCE HIRING (hiring managers, the team's leadership, and recruiters), NOT the
open role itself.

Return JSON with EXACTLY these keys:
{
  "company_name": "best guess of the hiring company, or empty",
  "company_domain": "like 'redfin.com' (no www/https), or empty",
  "role_title": "the JD's role title",
  "location_country": "country if stated else empty",
  "location_state": "state/region if stated else empty",
  "location_city": "city if stated else empty",
  "target_titles": ["3-6 titles of people to CONTACT, e.g. Engineering Manager, Director of Engineering, Technical Recruiter, Talent Acquisition"],
  "departments": ["subset of the allowed departments"],
  "seniority": ["subset of the allowed seniority levels"],
  "keywords": ["3-6 tech/industry keywords from the JD"]
}
Allowed departments: {departments}
Allowed seniority: {seniority}"""


def parse_jd(jd_text: str) -> dict:
    system = SYSTEM.replace("{departments}", ", ".join(DEPARTMENTS)).replace("{seniority}", ", ".join(SENIORITY))
    d = complete_json(system, f"JOB DESCRIPTION:\n\n{jd_text}", max_tokens=1200)
    d.setdefault("target_titles", [])
    d.setdefault("departments", [])
    d.setdefault("seniority", ["Manager", "Director", "Head"])
    d.setdefault("keywords", [])
    for k in ("company_name", "company_domain", "role_title", "location_country", "location_state", "location_city"):
        d.setdefault(k, "")
    d["departments"] = [x for x in d["departments"] if x in DEPARTMENTS] or ["Engineering", "Hiring"]
    d["seniority"] = [x for x in d["seniority"] if x in SENIORITY] or ["Manager", "Director", "Head"]
    return d
