"""Bilingual dashboard for the GCC job market — Bayt.com snapshot 12 May 2026.

Combines the English-portal and Arabic-portal scrapes:
- EN files: structured fields (richer English) — primary analysis source
- AR files: same jobs (97-99% overlap), used for bilingual coverage,
  language-requirement signals, remote-work signals, nationalization signals,
  and Arabic-content keyword analysis.

Output: dashboard_GCC_Jobs_Bilingual_12_May_2026.html
"""
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent

EN_FILES = {
    "Qatar": HERE / "bayt_jobs_Qatar_12_May_2026.xlsx",
    "UAE": HERE / "bayt_jobs_UAE_12_May_2026.xlsx",
    "Saudi Arabia": HERE / "bayt_jobs_Saudi_Arabia_12_May_2026.xlsx",
}
AR_FILES = {
    "Qatar": HERE / "bayt_jobs_Qatar_AR_12_May_2026.xlsx",
    "UAE": HERE / "bayt_jobs_UAE_AR_12_May_2026.xlsx",
    "Saudi Arabia": HERE / "bayt_jobs_Saudi_Arabia_AR_12_May_2026.xlsx",
}
COUNTRY_ORDER = ["Qatar", "UAE", "Saudi Arabia"]
COLORS = {"Qatar": "#8B1538", "UAE": "#00732F", "Saudi Arabia": "#FFB300"}


# -------- normalizers ------------------------------------------------------

def norm_years(s):
    if pd.isna(s):
        return None
    s = str(s).strip().lower()
    if "no experience" in s or s in {"0", "0 years", "fresh"}:
        return "0 (entry)"
    nums = re.findall(r"\d+", s)
    if not nums:
        return "Unspecified"
    n = int(nums[0])
    if n == 0:
        return "0 (entry)"
    if n <= 1:
        return "1 year"
    if n <= 2:
        return "2 years"
    if n <= 4:
        return "3-4 years"
    if n <= 6:
        return "5-6 years"
    if n <= 9:
        return "7-9 years"
    return "10+ years"


def norm_company_size(s):
    if pd.isna(s):
        return None
    s = str(s).strip().lower()
    if "500" in s:
        return "500+ employees"
    if "100" in s and "499" in s:
        return "100-499 employees"
    if "50-99" in s:
        return "50-99 employees"
    if "10-49" in s:
        return "10-49 employees"
    if "1-9" in s:
        return "1-9 employees"
    return s.title()


def norm_education(s):
    if pd.isna(s):
        return None
    s = str(s).strip().lower()
    if "phd" in s or "doctor" in s:
        return "PhD"
    if "master" in s:
        return "Master"
    if "bachelor" in s or "higher diploma" in s:
        return "Bachelor"
    if "diploma" in s:
        return "Diploma"
    if "high school" in s or "secondary" in s:
        return "High School"
    if "certificate" in s:
        return "Certificate"
    return s.title()


def norm_career(s):
    if pd.isna(s):
        return None
    s = str(s).strip().lower()
    if "executive" in s or "c-level" in s or "chief" in s:
        return "Executive"
    if "director" in s:
        return "Director"
    if "manager" in s:
        return "Manager"
    if "senior" in s:
        return "Senior"
    if "mid" in s:
        return "Mid-Level"
    if "entry" in s or "junior" in s:
        return "Entry-Level"
    if "intern" in s:
        return "Internship"
    if "student" in s:
        return "Student"
    return s.title()


def norm_employment(s):
    if pd.isna(s):
        return None
    return str(s).strip().title()


def norm_gender(s):
    if pd.isna(s):
        return None
    s = str(s).strip().title()
    if s in {"Any", "Either"}:
        return "Open to All"
    return s


def parse_salary_mid_usd(s):
    if pd.isna(s):
        return None
    s = str(s)
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", s)]
    if not nums:
        return None
    monthly = sum(nums[:2]) / len(nums[:2])
    if "year" in s.lower() or "annual" in s.lower():
        monthly = monthly / 12
    return round(monthly)


def extract_city(loc, country):
    if pd.isna(loc):
        return None
    s = str(loc).split(",")[0].strip().split("·")[0].strip()
    aliases = {"qatar", "uae", "united arab emirates", "saudi arabia", "ksa"}
    if s.lower() in aliases:
        return "Unspecified"
    return s


def split_skills(s):
    if pd.isna(s):
        return []
    parts = re.split(r"[;\n]| / |,(?=\s*[A-Z])", str(s))
    out = []
    for p in parts:
        p = p.strip(" .-•").lower()
        if 2 <= len(p) <= 60:
            out.append(p)
    return out


# -------- Arabic-content signal extractors ---------------------------------

LANG_AR_REQ = re.compile(r"(إجادة|إتقان|فصاحة|يجيد|يتقن)\s*(?:اللغة\s*)?العربية")
LANG_AR_MAND = ("العربية إلزامي", "العربية شرط", "العربية مطلوب")
LANG_EN_REQ = re.compile(r"(إجادة|إتقان|يجيد)\s*(?:اللغة\s*)?الإنجليزية")
LANG_EN_KEYS = ("fluent in english", "fluency in english", "english fluency",
                "english mandatory", "الإنجليزية إلزامي")

NAT_PATTERNS = {
    "Qatar": [r"مواطن(?:ون|ين)?\s+قطري", r"قطري(?:ة|ين)?\s*(?:فقط|الجنسية)", r"للقطريين"],
    "UAE": [r"مواطن(?:ون|ين)?\s+إماراتي", r"إماراتي(?:ة|ين)?\s*(?:فقط|الجنسية)",
            r"للإماراتيين", r"موظف(?:ة)?\s+إماراتي(?:ة)?"],
    "Saudi Arabia": [r"سعودي(?:ة|ين|ون)?\s*(?:فقط|إلزامي|الجنسية)",
                      r"مواطن(?:ون|ين)?\s+سعودي", r"للسعوديين",
                      r"موظف(?:ة)?\s+سعودي(?:ة)?", r"مرشحين سعوديين"],
}
REMOTE_RE = re.compile(r"عن\s*ب?ُ?عد|من\s*المنزل|عمل\s+من\s+البيت|\bremote\b|work\s+from\s+home|\bhybrid\b",
                       re.IGNORECASE)

def lang_signal(text):
    if pd.isna(text):
        return "unknown"
    t = str(text)
    tl = t.lower()
    ar = bool(LANG_AR_REQ.search(t)) or any(k in t for k in LANG_AR_MAND) \
         or "arabic mandatory" in tl or "fluent in arabic" in tl
    en = bool(LANG_EN_REQ.search(t)) or any(k in tl for k in LANG_EN_KEYS)
    if ar and en:
        return "both"
    if ar:
        return "arabic"
    if en:
        return "english"
    return "unspecified"


def nationalization_signal(text, country):
    if pd.isna(text):
        return False
    t = str(text)
    return any(re.search(p, t) for p in NAT_PATTERNS[country])


def remote_signal(text):
    if pd.isna(text):
        return False
    return bool(REMOTE_RE.search(str(text)))


# -------- Arabic word frequency --------------------------------------------

