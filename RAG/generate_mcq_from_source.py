"""
Source-derived MCQ Benchmark Generator
=======================================

Builds a multiple-choice benchmark directly from the original Bayt.com +
LinkedIn Excel files (Qatar / UAE / Saudi Arabia). Questions and distractors
are produced from real values in the source data — no dependence on the
previously generated open-ended benchmark.

Output: RAG_MCQ_Jobs_GCC_FromSource.xlsx
Columns: Question, Option_A, Option_B, Option_C, Option_D, Correct_Option,
         Correct_Answer, Category, Language, Reference, Filename

Question families (taxonomy = Category column):
  Lookup_CareerLevel / Lookup_EmploymentType / Lookup_Education / Lookup_Gender
  Lookup_JobCategory / Lookup_City / Lookup_Skill
  Lookup_Industry_LinkedIn / Lookup_Seniority_LinkedIn / Lookup_JobType_LinkedIn
  Lookup_Remote_LinkedIn / Lookup_Company_FromIndustry
  Pick_HighestSalary / Pick_MostExperience
  Pick_RoleInCategory / Pick_RoleRequiringEducation
  CrossFile_CountryWithMostInCategory / CrossFile_SourceWithMore
"""

import os
import re
import random
import pandas as pd

DATA_DIR = "/mnt/d/E/LLM/train/Jobs/bayt.com/FinalData"
OUT_MCQ  = "/mnt/d/E/LLM/train/Jobs/bayt.com/Benchmark/RAG_MCQ_Jobs_GCC_FromSource.xlsx"

BAYT_FILES = {
    "Qatar_EN_12May2026":  "bayt_jobs_Qatar_12_May_2026.xlsx",
    "Qatar_EN_07Jun2026":  "bayt_jobs_Qatar_07_Jun_2026.xlsx",
    "Qatar_AR_12May2026":  "bayt_jobs_Qatar_AR_12_May_2026.xlsx",
    "Saudi_EN_12May2026":  "bayt_jobs_Saudi_Arabia_12_May_2026.xlsx",
    "Saudi_EN_07Jun2026":  "bayt_jobs_Saudi_Arabia_07_Jun_2026.xlsx",
    "Saudi_AR_12May2026":  "bayt_jobs_Saudi_Arabia_AR_12_May_2026.xlsx",
    "UAE_EN_12May2026":    "bayt_jobs_UAE_12_May_2026.xlsx",
    "UAE_EN_07Jun2026":    "bayt_jobs_UAE_07_Jun_2026.xlsx",
    "UAE_AR_12May2026":    "bayt_jobs_UAE_AR_12_May_2026.xlsx",
}

LINKEDIN_FILES = {
    "Qatar_01Jun2026":   "linkedin_Qatar_jobs_20260601_2057.xlsx",
    "Qatar_07Jun2026":   "linkedin_Jobs_Qatar_7_June_2026.xlsx",
    "Saudi_01Jun2026":   "linkedin_Saudi_Arabia_jobs_20260601_1625.xlsx",
    "Saudi_07Jun2026":   "linkedin_Jobs_Saudi_Arabia_7_June_2026.xlsx",
    "UAE_01Jun2026":     "linkedin_UAE_jobs_20260601_1732.xlsx",
    "UAE_07Jun2026":     "linkedin_jobs_UAE_7_June_2026.xlsx",
}