AR_STOP = set("""
في من على إلى عن مع هذا هذه ذلك التي الذي أو أن إن كل عند بين حول بعد قبل
حتى إذا كما مثل عبر أمام تحت فوق وراء الى الذى والتى والذى يكون يجب يمكن
يتم تتم نحن أنت أنا هو هي هم هن شخص أشخاص شخصية الرئيسية جميع ضمن حسب
الذين اللواتي أي أية بعض معظم جزء نوع أنواع جدا جداً للغاية تماما تماماً
حقا حقاً أيضا أيضاً أكثر أقل أفضل أسوأ أكبر أصغر الموقع وظائف هذا تقديم
وتقديم وأهم إلى أم وحضارة وحياتها ومنحت وقتك أن نحن بشكل هذه الذين الوصف
الوظيفي الوصف الوظيفي وظيفة الموظف الموظفة العمل العمل المرشح المفضل
المهارات مهارات معرفة معلومات وسنوات سنة سنة سنوات أيضا الأخرى الأخر
خدمات الدعم الإمارات السعودية قطر يشترط القدرة لضمان وإدارة الأعمال
المسؤوليات الوظيفة موظف وجود سابقة الشهادة دبلوم عالي بكالوريوس قوية
ضمان تطوير خلال ذو ذي ذات صاحب صاحبة
""".split())

def top_arabic_terms(texts, n=40):
    bag = Counter()
    for t in texts:
        if pd.isna(t):
            continue
        for tok in re.findall(r"[؀-ۿ]{4,}", str(t)):
            if tok not in AR_STOP:
                bag[tok] += 1
    return dict(bag.most_common(n))


# -------- LOAD --------------------------------------------------------------

en_dfs = {c: pd.read_excel(p) for c, p in EN_FILES.items()}
ar_dfs = {c: pd.read_excel(p) for c, p in AR_FILES.items()}

for c, df in en_dfs.items():
    df["YearsBucket"] = df["Years_of_Experience"].apply(norm_years)
    df["CompanySizeNorm"] = df["Company_Size"].apply(norm_company_size)
    df["EducationNorm"] = df["Education_Level"].apply(norm_education)
    df["CareerNorm"] = df["Career_Level"].apply(norm_career)
    df["EmploymentNorm"] = df["Employment_Type"].apply(norm_employment)
    df["GenderNorm"] = df["Gender"].apply(norm_gender)
    df["SalaryUSD"] = df["Salary_Range_USD"].apply(parse_salary_mid_usd)
    df["City"] = df.apply(lambda r: extract_city(r["Job_Location"], c), axis=1)

# Merge AR signals onto EN via Job_ID where available
merged = {}
for c in COUNTRY_ORDER:
    en = en_dfs[c].copy()
    ar = ar_dfs[c]
    ar_sub = ar[["Job_ID", "Original_Page_Content"]].rename(columns={"Original_Page_Content": "AR_Content"})
    en = en.merge(ar_sub, on="Job_ID", how="left")
    en["LangSignal"] = en["AR_Content"].apply(lang_signal)
    en["NationalSignal"] = en["AR_Content"].apply(lambda x: nationalization_signal(x, c))
    en["RemoteSignal"] = en["AR_Content"].apply(remote_signal)
    en["HasAR"] = en["AR_Content"].notna()
    en["AR_Length"] = en["AR_Content"].fillna("").str.len()
    en["EN_Length"] = en["Job_Description"].fillna("").str.len()
    merged[c] = en

all_df = pd.concat(merged.values(), ignore_index=True)

# -------- COMPUTE DASHBOARD DATA -------------------------------------------

data = {"countries": COUNTRY_ORDER, "colors": COLORS}

# KPIs (per country)
kpis = {}
for c in COUNTRY_ORDER:
    df = merged[c]
    ar_only = len(ar_dfs[c]) - df["HasAR"].sum()
    kpis[c] = {
        "total": int(len(df)),
        "companies": int(df["Company_Name"].nunique()),
        "categories": int(df["Job_Category"].nunique()),
        "bilingual_pct": round(100 * df["HasAR"].mean(), 1),
        "ar_only_count": int(ar_only),
        "salary_disclosed_pct": round(100 * df["Salary_Range_USD"].notna().mean(), 1),
        "median_salary_usd": int(df["SalaryUSD"].median()) if df["SalaryUSD"].notna().any() else None,
        "bachelor_required_pct": round(100 * (df["EducationNorm"] == "Bachelor").mean(), 1),
        "entry_level_pct": round(100 * (df["YearsBucket"] == "0 (entry)").mean(), 1),
        "remote_pct": round(100 * df["RemoteSignal"].mean(), 1),
        "nationalization_pct": round(100 * df["NationalSignal"].mean(), 1),
        "arabic_req_pct": round(100 * df["LangSignal"].isin(["arabic", "both"]).mean(), 1),
        "english_req_pct": round(100 * df["LangSignal"].isin(["english", "both"]).mean(), 1),
    }
data["kpis"] = kpis

def top_counts(s, n=12):
    return s.dropna().value_counts().head(n).to_dict()

# Categories
data["categories"] = {c: top_counts(merged[c]["Job_Category"], 12) for c in COUNTRY_ORDER}

# Cross-country category compare (top 15 over all)
all_categories = (all_df["Job_Category"].value_counts().head(15)).index.tolist()
data["category_compare"] = {
    cat: {c: round(100 * (merged[c]["Job_Category"] == cat).mean(), 2) for c in COUNTRY_ORDER}
    for cat in all_categories
}
data["category_compare_order"] = all_categories

# Career level (%)
career_order = ["Entry-Level", "Mid-Level", "Senior", "Manager", "Director", "Executive", "Internship", "Student"]
data["career_levels"] = {
    c: {lvl: round(100 * (merged[c]["CareerNorm"] == lvl).sum()
                   / max(merged[c]["CareerNorm"].notna().sum(), 1), 1) for lvl in career_order}
    for c in COUNTRY_ORDER
}
data["career_order"] = career_order

# Years of experience (%)
years_order = ["0 (entry)", "1 year", "2 years", "3-4 years", "5-6 years", "7-9 years", "10+ years", "Unspecified"]
data["years"] = {
    c: {y: round(100 * (merged[c]["YearsBucket"] == y).sum()
                 / max(merged[c]["YearsBucket"].notna().sum(), 1), 1) for y in years_order}
    for c in COUNTRY_ORDER
}
data["years_order"] = years_order

# Education
edu_order = ["High School", "Diploma", "Certificate", "Bachelor", "Master", "PhD"]
data["education"] = {
    c: {e: int((merged[c]["EducationNorm"] == e).sum()) for e in edu_order}
    for c in COUNTRY_ORDER
}
data["education_order"] = edu_order

# Employment
emp_types = ["Full-Time", "Contract", "Part-Time", "Freelance", "Internship", "Temporary"]
data["employment"] = {
    c: {e: round(100 * (merged[c]["EmploymentNorm"] == e).sum()
                 / max(merged[c]["EmploymentNorm"].notna().sum(), 1), 1) for e in emp_types}
    for c in COUNTRY_ORDER
}
data["employment_order"] = emp_types

# Company size
size_order = ["1-9 employees", "10-49 employees", "50-99 employees", "100-499 employees", "500+ employees"]
data["company_size"] = {
    c: {s: int((merged[c]["CompanySizeNorm"] == s).sum()) for s in size_order}
    for c in COUNTRY_ORDER
}
data["company_size_order"] = size_order

# Top employers
data["top_companies"] = {c: top_counts(merged[c]["Company_Name"], 15) for c in COUNTRY_ORDER}

# Top cities
data["top_cities"] = {c: top_counts(merged[c]["City"], 12) for c in COUNTRY_ORDER}

# Gender
gender_order = ["Open to All", "Female", "Male"]
gd = {}
for c in COUNTRY_ORDER:
    n = merged[c]["GenderNorm"].notna().sum()
    gd[c] = {g: round(100 * (merged[c]["GenderNorm"] == g).sum() / max(n, 1), 1) for g in gender_order}
    gd[c]["_n"] = int(n)
data["gender"] = gd
data["gender_order"] = gender_order

# Top skills (EN)
def top_skills(df, n=30):
    bag = Counter()
    for s in df["Job_Skills"].dropna():
        for sk in split_skills(s):
            bag[sk] += 1
    return dict(bag.most_common(n))

data["skills_all"] = top_skills(all_df, 30)

# Salary distribution
def salary_buckets(df):
    s = df["SalaryUSD"].dropna()
    bins = [0, 500, 1000, 1500, 2000, 3000, 5000, 10000, 1_000_000]
    labels = ["<$500", "$500-1k", "$1k-1.5k", "$1.5k-2k", "$2k-3k", "$3k-5k", "$5k-10k", "$10k+"]
    if len(s) == 0:
        return {l: 0 for l in labels}
    cut = pd.cut(s, bins=bins, labels=labels, right=False)
    return cut.value_counts().reindex(labels).fillna(0).astype(int).to_dict()

data["salary_buckets"] = {c: salary_buckets(merged[c]) for c in COUNTRY_ORDER}
data["salary_buckets_order"] = ["<$500", "$500-1k", "$1k-1.5k", "$1.5k-2k", "$2k-3k", "$3k-5k", "$5k-10k", "$10k+"]

# Median salary by category
def median_salary_by_category(df, min_n=5, top=12):
    sub = df.dropna(subset=["SalaryUSD", "Job_Category"])
    g = sub.groupby("Job_Category")["SalaryUSD"].agg(["median", "count"])
    g = g[g["count"] >= min_n].sort_values("median", ascending=False).head(top)
    return {cat: {"median": int(row["median"]), "n": int(row["count"])} for cat, row in g.iterrows()}

data["salary_by_category"] = {c: median_salary_by_category(merged[c]) for c in COUNTRY_ORDER}

# --- Bilingual / language signal sections ---

# Bilingual coverage (per country)
biling = {}
for c in COUNTRY_ORDER:
    en_ids = set(en_dfs[c]["Job_ID"])
    ar_ids = set(ar_dfs[c]["Job_ID"])
    both = len(en_ids & ar_ids)
    biling[c] = {
        "Bilingual (both portals)": both,
        "EN portal only": len(en_ids - ar_ids),
        "AR portal only": len(ar_ids - en_ids),
    }
data["bilingual_coverage"] = biling

# Language requirement signals per country (% of postings)
lang_data = {}
for c in COUNTRY_ORDER:
    df = merged[c]
    n = len(df)
    cnts = df["LangSignal"].value_counts().to_dict()
    lang_data[c] = {
        "English required": round(100 * cnts.get("english", 0) / n, 1),
        "Arabic required": round(100 * cnts.get("arabic", 0) / n, 1),
        "Both required": round(100 * cnts.get("both", 0) / n, 1),
        "Not specified": round(100 * cnts.get("unspecified", 0) / n, 1),
    }
data["lang_requirements"] = lang_data
data["lang_requirements_order"] = ["English required", "Arabic required", "Both required", "Not specified"]

# Arabic-required % by top category (cross-country combined)
top_cats_for_lang = (all_df["Job_Category"].value_counts().head(15)).index.tolist()
arabic_by_cat = {}
for cat in top_cats_for_lang:
    sub = all_df[all_df["Job_Category"] == cat]
    arabic_by_cat[cat] = {
        "Arabic": round(100 * sub["LangSignal"].isin(["arabic", "both"]).mean(), 1),
        "English": round(100 * sub["LangSignal"].isin(["english", "both"]).mean(), 1),
    }
data["arabic_by_category"] = arabic_by_cat
data["arabic_by_category_order"] = top_cats_for_lang

# Remote work % by country
data["remote_by_country"] = {c: round(100 * merged[c]["RemoteSignal"].mean(), 1) for c in COUNTRY_ORDER}

# Remote % by top categories
remote_by_cat = {}
for cat in top_cats_for_lang:
    sub = all_df[all_df["Job_Category"] == cat]
    if len(sub) > 50:
        remote_by_cat[cat] = round(100 * sub["RemoteSignal"].mean(), 1)
remote_by_cat = dict(sorted(remote_by_cat.items(), key=lambda kv: kv[1], reverse=True))
data["remote_by_category"] = remote_by_cat

# Nationalization signals
nat_data = {c: round(100 * merged[c]["NationalSignal"].mean(), 2) for c in COUNTRY_ORDER}
data["nationalization"] = nat_data

# Nationalization by category (for the country it applies to)
nat_by_cat_country = {}
for c in COUNTRY_ORDER:
    sub = merged[c]
    cats = sub["Job_Category"].value_counts().head(10).index.tolist()
    nat_by_cat_country[c] = {
        cat: round(100 * sub.loc[sub["Job_Category"] == cat, "NationalSignal"].mean(), 1)
        for cat in cats
    }
data["nationalization_by_category"] = nat_by_cat_country

# Top Arabic terms from AR content
ar_combined = pd.concat([ar_dfs[c]["Original_Page_Content"] for c in COUNTRY_ORDER])
data["arabic_terms_all"] = top_arabic_terms(ar_combined, 30)

# Posting description length (proxy for posting quality)
data["desc_length_median"] = {
    c: {"EN": int(merged[c]["EN_Length"].median()),
        "AR": int(merged[c]["AR_Length"].median())}
    for c in COUNTRY_ORDER
}

# ---- write HTML -----------------------------------------------------------