KNOWN_CITIES = [
    "Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Al Ain", "Ras Al Khaimah", "Fujairah",
    "Riyadh", "Jeddah", "Dammam", "Mecca", "Medina", "Khobar", "Al Khobar",
    "Doha", "Al Wakrah", "Al Khor", "Ras Laffan", "Mesaieed", "Lusail",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clean_title(t):
    if pd.isna(t):
        return ""
    s = str(t)
    s = re.sub(r"\s*[-–—|]\s*Job ID[:#]?\s*\d+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\(?\s*Job ID[:#]?\s*\d+\)?", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[-–—|]\s*ID[:#]\s*\d+", "", s, flags=re.IGNORECASE)
    return s.strip().strip("-—–|").strip()


def clean_city(loc):
    if pd.isna(loc):
        return None
    s = str(loc).strip()
    for c in KNOWN_CITIES:
        if s == c or s.startswith(c + ","):
            return c
    # Bare country names mean "city not specified" — return None so callers
    # fall back to the country-level phrasing instead of saying "in Qatar"
    # for a Saudi job.
    if s.lower() in ("qatar", "saudi arabia", "uae", "united arab emirates"):
        return None
    return s.split(",")[0].strip()


def safe(v):
    if pd.isna(v):
        return None
    return str(v).strip()


def country_from_key(key):
    return "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")


# Country names in Arabic
COUNTRY_AR = {"Qatar": "قطر", "Saudi Arabia": "السعودية", "UAE": "الإمارات"}
CITY_AR = {
    "Doha": "الدوحة", "Dubai": "دبي", "Abu Dhabi": "أبوظبي", "Sharjah": "الشارقة",
    "Ajman": "عجمان", "Al Ain": "العين",
    "Riyadh": "الرياض", "Jeddah": "جدة", "Dammam": "الدمام",
    "Mecca": "مكة المكرمة", "Medina": "المدينة المنورة",
    "Al Wakrah": "الوكرة", "Al Khor": "الخور", "Ras Laffan": "رأس لفان",
    "Mesaieed": "مسيعيد", "Lusail": "لوسيل", "Khobar": "الخبر", "Al Khobar": "الخبر",
}


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("Loading Bayt files...")
bayt = {k: pd.read_excel(os.path.join(DATA_DIR, v)) for k, v in BAYT_FILES.items()}
print("Loading LinkedIn files...")
linkedin = {k: pd.read_excel(os.path.join(DATA_DIR, v)) for k, v in LINKEDIN_FILES.items()}

for k, df in bayt.items():
    print(f"  Bayt {k}: {len(df)} jobs")
for k, df in linkedin.items():
    print(f"  LinkedIn {k}: {len(df)} jobs")


# ---------------------------------------------------------------------------
# Build distractor pools from real source values
# ---------------------------------------------------------------------------
print("\nBuilding distractor pools from source files...")

def unique_values(dfs, col):
    s = set()
    for df in dfs:
        if col in df.columns:
            for v in df[col].dropna().unique():
                cv = str(v).strip()
                if cv and cv.lower() != 'nan':
                    s.add(cv)
    return sorted(s)


POOL_CAREER_LEVEL    = unique_values(bayt.values(), 'Career_Level')
POOL_EMPLOYMENT_TYPE = unique_values(bayt.values(), 'Employment_Type')
POOL_EDUCATION       = unique_values(bayt.values(), 'Education_Level')
POOL_GENDER          = unique_values(bayt.values(), 'Gender')
POOL_COMPANY_SIZE    = unique_values(bayt.values(), 'Company_Size')
POOL_JOB_CATEGORY    = unique_values(bayt.values(), 'Job_Category')

POOL_INDUSTRY_LI     = unique_values(linkedin.values(), 'company_industry')
POOL_JOB_LEVEL_LI    = unique_values(linkedin.values(), 'job_level')
POOL_JOB_TYPE_LI     = unique_values(linkedin.values(), 'job_type')

# Cities (cleaned) — pool per country plus global pool
POOL_CITY_BY_COUNTRY = {"Qatar": set(), "Saudi Arabia": set(), "UAE": set()}
for key, df in bayt.items():
    country = country_from_key(key)
    for loc in df['Job_Location'].dropna().unique():
        c = clean_city(loc)
        if c:
            POOL_CITY_BY_COUNTRY[country].add(c)
POOL_CITY_BY_COUNTRY = {k: sorted(v) for k, v in POOL_CITY_BY_COUNTRY.items()}
POOL_CITY_GLOBAL = sorted({c for cs in POOL_CITY_BY_COUNTRY.values() for c in cs})

# Companies on LinkedIn — used for "Which company operates in [industry]?"
ALL_LI_COMPANIES = set()
for df in linkedin.values():
    if 'company' in df.columns:
        ALL_LI_COMPANIES |= set(df['company'].dropna().unique())
ALL_LI_COMPANIES = sorted(ALL_LI_COMPANIES)


# ---------------------------------------------------------------------------
# MCQ row builder
# ---------------------------------------------------------------------------
mcq_rows = []


def add_mcq(question, correct, distractors, category, language, reference, filename, seed_str):
    if correct is None or pd.isna(correct):
        return False
    correct_s = str(correct).strip()
    if not correct_s:
        return False
    seen = {correct_s.lower()}
    unique_d = []
    for d in distractors:
        if d is None or pd.isna(d):
            continue
        ds = str(d).strip()
        if ds and ds.lower() not in seen:
            seen.add(ds.lower())
            unique_d.append(ds)
    if len(unique_d) < 3:
        return False
    opts = [correct_s] + unique_d[:3]
    rng = random.Random(hash(seed_str) & 0xFFFFFFFF)
    rng.shuffle(opts)
    letter = "ABCD"[opts.index(correct_s)]
    mcq_rows.append({
        "Question": question,
        "Option_A": opts[0],
        "Option_B": opts[1],
        "Option_C": opts[2],
        "Option_D": opts[3],
        "Correct_Option": letter,
        "Correct_Answer": correct_s,
        "Category": category,
        "Language": language,
        "Reference": reference,
        "Filename": filename,
    })
    return True


def diversify_sample(df, n, seed, by='Job_Category'):
    if by in df.columns:
        grp = df.dropna(subset=[by]).groupby(by)
        per = max(1, n // max(1, len(grp)))
        rows = [g.sample(min(len(g), per), random_state=seed) for _, g in grp]
        return pd.concat(rows).drop_duplicates(subset=['Job_ID'] if 'Job_ID' in df.columns else ['id']).head(n)
    return df.head(n)


def pick_distractors(pool, exclude, k=3, seed=0):
    """Pick k distractors from pool, excluding values that match `exclude`."""
    rng = random.Random(seed)
    candidates = [p for p in pool if str(p).strip().lower() != str(exclude).strip().lower()]
    if len(candidates) < k:
        return candidates
    return rng.sample(candidates, k)


# Pre-build word-bag of unique skills for skill distractors
ALL_SKILLS = set()
for df in bayt.values():
    for s in df['Job_Skills'].dropna():
        for tok in re.split(r"[;,/\n]", str(s)):
            t = tok.strip()
            if 2 < len(t) < 60:
                ALL_SKILLS.add(t)
ALL_SKILLS = sorted(ALL_SKILLS)


# ---------------------------------------------------------------------------
# Bayt: single-row attribute lookup MCQs
# ---------------------------------------------------------------------------
print("\nGenerating Bayt single-row lookup MCQs...")

seed_counter = 0
for key, fname in BAYT_FILES.items():
    df = bayt[key]
    country = country_from_key(key)
    country_ar = COUNTRY_AR[country]
    is_arabic = "_AR_" in key
    lang = "Arabic" if is_arabic else "English"
    sample = diversify_sample(df, 40, seed_counter)
    seed_counter += 1

    for _, row in sample.iterrows():
        jid = row.get('Job_ID', 'N/A')
        title = clean_title(row.get('Job_Title'))
        if not title:
            continue
        city = clean_city(row.get('Job_Location'))
        place_en = f"in {city}" if city else f"in {country}"
        place_ar = f"في {CITY_AR.get(city, city)}" if city else f"في {country_ar}"
        ref = f"{jid} - {title}"

        # Career_Level
        if pd.notna(row.get('Career_Level')):
            correct = safe(row['Career_Level'])
            ds = pick_distractors(POOL_CAREER_LEVEL, correct, 3, hash((jid, 'CL')))
            q = (f"ما المستوى الوظيفي المطلوب لوظيفة {title} {place_ar}؟"
                 if is_arabic else
                 f"What career level does the {title} role {place_en} require?")
            add_mcq(q, correct, ds, "Lookup_CareerLevel", lang, ref, fname, f"{jid}-CL")

        # Employment_Type
        if pd.notna(row.get('Employment_Type')):
            correct = safe(row['Employment_Type'])
            ds = pick_distractors(POOL_EMPLOYMENT_TYPE, correct, 3, hash((jid, 'ET')))
            q = (f"ما نوع التوظيف لوظيفة {title} {place_ar}؟"
                 if is_arabic else
                 f"What is the employment type for the {title} role {place_en}?")
            add_mcq(q, correct, ds, "Lookup_EmploymentType", lang, ref, fname, f"{jid}-ET")

        # Education_Level
        if pd.notna(row.get('Education_Level')):
            correct = safe(row['Education_Level'])
            ds = pick_distractors(POOL_EDUCATION, correct, 3, hash((jid, 'ED')))
            q = (f"ما الحد الأدنى من المؤهل العلمي المطلوب لوظيفة {title} {place_ar}؟"
                 if is_arabic else
                 f"What is the minimum education level required for the {title} role {place_en}?")
            add_mcq(q, correct, ds, "Lookup_Education", lang, ref, fname, f"{jid}-ED")

        # Gender
        if pd.notna(row.get('Gender')):
            correct = safe(row['Gender'])
            ds = pick_distractors(POOL_GENDER, correct, 3, hash((jid, 'GN')))
            q = (f"ما تفضيل الجنس لوظيفة {title} {place_ar}؟"
                 if is_arabic else
                 f"What gender preference does the {title} role {place_en} specify?")
            add_mcq(q, correct, ds, "Lookup_Gender", lang, ref, fname, f"{jid}-GN")

        # Job_Category
        if pd.notna(row.get('Job_Category')):
            correct = safe(row['Job_Category'])
            ds = pick_distractors(POOL_JOB_CATEGORY, correct, 3, hash((jid, 'JC')))
            q = (f"ضمن أي فئة وظيفية تصنف وظيفة {title} {place_ar}؟"
                 if is_arabic else
                 f"Under which job category is the {title} role {place_en} classified?")
            add_mcq(q, correct, ds, "Lookup_JobCategory", lang, ref, fname, f"{jid}-JC")

        # City
        if city:
            cities_pool = POOL_CITY_BY_COUNTRY.get(country, POOL_CITY_GLOBAL)
            if len(cities_pool) < 4:
                cities_pool = POOL_CITY_GLOBAL
            ds = pick_distractors(cities_pool, city, 3, hash((jid, 'CI')))
            city_ar = CITY_AR.get(city, city)
            q = (f"في أي مدينة تقع وظيفة {title}؟"
                 if is_arabic else
                 f"In which city is the {title} role located?")
            # Use Arabic city names when both correct and distractors have a translation
            if is_arabic and all(d in CITY_AR for d in ds + [city]):
                add_mcq(q, city_ar, [CITY_AR[d] for d in ds],
                        "Lookup_City", lang, ref, fname, f"{jid}-CI")
            else:
                add_mcq(q, city, ds, "Lookup_City", lang, ref, fname, f"{jid}-CI")

        # Company_Size
        if pd.notna(row.get('Company_Size')) and len(POOL_COMPANY_SIZE) >= 4:
            correct = safe(row['Company_Size'])
            ds = pick_distractors(POOL_COMPANY_SIZE, correct, 3, hash((jid, 'CS')))
            q = (f"ما حجم الشركة المعلنة عن وظيفة {title} {place_ar}؟"
                 if is_arabic else
                 f"What is the size of the company hiring for the {title} role {place_en}?")
            add_mcq(q, correct, ds, "Lookup_CompanySize", lang, ref, fname, f"{jid}-CS")

        # Skill required (single skill MC) — distractors from ALL_SKILLS pool excluding this job's skills
        skills_text = safe(row.get('Job_Skills'))
        if skills_text:
            job_skills = [t.strip() for t in re.split(r"[;,/\n]", skills_text) if 2 < len(t.strip()) < 60]
            if job_skills:
                rng = random.Random(hash((jid, 'SK')))
                correct_skill = rng.choice(job_skills)
                job_skill_set = {s.lower() for s in job_skills}
                non_matching = [s for s in ALL_SKILLS if s.lower() not in job_skill_set]
                if len(non_matching) >= 3:
                    ds = rng.sample(non_matching, 3)
                    q = (f"أي من المهارات التالية مطلوبة لوظيفة {title} {place_ar}؟"
                         if is_arabic else
                         f"Which of the following skills is required for the {title} role {place_en}?")
                    add_mcq(q, correct_skill, ds, "Lookup_Skill", lang, ref, fname, f"{jid}-SK")


# ---------------------------------------------------------------------------
# Bayt: multi-row "pick" MCQs
# ---------------------------------------------------------------------------
print("Generating Bayt multi-row pick MCQs...")


def parse_max_salary_usd(s):
    if pd.isna(s):
        return None
    nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", str(s))]
    return max(nums) if nums else None


def parse_max_experience(s):
    if pd.isna(s):
        return None
    nums = [int(x) for x in re.findall(r"\d+", str(s))]
    return max(nums) if nums else None


for key, fname in BAYT_FILES.items():
    df = bayt[key].copy()
    df['_max_sal'] = df['Salary_Range_USD'].apply(parse_max_salary_usd)
    df['_max_exp'] = df['Years_of_Experience'].apply(parse_max_experience)
    country = country_from_key(key)
    is_arabic = "_AR_" in key
    lang = "Arabic" if is_arabic else "English"

    # Pick_HighestSalary: 4 random salaried roles, correct = highest
    salaried = df.dropna(subset=['_max_sal'])
    if len(salaried) >= 8:
        rng = random.Random(hash((key, 'HS')))
        for trial in range(20):
            picks = salaried.sample(4, random_state=hash((key, 'HS', trial)) & 0xFFFFFFFF)
            titles = [clean_title(r['Job_Title']) for _, r in picks.iterrows()]
            if len(set(titles)) < 4 or any(not t for t in titles):
                continue
            # Disambiguate identical titles with city
            displayed = []
            for (_, r), t in zip(picks.iterrows(), titles):
                ct = clean_city(r['Job_Location'])
                displayed.append(f"{t} ({ct})" if ct else t)
            if len(set(displayed)) < 4:
                continue
            max_idx = picks['_max_sal'].idxmax()
            correct = displayed[list(picks.index).index(max_idx)]
            refs = "; ".join(f"{r['Job_ID']} - {clean_title(r['Job_Title'])}" for _, r in picks.iterrows())
            q = (f"من بين الوظائف التالية في {COUNTRY_AR[country]}، أيها يعرض أعلى راتب معلن؟"
                 if is_arabic else
                 f"Among the following roles in {country}, which advertises the highest salary?")
            add_mcq(q, correct, [d for d in displayed if d != correct],
                    "Pick_HighestSalary", lang, refs, fname, f"{key}-HS-{trial}")

    # Pick_MostExperience: 4 random with experience, correct = most
    with_exp = df.dropna(subset=['_max_exp'])
    if len(with_exp) >= 8:
        for trial in range(20):
            picks = with_exp.sample(4, random_state=hash((key, 'ME', trial)) & 0xFFFFFFFF)
            titles = [clean_title(r['Job_Title']) for _, r in picks.iterrows()]
            if len(set(titles)) < 4 or any(not t for t in titles):
                continue
            displayed = []
            for (_, r), t in zip(picks.iterrows(), titles):
                ct = clean_city(r['Job_Location'])
                displayed.append(f"{t} ({ct})" if ct else t)
            if len(set(displayed)) < 4:
                continue
            # Check distinct experience
            exp_values = list(picks['_max_exp'])
            if len(set(exp_values)) < 2:
                continue
            max_idx = picks['_max_exp'].idxmax()
            correct = displayed[list(picks.index).index(max_idx)]
            refs = "; ".join(f"{r['Job_ID']} - {clean_title(r['Job_Title'])}" for _, r in picks.iterrows())
            q = (f"من بين الوظائف التالية في {COUNTRY_AR[country]}، أيها يتطلب أكبر عدد من سنوات الخبرة؟"
                 if is_arabic else
                 f"Among the following roles in {country}, which requires the most years of experience?")
            add_mcq(q, correct, [d for d in displayed if d != correct],
                    "Pick_MostExperience", lang, refs, fname, f"{key}-ME-{trial}")

    # Pick_RoleInCategory: 1 role in target category + 3 in different categories
    cat_counts = df['Job_Category'].value_counts()
    top_categories = cat_counts[cat_counts >= 10].index.tolist()
    rng = random.Random(hash((key, 'CAT')))
    for cat in top_categories[:8]:
        in_cat = df[df['Job_Category'] == cat]
        out_cat = df[df['Job_Category'].notna() & (df['Job_Category'] != cat)]
        if len(in_cat) < 1 or len(out_cat) < 3:
            continue
        for trial in range(5):
            try:
                pick_in = in_cat.sample(1, random_state=hash((key, 'CAT', cat, trial)) & 0xFFFFFFFF).iloc[0]
                picks_out = out_cat.sample(3, random_state=hash((key, 'CAT', cat, trial, 'o')) & 0xFFFFFFFF)
            except ValueError:
                continue
            t_in = clean_title(pick_in['Job_Title'])
            t_outs = [clean_title(r['Job_Title']) for _, r in picks_out.iterrows()]
            if not t_in or any(not t for t in t_outs) or len(set([t_in] + t_outs)) < 4:
                continue
            refs = f"{pick_in['Job_ID']} - {t_in}; " + "; ".join(
                f"{r['Job_ID']} - {clean_title(r['Job_Title'])}" for _, r in picks_out.iterrows())
            q = (f"أي من المسميات الوظيفية التالية مصنفة ضمن فئة '{cat}' في {COUNTRY_AR[country]}؟"
                 if is_arabic else
                 f"Which of the following job titles is classified under the '{cat}' category in {country}?")
            add_mcq(q, t_in, t_outs, "Pick_RoleInCategory", lang, refs, fname, f"{key}-CAT-{cat}-{trial}")

    # Pick_RoleRequiringEducation: 1 role requiring [Master/PhD] + 3 with lower
    for target_edu, target_pattern, target_label in [
        ("Master", r"master", "Master's degree"),
        ("PhD",    r"phd|doctor", "PhD"),
    ]:
        ed_mask = df['Education_Level'].astype(str).str.lower().str.contains(target_pattern, regex=True, na=False)
        in_set = df[ed_mask]
        out_set = df[df['Education_Level'].notna() & ~ed_mask]
        if len(in_set) < 1 or len(out_set) < 3:
            continue
        for trial in range(5):
            try:
                pick_in = in_set.sample(1, random_state=hash((key, 'EDU', target_edu, trial)) & 0xFFFFFFFF).iloc[0]
                picks_out = out_set.sample(3, random_state=hash((key, 'EDU', target_edu, trial, 'o')) & 0xFFFFFFFF)
            except ValueError:
                continue
            t_in = clean_title(pick_in['Job_Title'])
            t_outs = [clean_title(r['Job_Title']) for _, r in picks_out.iterrows()]
            if not t_in or any(not t for t in t_outs) or len(set([t_in] + t_outs)) < 4:
                continue
            refs = f"{pick_in['Job_ID']} - {t_in}; " + "; ".join(
                f"{r['Job_ID']} - {clean_title(r['Job_Title'])}" for _, r in picks_out.iterrows())
            q = (f"أي من الوظائف التالية في {COUNTRY_AR[country]} تشترط الحصول على {target_label}؟"
                 if is_arabic else
                 f"Which of the following roles in {country} requires a {target_label}?")
            add_mcq(q, t_in, t_outs, "Pick_RoleRequiringEducation", lang, refs, fname,
                    f"{key}-EDU-{target_edu}-{trial}")


# ---------------------------------------------------------------------------
# LinkedIn: single-row attribute lookup MCQs
# ---------------------------------------------------------------------------
print("Generating LinkedIn single-row lookup MCQs...")

for key, fname in LINKEDIN_FILES.items():
    df = linkedin[key]
    country = country_from_key(key)

    if 'company_industry' in df.columns:
        sample = df.dropna(subset=['title', 'company', 'company_industry']).groupby('company_industry').head(2).head(40)
    else:
        sample = df.dropna(subset=['title', 'company']).head(30)

    for _, row in sample.iterrows():
        jid = row.get('id', 'N/A')
        title = clean_title(row.get('title'))
        if not title:
            continue
        company = safe(row.get('company')) or "the employer"
        loc = safe(row.get('location')) or country
        ref = f"{jid} - {title}"

        # Industry
        if pd.notna(row.get('company_industry')) and len(POOL_INDUSTRY_LI) >= 4:
            correct = safe(row['company_industry'])
            ds = pick_distractors(POOL_INDUSTRY_LI, correct, 3, hash((jid, 'IND')))
            q = f"In which industry does {company} operate (hiring for the {title} role in {loc})?"
            add_mcq(q, correct, ds, "Lookup_Industry_LinkedIn", "English", ref, fname, f"{jid}-IND")

        # Seniority (job_level)
        if pd.notna(row.get('job_level')) and len(POOL_JOB_LEVEL_LI) >= 4:
            correct = safe(row['job_level'])
            ds = pick_distractors(POOL_JOB_LEVEL_LI, correct, 3, hash((jid, 'SEN')))
            q = f"What seniority level does the {title} role at {company} in {loc} require?"
            add_mcq(q, correct, ds, "Lookup_Seniority_LinkedIn", "English", ref, fname, f"{jid}-SEN")

        # Job type
        if pd.notna(row.get('job_type')) and len(POOL_JOB_TYPE_LI) >= 4:
            correct = safe(row['job_type'])
            ds = pick_distractors(POOL_JOB_TYPE_LI, correct, 3, hash((jid, 'JT')))
            q = f"What employment arrangement is offered for the {title} role at {company}?"
            add_mcq(q, correct, ds, "Lookup_JobType_LinkedIn", "English", ref, fname, f"{jid}-JT")

        # Remote — Yes/No style with 4 plausible options
        if pd.notna(row.get('is_remote')):
            is_rem = bool(row['is_remote'])
            correct = "Yes, the listing is marked as remote." if is_rem else "No, the listing is not remote."
            distractors = (
                ["No, the listing is not remote.", "Hybrid arrangement (partial remote).", "Not specified in the listing."]
                if is_rem else
                ["Yes, the listing is marked as remote.", "Hybrid arrangement (partial remote).", "Not specified in the listing."]
            )
            q = f"Is the {title} role at {company} in {loc} a remote position?"
            add_mcq(q, correct, distractors, "Lookup_Remote_LinkedIn", "English", ref, fname, f"{jid}-REM")


# ---------------------------------------------------------------------------
# LinkedIn: pick-company-from-industry MCQs
# ---------------------------------------------------------------------------
print("Generating LinkedIn pick-company MCQs...")

for key, fname in LINKEDIN_FILES.items():
    df = linkedin[key]
    country = country_from_key(key)
    industries_present = df['company_industry'].value_counts()
    top_inds = industries_present[industries_present >= 5].index.tolist()[:12]
    for ind in top_inds:
        in_ind = df[df['company_industry'] == ind]['company'].dropna().unique()
        out_ind = df[df['company_industry'].notna() & (df['company_industry'] != ind)]['company'].dropna().unique()
        if len(in_ind) < 1 or len(out_ind) < 3:
            continue
        for trial in range(3):
            rng = random.Random(hash((key, ind, trial)) & 0xFFFFFFFF)
            correct = rng.choice(list(in_ind))
            others = [c for c in out_ind if c != correct]
            if len(others) < 3:
                continue
            distractors = rng.sample(others, 3)
            ref = f"Companies operating in {ind} (sample): {correct}; Other-industry companies sampled: " + ", ".join(distractors)
            q = f"Which of the following companies hiring in {country} operates in the '{ind}' industry?"
            add_mcq(q, correct, distractors, "Lookup_Company_FromIndustry",
                    "English", ref, fname, f"{key}-IND-{ind}-{trial}")


# ---------------------------------------------------------------------------
# Cross-file MCQs: country with most postings in a sector
# ---------------------------------------------------------------------------
print("Generating cross-file MCQs...")

for date_key, date_label in [("07Jun2026", "07 Jun 2026"), ("12May2026", "12 May 2026")]:
    qa_df = bayt.get(f"Qatar_EN_{date_key}")
    sa_df = bayt.get(f"Saudi_EN_{date_key}")
    ae_df = bayt.get(f"UAE_EN_{date_key}")
    if qa_df is None or sa_df is None or ae_df is None:
        continue
    files = [BAYT_FILES[f"Qatar_EN_{date_key}"], BAYT_FILES[f"Saudi_EN_{date_key}"], BAYT_FILES[f"UAE_EN_{date_key}"]]
    f_join = "; ".join(files)
    pool_country = ["Qatar", "Saudi Arabia", "UAE", "Roughly equal across all three"]

    for cat in ["Engineering", "IT", "Tech", "Sales", "Healthcare", "Construction",
                "Hospitality", "Education", "Finance", "Business Support"]:
        counts = {
            "Qatar":        int((qa_df['Job_Category'].astype(str) == cat).sum()),
            "Saudi Arabia": int((sa_df['Job_Category'].astype(str) == cat).sum()),
            "UAE":          int((ae_df['Job_Category'].astype(str) == cat).sum()),
        }
        if sum(counts.values()) < 30:
            continue
        winner = max(counts, key=counts.get)
        ds = pick_distractors(pool_country, winner, 3, hash(('CC', cat, date_key)))
        q = f"Which GCC country has the most {cat} postings on Bayt as of {date_label}?"
        ref = f"Counts — Qatar: {counts['Qatar']}; Saudi Arabia: {counts['Saudi Arabia']}; UAE: {counts['UAE']}"
        add_mcq(q, winner, ds, "CrossFile_CountryWithMostInCategory",
                "English", ref, f_join, f"CC-{cat}-{date_key}")

# Bayt vs LinkedIn source comparison
for country, bk, lk in [
    ("Qatar",        "Qatar_EN_07Jun2026", "Qatar_07Jun2026"),
    ("Saudi Arabia", "Saudi_EN_07Jun2026", "Saudi_07Jun2026"),
    ("UAE",          "UAE_EN_07Jun2026",   "UAE_07Jun2026"),
]:
    bdf = bayt[bk]
    ldf = linkedin[lk]
    pool = ["Bayt", "LinkedIn", "Both have roughly the same number", "Cannot be determined"]
    winner = "Bayt" if len(bdf) > len(ldf) else "LinkedIn"
    ds = pick_distractors(pool, winner, 3, hash(('SRC', country)))
    q = f"Which job board has more {country} listings as of 07 Jun 2026 — Bayt or LinkedIn?"
    ref = f"Bayt: {len(bdf)} postings; LinkedIn: {len(ldf)} postings"
    add_mcq(q, winner, ds, "CrossFile_SourceWithMore", "English", ref,
            f"{BAYT_FILES[bk]}; {LINKEDIN_FILES[lk]}", f"SRC-{country}")


# ---------------------------------------------------------------------------
# Dedupe & save
# ---------------------------------------------------------------------------
print(f"\nGenerated {len(mcq_rows)} raw MCQs. Deduplicating...")
mcq_df = pd.DataFrame(mcq_rows).drop_duplicates(subset=['Question', 'Filename']).reset_index(drop=True)
print(f"After dedupe: {len(mcq_df)} MCQs.")

mcq_df.to_excel(OUT_MCQ, index=False)
print(f"Saved MCQ benchmark to {OUT_MCQ}")

print("\nBreakdown by Category:")
print(mcq_df['Category'].value_counts())
print("\nBreakdown by Language:")
print(mcq_df['Language'].value_counts())
print("\nCorrect-option distribution:")
print(mcq_df['Correct_Option'].value_counts())