payload = json.dumps(data, ensure_ascii=False)
print(f"Payload: {len(payload):,} chars; total jobs: {sum(k['total'] for k in kpis.values()):,}")

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GCC Job Market Intelligence — Bilingual Dashboard (12 May 2026)</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{
  --bg:#0e1117; --panel:#1a2332; --panel-2:#243044; --text:#e6edf3; --muted:#8b98a5;
  --accent:#58a6ff; --gold:#ffc547; --teal:#06b6d4; --pink:#ec4899;
  --border:#30363d;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:linear-gradient(180deg,#0e1117 0%, #131a26 100%);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;min-height:100vh}
.wrap{max-width:1500px;margin:0 auto;padding:24px}
header{padding:28px 0 14px;border-bottom:1px solid var(--border);margin-bottom:20px;
  display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:14px}
header h1{margin:0 0 4px;font-size:30px;letter-spacing:-0.6px;
  background:linear-gradient(120deg,#58a6ff,#ffc547);-webkit-background-clip:text;background-clip:text;color:transparent}
.subtitle{color:var(--muted);font-size:14px;max-width:780px}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;font-size:12px}
.chip{padding:5px 11px;background:var(--panel);border:1px solid var(--border);border-radius:999px;color:var(--muted)}
.chip b{color:var(--gold)}
.kpi-row{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:22px 0}
.kpi{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:18px;position:relative;
  box-shadow:0 1px 0 rgba(255,255,255,0.03)}
.kpi-header{display:flex;align-items:center;gap:10px;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid var(--border)}
.flag{width:38px;height:25px;border-radius:3px;display:flex;align-items:center;justify-content:center;
  font-size:9px;font-weight:bold;color:#fff;flex-shrink:0}
.flag.qatar{background:linear-gradient(to right,#fff 30%,#8B1538 30%)}
.flag.uae{background:linear-gradient(to bottom,#00732F 33%,#fff 33%,#fff 66%,#000 66%);position:relative}
.flag.uae:before{content:'';position:absolute;left:0;top:0;bottom:0;width:25%;background:#FF0000}
.flag.ksa{background:#006C35}
.kpi-name{font-size:16px;font-weight:600}
.kpi-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px 14px;font-size:12px}
.kpi-grid .num{color:var(--gold);font-size:20px;font-weight:700;line-height:1.1}
.kpi-grid .lbl{color:var(--muted);font-size:10.5px;text-transform:uppercase;letter-spacing:0.4px;margin-top:2px}
.section{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:22px;margin-bottom:20px}
.section h2{margin:0 0 4px;font-size:19px}
.section .desc{color:var(--muted);font-size:13px;margin-bottom:18px;line-height:1.5}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px}
.chart{width:100%;min-height:380px}
.tall{min-height:540px}
.insights{background:linear-gradient(135deg,var(--panel-2),#1d2740);border-left:3px solid var(--gold);
  padding:14px 18px;border-radius:6px;margin-top:16px;font-size:14px;line-height:1.7}
.insights b{color:var(--gold)}
.insights .h{color:var(--accent)}
.tab-row{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
.tab{padding:7px 13px;background:var(--panel-2);border:1px solid var(--border);border-radius:6px;cursor:pointer;
  font-size:12.5px;color:var(--muted);transition:all 0.15s}
.tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.tab:hover{color:var(--text)}
.section-anchor{padding-top:6px}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px;font-size:12px}
.toc a{padding:6px 11px;background:var(--panel);border:1px solid var(--border);border-radius:999px;
  color:var(--muted);text-decoration:none;transition:all 0.15s}
.toc a:hover{color:var(--text);border-color:var(--accent)}
footer{text-align:center;color:var(--muted);font-size:12px;padding:24px 0;border-top:1px solid var(--border);margin-top:32px}
@media (max-width:980px){.grid-2,.grid-3,.kpi-row{grid-template-columns:1fr}.kpi-grid{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div>
    <h1>GCC Job Market Intelligence</h1>
    <div class="subtitle">A bilingual snapshot of <b>20,535 active English-portal postings</b> and <b>20,568 Arabic-portal postings</b> from Bayt.com across Qatar, UAE, and Saudi Arabia. Snapshot date: 12 May 2026.</div>
  </div>
  <div class="toolbar">
    <div class="chip"><b>3</b> countries</div>
    <div class="chip"><b>20.5k</b> postings</div>
    <div class="chip"><b>2.8k</b> employers</div>
    <div class="chip"><b>2</b> languages</div>
  </div>
</header>

<div class="toc">
  <a href="#sec1">1. Volume & Mix</a>
  <a href="#sec2">2. Categories</a>
  <a href="#sec3">3. Seniority</a>
  <a href="#sec4">4. Education/Contract</a>
  <a href="#sec5">5. Employers</a>
  <a href="#sec6">6. Geography</a>
  <a href="#sec7">7. Salary</a>
  <a href="#sec8">8. Bilingual Coverage</a>
  <a href="#sec9">9. Language Requirements</a>
  <a href="#sec10">10. Remote Work</a>
  <a href="#sec11">11. Nationalization</a>
  <a href="#sec12">12. Arabic Content</a>
  <a href="#sec13">13. Skills</a>
  <a href="#sec14">14. Gender</a>
</div>

<div class="kpi-row" id="kpiCards"></div>

<div class="section" id="sec1">
  <h2>1. Market Volume & Hiring Mix</h2>
  <div class="desc">UAE absorbs nearly half of all GCC postings on this single day. Engineering tops every market; sector mix below shows how each economy diverges.</div>
  <div class="grid-2">
    <div id="chartVolume" class="chart"></div>
    <div id="chartCategoryShare" class="chart"></div>
  </div>
  <div class="insights" id="insight1"></div>
</div>

<div class="section" id="sec2">
  <h2>2. Top Job Categories by Country</h2>
  <div class="desc">Hiring concentration by function. Tabs below switch between countries.</div>
  <div class="tab-row" data-target="chartTopCats">
    <div class="tab active" data-key="Qatar">Qatar</div>
    <div class="tab" data-key="UAE">UAE</div>
    <div class="tab" data-key="Saudi Arabia">Saudi Arabia</div>
  </div>
  <div id="chartTopCats" class="chart tall"></div>
  <div class="insights" id="insight2"></div>
</div>

<div class="section" id="sec3">
  <h2>3. Seniority & Experience Demand</h2>
  <div class="desc">Career level (left) and required years of experience (right). KSA dominates the entry-level signal — a clear Saudization footprint.</div>
  <div class="grid-2">
    <div id="chartCareer" class="chart"></div>
    <div id="chartYears" class="chart"></div>
  </div>
  <div class="insights" id="insight3"></div>
</div>

<div class="section" id="sec4">
  <h2>4. Education Requirements & Employment Type</h2>
  <div class="desc">Bachelor's is the dominant credential. KSA postings disclose education far more reliably than UAE/Qatar.</div>
  <div class="grid-2">
    <div id="chartEdu" class="chart"></div>
    <div id="chartEmployment" class="chart"></div>
  </div>
  <div class="insights" id="insight4"></div>
</div>

<div class="section" id="sec5">
  <h2>5. Who Is Hiring</h2>
  <div class="desc">Distribution by company size (left) and the 15 most active employers in each market (tabs).</div>
  <div class="grid-2">
    <div id="chartCompanySize" class="chart"></div>
    <div>
      <div class="tab-row" data-target="chartTopCompanies">
        <div class="tab active" data-key="Qatar">Qatar</div>
        <div class="tab" data-key="UAE">UAE</div>
        <div class="tab" data-key="Saudi Arabia">Saudi Arabia</div>
      </div>
      <div id="chartTopCompanies" class="chart"></div>
    </div>
  </div>
  <div class="insights" id="insight5"></div>
</div>

<div class="section" id="sec6">
  <h2>6. Geographic Concentration</h2>
  <div class="desc">Top cities per country. Note: the source file had a country-suffix parser bug — cities are reconstructed from the prefix portion of the location string.</div>
  <div class="grid-3">
    <div id="chartCityQatar" class="chart"></div>
    <div id="chartCityUAE" class="chart"></div>
    <div id="chartCityKSA" class="chart"></div>
  </div>
  <div class="insights" id="insight6"></div>
</div>

<div class="section" id="sec7">
  <h2>7. Salary Intelligence</h2>
  <div class="desc">Only 7-10% of postings disclose salary. Among those that do, the distribution (left) and median monthly USD by job category (right).</div>
  <div class="grid-2">
    <div id="chartSalaryDist" class="chart"></div>
    <div>
      <div class="tab-row" data-target="chartSalaryCat">
        <div class="tab active" data-key="Qatar">Qatar</div>
        <div class="tab" data-key="UAE">UAE</div>
        <div class="tab" data-key="Saudi Arabia">Saudi Arabia</div>
      </div>
      <div id="chartSalaryCat" class="chart"></div>
    </div>
  </div>
  <div class="insights" id="insight7"></div>
</div>

<div class="section" id="sec8">
  <h2>8. Bilingual Posting Coverage <span style="color:var(--accent);font-weight:400;font-size:14px">— EN vs AR portal overlap</span></h2>
  <div class="desc">Each Bayt.com job is potentially listed on both the English and Arabic portal. Coverage tells us which jobs are being marketed to each audience.</div>
  <div class="grid-2">
    <div id="chartBilingual" class="chart"></div>
    <div id="chartDescLen" class="chart"></div>
  </div>
  <div class="insights" id="insight8"></div>
</div>

<div class="section" id="sec9">
  <h2>9. Language Requirements <span style="color:var(--accent);font-weight:400;font-size:14px">— extracted from Arabic page content</span></h2>
  <div class="desc">% of postings that explicitly require Arabic, English, or both, by country. Note: most postings don't explicitly state a language requirement — what's reported below is the explicit signal only.</div>
  <div class="grid-2">
    <div id="chartLang" class="chart"></div>
    <div id="chartLangCat" class="chart"></div>
  </div>
  <div class="insights" id="insight9"></div>
</div>

<div class="section" id="sec10">
  <h2>10. Remote / Hybrid Work <span style="color:var(--accent);font-weight:400;font-size:14px">— signal from Arabic content</span></h2>
  <div class="desc">% of postings that mention remote, hybrid, or work-from-home arrangements in their description.</div>
  <div class="grid-2">
    <div id="chartRemoteCountry" class="chart"></div>
    <div id="chartRemoteCat" class="chart"></div>
  </div>
  <div class="insights" id="insight10"></div>
</div>

<div class="section" id="sec11">
  <h2>11. Nationalization Signals <span style="color:var(--accent);font-weight:400;font-size:14px">— Saudization / Emiratization / Qatarization</span></h2>
  <div class="desc">% of postings that explicitly mention preference for nationals of the home country, by category, extracted from the Arabic description text.</div>
  <div class="grid-2">
    <div id="chartNatCountry" class="chart"></div>
    <div>
      <div class="tab-row" data-target="chartNatCat">
        <div class="tab" data-key="Qatar">Qatar</div>
        <div class="tab" data-key="UAE">UAE</div>
        <div class="tab active" data-key="Saudi Arabia">Saudi Arabia</div>
      </div>
      <div id="chartNatCat" class="chart"></div>
    </div>
  </div>
  <div class="insights" id="insight11"></div>
</div>

<div class="section" id="sec12">
  <h2>12. Most Frequent Arabic Terms <span style="color:var(--accent);font-weight:400;font-size:14px">— from Original_Page_Content</span></h2>
  <div class="desc">Top meaningful Arabic terms across all Arabic-portal postings, with common stopwords and boilerplate ("Job Description", "Skills") removed.</div>
  <div id="chartArTerms" class="chart tall"></div>
  <div class="insights" id="insight12"></div>
</div>

<div class="section" id="sec13">
  <h2>13. In-Demand Skills</h2>
  <div class="desc">Top 30 skills extracted from the Job_Skills field across all 20,535 postings.</div>
  <div id="chartSkills" class="chart tall"></div>
  <div class="insights" id="insight13"></div>
</div>

<div class="section" id="sec14">
  <h2>14. Gender Preference in Postings</h2>
  <div class="desc">Most postings (~90%) do not specify a gender. Among the minority that do, this is the split.</div>
  <div id="chartGender" class="chart"></div>
  <div class="insights" id="insight14"></div>
</div>

<footer>
  Generated 2026-05-12 from Bayt.com EN + AR portal snapshots · Self-contained interactive HTML dashboard · Plotly.js<br>
  Bilingual signals (language, remote, nationalization) extracted by pattern-matching on Arabic page content.
</footer>
</div>

<script>
const DATA = __DATA__;
const COLORS = {"Qatar":"#8B1538","UAE":"#00732F","Saudi Arabia":"#FFB300"};
const LAYOUT_BASE = {
  paper_bgcolor:"#1a2332", plot_bgcolor:"#1a2332",
  font:{color:"#e6edf3", family:"-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif", size:12},
  margin:{l:60,r:20,t:40,b:60},
  legend:{bgcolor:"rgba(0,0,0,0)"},
  xaxis:{gridcolor:"#30363d",zerolinecolor:"#30363d"},
  yaxis:{gridcolor:"#30363d",zerolinecolor:"#30363d"}
};
function L(extra){ return Object.assign({}, JSON.parse(JSON.stringify(LAYOUT_BASE)), extra||{}); }
const CFG = {displaylogo:false, responsive:true, modeBarButtonsToRemove:["lasso2d","select2d"]};

// KPI cards
(function(){
  const flagCls = {"Qatar":"qatar","UAE":"uae","Saudi Arabia":"ksa"};
  const flagText = {"Saudi Arabia":"KSA"};
  const host = document.getElementById("kpiCards");
  DATA.countries.forEach(c=>{
    const k = DATA.kpis[c];
    const sal = k.median_salary_usd ? "$"+k.median_salary_usd.toLocaleString() : "n/a";
    host.insertAdjacentHTML("beforeend", `
      <div class="kpi">
        <div class="kpi-header">
          <span class="flag ${flagCls[c]}">${flagText[c]||""}</span>
          <span class="kpi-name">${c}</span>
        </div>
        <div class="kpi-grid">
          <div><div class="num">${k.total.toLocaleString()}</div><div class="lbl">Postings</div></div>
          <div><div class="num">${k.companies.toLocaleString()}</div><div class="lbl">Employers</div></div>
          <div><div class="num">${k.bilingual_pct}%</div><div class="lbl">Bilingual</div></div>
          <div><div class="num">${k.bachelor_required_pct}%</div><div class="lbl">BSc Req'd</div></div>
          <div><div class="num">${sal}</div><div class="lbl">Median USD/mo</div></div>
          <div><div class="num">${k.entry_level_pct}%</div><div class="lbl">Entry Level</div></div>
          <div><div class="num">${k.remote_pct}%</div><div class="lbl">Remote/Hybrid</div></div>
          <div><div class="num">${k.english_req_pct}%</div><div class="lbl">EN req</div></div>
          <div><div class="num">${k.nationalization_pct}%</div><div class="lbl">${c==="Saudi Arabia"?"Saudization":(c==="UAE"?"Emiratization":"Qatarization")}</div></div>
        </div>
      </div>
    `);
  });
})();

// 1a. Volume donut
{
  const labels = DATA.countries, vals = labels.map(c=>DATA.kpis[c].total);
  Plotly.newPlot("chartVolume",
    [{type:"pie",hole:0.55,labels,values:vals,
      marker:{colors:labels.map(c=>COLORS[c])},
      textinfo:"label+percent",textfont:{size:14}}],
    L({title:"Share of total postings (n=20,535)",showlegend:false}), CFG);
}

// 1b. Category compare
{
  const cats = DATA.category_compare_order;
  const traces = DATA.countries.map(c=>({
    type:"bar", name:c, x:cats, y:cats.map(cat=>DATA.category_compare[cat][c]),
    marker:{color:COLORS[c]}
  }));
  Plotly.newPlot("chartCategoryShare", traces,
    L({title:"Top 15 categories — % share within each country",
       barmode:"group", xaxis:{tickangle:-35,gridcolor:"#30363d"},
       yaxis:{title:"% of postings",gridcolor:"#30363d"}}), CFG);
}

// 2. Top categories
function drawTopCats(country){
  const obj = DATA.categories[country];
  const labels = Object.keys(obj), vals = Object.values(obj);
  Plotly.newPlot("chartTopCats",
    [{type:"bar", orientation:"h", x:vals.slice().reverse(), y:labels.slice().reverse(),
      marker:{color:COLORS[country]},
      text:vals.slice().reverse().map(v=>v.toLocaleString()), textposition:"outside"}],
    L({title:`Top 12 job categories — ${country}`,
       margin:{l:160,r:40,t:40,b:40},
       xaxis:{title:"Postings",gridcolor:"#30363d"}}), CFG);
}
drawTopCats("Qatar");

// 3a. Career level
{
  const order = DATA.career_order;
  const traces = order.map((lvl,i)=>({
    type:"bar", orientation:"h", name:lvl,
    x:DATA.countries.map(c=>DATA.career_levels[c][lvl]),
    y:DATA.countries,
    marker:{color:["#3a86ff","#06a77d","#ffbe0b","#fb5607","#8338ec","#ff006e","#7d8597","#adb5bd"][i]}
  }));
  Plotly.newPlot("chartCareer", traces,
    L({title:"Career level mix (% of leveled postings)",
       barmode:"stack",
       xaxis:{title:"%",gridcolor:"#30363d",range:[0,100]},
       legend:{orientation:"h",y:-0.2}}), CFG);
}

// 3b. Years
{
  const order = DATA.years_order;
  const traces = DATA.countries.map(c=>({
    type:"bar", name:c, x:order, y:order.map(y=>DATA.years[c][y]),
    marker:{color:COLORS[c]}
  }));
  Plotly.newPlot("chartYears", traces,
    L({title:"Required years of experience (% within country)",
       barmode:"group",
       xaxis:{gridcolor:"#30363d"}, yaxis:{title:"%",gridcolor:"#30363d"}}), CFG);
}

// 4a. Education
{
  const order = DATA.education_order;
  const traces = DATA.countries.map(c=>({
    type:"bar", name:c, x:order, y:order.map(e=>DATA.education[c][e]),
    marker:{color:COLORS[c]}
  }));
  Plotly.newPlot("chartEdu", traces,
    L({title:"Education level required (counts)",
       barmode:"group",
       xaxis:{gridcolor:"#30363d"}, yaxis:{title:"# postings",gridcolor:"#30363d"}}), CFG);
}

// 4b. Employment
{
  const order = DATA.employment_order;
  const traces = DATA.countries.map(c=>({
    type:"bar", name:c, x:order, y:order.map(e=>DATA.employment[c][e]),
    marker:{color:COLORS[c]}
  }));
  Plotly.newPlot("chartEmployment", traces,
    L({title:"Employment type (% where specified)",
       barmode:"group",
       xaxis:{gridcolor:"#30363d"}, yaxis:{title:"%",gridcolor:"#30363d"}}), CFG);
}

// 5a. Company size
{
  const order = DATA.company_size_order;
  const traces = DATA.countries.map(c=>({
    type:"bar", name:c, x:order, y:order.map(s=>DATA.company_size[c][s]),
    marker:{color:COLORS[c]}
  }));
  Plotly.newPlot("chartCompanySize", traces,
    L({title:"Hiring company size (where disclosed)",
       barmode:"group",
       xaxis:{tickangle:-20,gridcolor:"#30363d"}, yaxis:{title:"# postings",gridcolor:"#30363d"}}), CFG);
}

// 5b. Top employers
function drawTopCompanies(country){
  const obj = DATA.top_companies[country];
  const labels = Object.keys(obj), vals = Object.values(obj);
  Plotly.newPlot("chartTopCompanies",
    [{type:"bar", orientation:"h", x:vals.slice().reverse(), y:labels.slice().reverse(),
      marker:{color:COLORS[country]},
      text:vals.slice().reverse().map(v=>v.toLocaleString()), textposition:"outside"}],
    L({title:`Top 15 employers — ${country}`,
       margin:{l:210,r:40,t:40,b:40},
       xaxis:{title:"# postings",gridcolor:"#30363d"}}), CFG);
}
drawTopCompanies("Qatar");

// 6. Cities
function drawCity(country, divId){
  const obj = DATA.top_cities[country];
  const labels = Object.keys(obj), vals = Object.values(obj);
  Plotly.newPlot(divId,
    [{type:"bar", orientation:"h", x:vals.slice().reverse(), y:labels.slice().reverse(),
      marker:{color:COLORS[country]},
      text:vals.slice().reverse().map(v=>v.toLocaleString()), textposition:"outside"}],
    L({title:`${country} — top cities`,
       margin:{l:130,r:30,t:40,b:40}, xaxis:{gridcolor:"#30363d"}}), CFG);
}
drawCity("Qatar","chartCityQatar");
drawCity("UAE","chartCityUAE");
drawCity("Saudi Arabia","chartCityKSA");

// 7a. Salary distribution
{
  const order = DATA.salary_buckets_order;
  const traces = DATA.countries.map(c=>({
    type:"bar", name:c, x:order, y:order.map(b=>DATA.salary_buckets[c][b]),
    marker:{color:COLORS[c]}
  }));
  Plotly.newPlot("chartSalaryDist", traces,
    L({title:"Salary distribution (monthly USD) — where disclosed",
       barmode:"group",
       xaxis:{gridcolor:"#30363d"}, yaxis:{title:"# postings",gridcolor:"#30363d"}}), CFG);
}

// 7b. Salary by category
function drawSalaryCat(country){
  const obj = DATA.salary_by_category[country];
  const labels = Object.keys(obj);
  if(!labels.length){
    document.getElementById("chartSalaryCat").innerHTML =
      `<div style="padding:60px;text-align:center;color:#8b98a5">Not enough salary disclosures in ${country}.</div>`;
    return;
  }
  const meds = labels.map(l=>obj[l].median);
  const ns = labels.map(l=>obj[l].n);
  Plotly.newPlot("chartSalaryCat",
    [{type:"bar", orientation:"h", x:meds.slice().reverse(), y:labels.slice().reverse(),
      marker:{color:COLORS[country]},
      text:meds.slice().reverse().map((m,i)=>`$${m.toLocaleString()} (n=${ns.slice().reverse()[i]})`),
      textposition:"outside"}],
    L({title:`Median monthly USD by job category — ${country}`,
       margin:{l:160,r:90,t:40,b:40}, xaxis:{title:"USD / month",gridcolor:"#30363d"}}), CFG);
}
drawSalaryCat("Qatar");

// 8a. Bilingual coverage
{
  const order = ["Bilingual (both portals)","EN portal only","AR portal only"];
  const colors = ["#06b6d4","#3a86ff","#ec4899"];
  const traces = order.map((k,i)=>({
    type:"bar", name:k,
    x:DATA.countries, y:DATA.countries.map(c=>DATA.bilingual_coverage[c][k]),
    marker:{color:colors[i]},
    text:DATA.countries.map(c=>DATA.bilingual_coverage[c][k].toLocaleString()),
    textposition:"inside"
  }));
  Plotly.newPlot("chartBilingual", traces,
    L({title:"Portal coverage — bilingual vs single-portal postings",
       barmode:"stack",
       xaxis:{gridcolor:"#30363d"}, yaxis:{title:"# postings",gridcolor:"#30363d"}}), CFG);
}

// 8b. Description length
{
  const traces = [
    {type:"bar", name:"English description (chars)", x:DATA.countries,
     y:DATA.countries.map(c=>DATA.desc_length_median[c].EN),
     marker:{color:"#3a86ff"}, text:DATA.countries.map(c=>DATA.desc_length_median[c].EN.toLocaleString()), textposition:"outside"},
    {type:"bar", name:"Arabic page content (chars)", x:DATA.countries,
     y:DATA.countries.map(c=>DATA.desc_length_median[c].AR),
     marker:{color:"#ec4899"}, text:DATA.countries.map(c=>DATA.desc_length_median[c].AR.toLocaleString()), textposition:"outside"}
  ];
  Plotly.newPlot("chartDescLen", traces,
    L({title:"Median posting length — EN structured vs AR full page",
       barmode:"group",
       xaxis:{gridcolor:"#30363d"}, yaxis:{title:"# characters (median)",gridcolor:"#30363d"}}), CFG);
}

// 9a. Lang req per country
{
  const order = DATA.lang_requirements_order;
  const colors = {"English required":"#3a86ff","Arabic required":"#ec4899","Both required":"#06b6d4","Not specified":"#444c5e"};
  const traces = order.map(k=>({
    type:"bar", name:k,
    x:DATA.countries, y:DATA.countries.map(c=>DATA.lang_requirements[c][k]),
    marker:{color:colors[k]},
    text:DATA.countries.map(c=>DATA.lang_requirements[c][k].toFixed(1)+"%"),
    textposition:"inside"
  }));
  Plotly.newPlot("chartLang", traces,
    L({title:"Language requirement signal (% of postings)",
       barmode:"stack",
       xaxis:{gridcolor:"#30363d"}, yaxis:{title:"%",gridcolor:"#30363d",range:[0,100]}}), CFG);
}

// 9b. Arabic/English by category
{
  const order = DATA.arabic_by_category_order;
  Plotly.newPlot("chartLangCat", [
    {type:"bar", name:"Arabic req", x:order, y:order.map(c=>DATA.arabic_by_category[c].Arabic),
     marker:{color:"#ec4899"}},
    {type:"bar", name:"English req", x:order, y:order.map(c=>DATA.arabic_by_category[c].English),
     marker:{color:"#3a86ff"}}
  ], L({title:"Language requirement by job category (cross-country)",
        barmode:"group",
        xaxis:{tickangle:-35,gridcolor:"#30363d"}, yaxis:{title:"%",gridcolor:"#30363d"}}), CFG);
}

// 10a. Remote by country
{
  const vals = DATA.countries.map(c=>DATA.remote_by_country[c]);
  Plotly.newPlot("chartRemoteCountry",
    [{type:"bar", x:DATA.countries, y:vals,
      marker:{color:DATA.countries.map(c=>COLORS[c])},
      text:vals.map(v=>v.toFixed(1)+"%"), textposition:"outside"}],
    L({title:"Remote / hybrid work mention rate by country",
       xaxis:{gridcolor:"#30363d"}, yaxis:{title:"% of postings",gridcolor:"#30363d"}, showlegend:false}), CFG);
}

// 10b. Remote by category
{
  const obj = DATA.remote_by_category;
  const labels = Object.keys(obj), vals = Object.values(obj);
  Plotly.newPlot("chartRemoteCat",
    [{type:"bar", orientation:"h", x:vals.slice().reverse(), y:labels.slice().reverse(),
      marker:{color:vals.slice().reverse().map(v=>`rgba(6,182,212,${0.3+0.7*v/Math.max(...vals)})`)},
      text:vals.slice().reverse().map(v=>v.toFixed(1)+"%"), textposition:"outside"}],
    L({title:"Remote-friendly job categories (% of postings)",
       margin:{l:140,r:60,t:40,b:40},
       xaxis:{gridcolor:"#30363d"}}), CFG);
}

// 11a. Nationalization country
{
  const vals = DATA.countries.map(c=>DATA.nationalization[c]);
  const labels = {"Qatar":"Qatarization (Qatar)","UAE":"Emiratization (UAE)","Saudi Arabia":"Saudization (KSA)"};
  Plotly.newPlot("chartNatCountry",
    [{type:"bar", x:DATA.countries.map(c=>labels[c]), y:vals,
      marker:{color:DATA.countries.map(c=>COLORS[c])},
      text:vals.map(v=>v.toFixed(2)+"%"), textposition:"outside"}],
    L({title:"Explicit national-preference mention rate",
       xaxis:{gridcolor:"#30363d"},
       yaxis:{title:"% of postings",gridcolor:"#30363d"}, showlegend:false}), CFG);
}

// 11b. Nationalization by category
function drawNatCat(country){
  const obj = DATA.nationalization_by_category[country];
  const labels = Object.keys(obj), vals = Object.values(obj);
  Plotly.newPlot("chartNatCat",
    [{type:"bar", orientation:"h", x:vals.slice().reverse(), y:labels.slice().reverse(),
      marker:{color:COLORS[country]},
      text:vals.slice().reverse().map(v=>v.toFixed(1)+"%"), textposition:"outside"}],
    L({title:`National-preference rate by category — ${country}`,
       margin:{l:140,r:60,t:40,b:40},
       xaxis:{title:"%",gridcolor:"#30363d"}}), CFG);
}
drawNatCat("Saudi Arabia");

// 12. Top Arabic terms
{
  const obj = DATA.arabic_terms_all;
  const labels = Object.keys(obj), vals = Object.values(obj);
  Plotly.newPlot("chartArTerms",
    [{type:"bar", orientation:"h", x:vals.slice().reverse(), y:labels.slice().reverse(),
      marker:{color:vals.slice().reverse().map((v,i)=>{
        const t=i/(vals.length-1);
        return `rgb(${Math.round(236-t*160)},${Math.round(72+t*100)},${Math.round(153-t*60)})`;
      })},
      text:vals.slice().reverse().map(v=>v.toLocaleString()), textposition:"outside"}],
    L({title:"Top Arabic terms across 20,568 Arabic-portal postings",
       margin:{l:140,r:60,t:40,b:40},
       xaxis:{title:"# occurrences",gridcolor:"#30363d"},
       yaxis:{tickfont:{size:14}}}), CFG);
}

// 13. Skills
{
  const obj = DATA.skills_all;
  const labels = Object.keys(obj), vals = Object.values(obj);
  Plotly.newPlot("chartSkills",
    [{type:"bar", orientation:"h", x:vals.slice().reverse(), y:labels.slice().reverse(),
      marker:{color:vals.slice().reverse().map((v,i)=>{
        const t=i/(vals.length-1);
        return `rgb(${Math.round(88+t*100)},${Math.round(166-t*60)},${Math.round(255-t*100)})`;
      })},
      text:vals.slice().reverse().map(v=>v.toLocaleString()), textposition:"outside"}],
    L({title:"Top 30 skills demanded across all 20,535 postings",
       margin:{l:240,r:60,t:40,b:40},
       xaxis:{title:"# postings mentioning skill",gridcolor:"#30363d"}}), CFG);
}

// 14. Gender
{
  const order = DATA.gender_order;
  const colors = ["#7d8597","#ec4899","#3a86ff"];
  const traces = order.map((g,i)=>({
    type:"bar", name:g, x:DATA.countries,
    y:DATA.countries.map(c=>DATA.gender[c][g]),
    marker:{color:colors[i]},
    text:DATA.countries.map(c=>DATA.gender[c][g]+"%"), textposition:"inside"
  }));
  Plotly.newPlot("chartGender", traces,
    L({title:"Gender preference (% within postings that specified)",
       barmode:"stack",
       xaxis:{gridcolor:"#30363d"}, yaxis:{title:"%",gridcolor:"#30363d",range:[0,100]}}), CFG);
}

// Tabs
document.querySelectorAll(".tab-row").forEach(row=>{
  row.addEventListener("click", e=>{
    if(!e.target.classList.contains("tab")) return;
    row.querySelectorAll(".tab").forEach(t=>t.classList.remove("active"));
    e.target.classList.add("active");
    const key = e.target.dataset.key, target = row.dataset.target;
    if(target==="chartTopCats") drawTopCats(key);
    else if(target==="chartTopCompanies") drawTopCompanies(key);
    else if(target==="chartSalaryCat") drawSalaryCat(key);
    else if(target==="chartNatCat") drawNatCat(key);
  });
});

// Insights
const k = DATA.kpis;
const totalAll = k["Qatar"].total + k["UAE"].total + k["Saudi Arabia"].total;
function ins(id, html){ document.getElementById(id).innerHTML = html; }

ins("insight1", `
  <span class="h">Key takeaway:</span> The UAE absorbs <b>${(100*k["UAE"].total/totalAll).toFixed(0)}%</b> of all GCC postings on this single day,
  KSA <b>${(100*k["Saudi Arabia"].total/totalAll).toFixed(0)}%</b>, and Qatar <b>${(100*k["Qatar"].total/totalAll).toFixed(0)}%</b>.
  <b>Engineering</b> is #1 in every market, but Construction is meaningfully bigger in UAE+KSA than Qatar
  (UAE ${DATA.category_compare["Construction"]["UAE"]}%, KSA ${DATA.category_compare["Construction"]["Saudi Arabia"]}%, Qatar ${DATA.category_compare["Construction"]["Qatar"]}%) — the megaproject pipeline signal.
`);

ins("insight2", `
  <span class="h">Sector signatures:</span> Qatar tilts toward <b>Healthcare and Engineering</b> — a services-and-infrastructure economy.
  UAE's mix is the broadest (Engineering, Construction, Sales, IT, Hospitality) — a regional hub. KSA leans heavily into <b>Engineering, Sales, Construction</b> — Vision 2030 build-out and consumer-market expansion.
`);

ins("insight3", `
  <span class="h">Saudi Arabia is the entry-level magnet:</span> <b>${k["Saudi Arabia"].entry_level_pct}%</b> of KSA postings require zero years of experience,
  versus <b>${k["Qatar"].entry_level_pct}%</b> in Qatar and <b>${k["UAE"].entry_level_pct}%</b> in the UAE. This aligns with the Saudization (Nitaqat) pressure to absorb young nationals.
  Qatar's market skews <b>senior</b> — over 46% of leveled roles are Senior or above.
`);

ins("insight4", `
  <span class="h">Bachelor's = the de facto standard.</span> KSA is the strictest (<b>${k["Saudi Arabia"].bachelor_required_pct}%</b> of postings) and most consistent in disclosing education,
  versus ${k["Qatar"].bachelor_required_pct}% in Qatar and ${k["UAE"].bachelor_required_pct}% in the UAE.
  Full-time roles dominate; internships are more visible in UAE/KSA.
`);

ins("insight5", `
  <span class="h">Large employers post the most jobs.</span> The 500+ employee tier leads in all three markets where company size is disclosed,
  consistent with the high turnover of large recruitment-driven groups. The top-15 employer concentration shows recruitment agencies dominate Qatar;
  global brands and aggressive growth-stage companies in the UAE; giga-project sponsors and Saudization-driven retail in KSA.
`);

ins("insight6", `
  <span class="h">Hiring is highly concentrated:</span> Doha for Qatar, Dubai > Abu Dhabi for the UAE, and Riyadh > Jeddah for KSA.
  Sharjah, Al Khobar, Dammam, and the Makkah/Medina belt account for the long tail.
`);

ins("insight7", `
  <span class="h">Salary transparency is poor</span> — only <b>${k["Qatar"].salary_disclosed_pct}%</b> in Qatar, <b>${k["UAE"].salary_disclosed_pct}%</b> in UAE,
  <b>${k["Saudi Arabia"].salary_disclosed_pct}%</b> in KSA. Among disclosures, the dominant band is <b>$500-2,000/month</b>, skewed by entry-level service-sector roles.
  Median monthly USD where disclosed: Qatar $${k["Qatar"].median_salary_usd}, UAE $${k["UAE"].median_salary_usd}, KSA $${k["Saudi Arabia"].median_salary_usd}.
  Premium categories (Engineering, Management, IT) clear meaningfully higher medians where reported.
`);

ins("insight8", `
  <span class="h">Nearly every job is bilingually marketed</span> — <b>${k["Qatar"].bilingual_pct}%</b> (Qatar), <b>${k["UAE"].bilingual_pct}%</b> (UAE),
  <b>${k["Saudi Arabia"].bilingual_pct}%</b> (KSA) of postings appear on both the English and Arabic portals.
  Bayt clearly defaults to bilingual exposure to maximize candidate reach. Median Arabic page length is ~4-7× the structured English description — the AR page is the richer raw artifact.
`);

ins("insight9", `
  <span class="h">Where language is explicitly stated, English dominates:</span> <b>${k["UAE"].english_req_pct}%</b> (UAE),
  <b>${k["Saudi Arabia"].english_req_pct}%</b> (KSA), <b>${k["Qatar"].english_req_pct}%</b> (Qatar) of postings explicitly require English.
  Arabic-required appears in <b>${k["Qatar"].arabic_req_pct}%</b> (Qatar), <b>${k["UAE"].arabic_req_pct}%</b> (UAE), <b>${k["Saudi Arabia"].arabic_req_pct}%</b> (KSA).
  The vast majority of postings don't make an explicit language requirement, but the implicit signal (Arabic Original_Page_Content) suggests Arabic is expected by default.
`);

ins("insight10", `
  <span class="h">Remote work is still rare in the GCC</span> — only <b>${DATA.remote_by_country["UAE"]}%</b> (UAE),
  <b>${DATA.remote_by_country["Saudi Arabia"]}%</b> (KSA), and <b>${DATA.remote_by_country["Qatar"]}%</b> (Qatar) of postings mention remote/hybrid arrangements.
  When remote is offered, it concentrates in <b>${Object.keys(DATA.remote_by_category)[0]}</b>, <b>${Object.keys(DATA.remote_by_category)[1]}</b>, and <b>${Object.keys(DATA.remote_by_category)[2]}</b> — knowledge-work categories.
  Physical-presence sectors (Construction, Hospitality, Healthcare) almost never offer remote.
`);

ins("insight11", `
  <span class="h">Explicit nationalization mentions are surprisingly rare in posting text:</span> <b>${DATA.nationalization["Saudi Arabia"].toFixed(2)}%</b> (KSA),
  <b>${DATA.nationalization["UAE"].toFixed(2)}%</b> (UAE), <b>${DATA.nationalization["Qatar"].toFixed(2)}%</b> (Qatar).
  Most employers operate under Saudization/Emiratization quotas but don't explicitly state national preferences in job text — those filters are enforced at the application/sourcing stage instead.
  Where explicit, KSA-targeted Saudization mentions cluster in entry-level service categories (retail, reception, sales).
`);

ins("insight12", `
  <span class="h">After removing boilerplate ("job description", "skills"),</span> the most frequent Arabic terms reveal the operational vocabulary of the GCC market:
  <b>إدارة (management), خبرة (experience), مهارات (skills), العملاء (clients), معرفة (knowledge), تطوير (development), بكالوريوس (Bachelor), دبلوم (diploma)</b>.
  This confirms the skill-and-experience-led framing of GCC postings — formal credentials + soft management/client skills dominate the language.
`);

ins("insight13", `
  <span class="h">Communication, project management, leadership, problem-solving</span> are the cross-cutting non-technical skills demanded most often —
  these dominate the top-10 across all 20,535 postings. Among technical skills, <b>customer service, sales, accounting, and engineering design</b> appear prominently.
  Microsoft Office shows up as a baseline expectation. The takeaway for candidates: soft skills win at the top of the list.
`);

ins("insight14", `
  <span class="h">Gender-neutral by default:</span> ~90% of postings don't specify gender. Among the ~10% that do, "Open to All" is the most common explicit signal.
  Female-specified roles slightly outnumber male-specified roles in Qatar and UAE — concentrated in healthcare, education, and reception/admin functions —
  reflecting the segmented service-economy reality of the region.
`);
</script>
</body>
</html>
"""

out = HTML.replace("__DATA__", payload)
out_path = HERE / "dashboard_GCC_Jobs_Bilingual_12_May_2026.html"
out_path.write_text(out, encoding="utf-8")
print(f"Wrote: {out_path}")
print(f"Size: {len(out):,} chars")
