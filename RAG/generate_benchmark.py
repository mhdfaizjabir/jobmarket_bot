"""
RAG Benchmark Generator for Bayt.com + LinkedIn Job Posts (Qatar, UAE, Saudi Arabia)

Produces an Excel benchmark of natural, persona-style user questions for evaluating a
RAG system over GCC job postings. Question text NEVER contains internal Job IDs —
those go into the Reference column only.

Coverage families:
  1. Fresh-graduate persona ("I'm a fresh grad with a bachelor's in X — what skills...")
  2. Experienced-professional persona ("I have 10 years experience as a Y — salary?")
  3. Career-level / entry-level / senior queries
  4. Demographic & nationality preferences (female-only, Saudi-only, Emirati-only)
  5. Work-style queries (remote, part-time, internships, contracts)
  6. Language queries (Arabic-required, English-required)
  7. Education-level queries (Bachelor / Master / PhD / High School)
  8. City-level relocation queries (Dubai / Riyadh / Doha / Jeddah / ...)
  9. Industry queries (LinkedIn industries)
 10. Market-overview / aggregation queries
 11. Salary / compensation queries
 12. Cross-country comparison (Qatar vs UAE vs Saudi Arabia)
 13. Time comparison (May 2026 vs June 2026)
 14. Source comparison (Bayt vs LinkedIn)
 15. Specific-job questions phrased through title + city + company (no Job ID)
 16. Arabic-language versions of all of the above (for AR-extracted files)

Each row has: Question, Answer, Reference (Job IDs + titles), Filename (single or
semicolon-separated list for cross-file questions).
"""

import os
import re
import pandas as pd

DATA_DIR = "/mnt/d/E/LLM/train/Jobs/bayt.com/FinalData"
OUT_PATH = "/mnt/d/E/LLM/train/Jobs/bayt.com/Benchmark/RAG_Benchmark_Jobs_GCC.xlsx"

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

COUNTRY_FROM_KEY = {"Qatar": "Qatar", "Saudi": "Saudi Arabia", "UAE": "UAE"}
COUNTRY_AR       = {"Qatar": "قطر",   "Saudi": "السعودية",       "UAE": "الإمارات"}

KNOWN_CITIES = [
    "Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Al Ain", "Ras Al Khaimah", "Fujairah",
    "Riyadh", "Jeddah", "Dammam", "Mecca", "Medina", "Khobar", "Al Khobar",
    "Doha", "Al Wakrah", "Al Khor", "Ras Laffan", "Mesaieed", "Lusail",
]


def clean_title(t):
    """Strip embedded 'Job ID: 12345' patterns recruiters sometimes paste into titles."""
    if pd.isna(t):
        return ""
    s = str(t)
    s = re.sub(r"\s*[-–—|]\s*Job ID[:#]?\s*\d+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\(?\s*Job ID[:#]?\s*\d+\)?", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[-–—|]\s*ID[:#]\s*\d+", "", s, flags=re.IGNORECASE)
    return s.strip().strip("-—–|").strip()


def clean_city(loc):
    """Bayt locations have a data bug where every city is suffixed with ', Qatar'.
    Strip it so user-facing questions look natural."""
    if pd.isna(loc):
        return None
    s = str(loc).strip()
    for c in KNOWN_CITIES:
        if s == c or s.startswith(c + ","):
            return c
    # Fall back: take the part before the first comma
    return s.split(",")[0].strip()


qa_rows = []


def add(question, answer, reference, filename):
    qa_rows.append({
        "Question": question,
        "Answer": str(answer),
        "Reference": reference,
        "Filename": filename,
    })


def fmt_ref_list(rows, id_col, title_col, limit=5):
    refs = []
    for _, r in rows.head(limit).iterrows():
        refs.append(f"{r[id_col]} - {r[title_col]}")
    return "; ".join(refs)


def safe(v):
    if pd.isna(v):
        return "Not specified"
    return str(v).strip()


# ---------------------------------------------------------------------------
# Load all data
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
# Profession / specialization catalog used across persona questions
#   (label_en, label_ar, regex matching Job_Title)
# ---------------------------------------------------------------------------
PROFESSIONS = [
    ("programming / software engineering", "البرمجة / هندسة البرمجيات",
     r"software|programmer|developer|full[- ]stack|backend|frontend|.net|java\b|python|node|web developer"),
    ("data science / machine learning",    "علم البيانات / تعلم الآلة",
     r"data scien|data analyst|machine learning|ml engineer|ai engineer|deep learning"),
    ("accounting",                          "المحاسبة",
     r"account(?:ant|ing)|bookkeep|auditor|audit\b"),
    ("finance",                             "التمويل والمالية",
     r"financ|treasur|investment|portfolio|banking"),
    ("marketing",                           "التسويق",
     r"marketing|brand|seo|content writer|copywriter|digital marketing"),
    ("sales",                               "المبيعات",
     r"sales|business development|account executive|key account"),
    ("nursing",                             "التمريض",
     r"\bnurs(?:e|ing)|registered nurse|rn\b|midwife"),
    ("medicine / physician",                "الطب",
     r"physician|doctor|surgeon|consultant.*medic|pediatric|dentist|pharmac"),
    ("teaching",                            "التدريس",
     r"teacher|teaching|instructor|tutor|professor|lecturer"),
    ("Arabic teaching",                     "تدريس اللغة العربية",
     r"arabic.*teach|teacher.*arabic|arabic.*instructor|arabic.*lecturer|arabic.*tutor"),
    ("civil engineering",                   "الهندسة المدنية",
     r"civil engineer|structural engineer|site engineer|construction engineer"),
    ("mechanical engineering",              "الهندسة الميكانيكية",
     r"mechanical engineer|hvac engineer"),
    ("electrical engineering",              "الهندسة الكهربائية",
     r"electrical engineer|power engineer"),
    ("architecture",                        "العمارة",
     r"\barchitect\b|architecture|landscape architect"),
    ("project management",                  "إدارة المشاريع",
     r"project manager|programme manager|program manager|pmo"),
    ("HR / human resources",                "الموارد البشرية",
     r"human resources|hr manager|hr officer|hr business partner|talent acquisition|recruit"),
    ("driving",                             "القيادة",
     r"\bdriver\b|chauffeur"),
    ("hospitality / chef",                  "الضيافة والطهي",
     r"\bchef\b|cook|waiter|waitress|barista|hotel|hospitality|f&b"),
    ("cybersecurity",                       "الأمن السيبراني",
     r"cyber security|cybersecurity|information security|infosec|soc analyst|penetration tester"),
    ("DevOps / cloud",                      "ديف أوبس / الحوسبة السحابية",
     r"devops|sre\b|cloud engineer|aws|azure engineer|kubernetes|sysadmin"),
    ("customer service",                    "خدمة العملاء",
     r"customer service|customer support|call center|contact center"),
    ("administration / secretarial",        "الإدارة والسكرتارية",
     r"secretary|receptionist|admin assistant|office manager|personal assistant|executive assistant"),
    ("logistics / supply chain",            "اللوجستيات وسلسلة التوريد",
     r"logistic|supply chain|warehouse|procurement|forklift"),
    ("retail",                              "البيع بالتجزئة",
     r"cashier|retail|store manager|merchand"),
    ("graphic design",                      "التصميم الجرافيكي",
     r"graphic design|ux designer|ui designer|product designer|motion graphic"),
]


# ---------------------------------------------------------------------------
# 1) FRESH-GRADUATE PERSONA QUESTIONS  (single Bayt file)
#    Pattern: "I'm a fresh grad with a bachelor's in X — what skills are needed in Y?"
# ---------------------------------------------------------------------------
print("\nGenerating fresh-graduate persona questions...")


def top_skills_from_postings(postings, k=10):
    bag = []
    for s in postings['Job_Skills'].dropna():
        for token in re.split(r"[;,/\n]", str(s)):
            t = token.strip()
            if t and len(t) < 80:
                bag.append(t)
    if not bag:
        return []
    counts = pd.Series(bag).value_counts().head(k)
    return list(counts.items())


for key, fname in BAYT_FILES.items():
    df = bayt[key]
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    country_key = "Qatar" if "Qatar" in key else ("Saudi" if "Saudi" in key else "UAE")
    country_ar = COUNTRY_AR[country_key]
    is_arabic = "_AR_" in key
    date_label = "12 May 2026" if "12May" in key else "07 Jun 2026"

    for (prof_en, prof_ar, pattern) in PROFESSIONS:
        title_match = df['Job_Title'].astype(str).str.contains(pattern, case=False, na=False, regex=True)
        match = df[title_match]
        if match.empty:
            continue

        # Entry-level subset for fresh-grad question
        entry = match
        if 'Career_Level' in df.columns:
            entry_filter = match['Career_Level'].astype(str).str.lower().str.contains('entry|junior|fresh', na=False, regex=True)
            if entry_filter.any():
                entry = match[entry_filter]
        target = entry if len(entry) >= 3 else match

        skills = top_skills_from_postings(target)
        skill_text = "; ".join([f"{s} ({c} mentions)" for s, c in skills[:8]]) if skills else "Skills not consistently listed"

        if is_arabic:
            q = f"أنا خريج جديد بدرجة بكالوريوس في {prof_ar}، ما المهارات المطلوبة للعمل في {country_ar}؟"
            a = f"بناءً على {len(target)} إعلان وظيفة ذات صلة، أبرز المهارات المطلوبة: {skill_text}."
        else:
            q = f"I'm a fresh graduate with a bachelor's degree in {prof_en}. What skills do I need to be hired in {country}?"
            a = f"Based on {len(target)} matching postings, the most frequently required skills are: {skill_text}."

        add(q, a, fmt_ref_list(target, 'Job_ID', 'Job_Title', 5), fname)

        # Availability variant
        if is_arabic:
            q2 = f"أنا خريج {prof_ar}، هل توجد وظائف تطلب هذا التخصص تحديداً في {country_ar}؟"
            a2 = f"نعم، يوجد {len(match)} إعلان وظيفة يتطابق مع تخصص {prof_ar} في {country_ar}. عينة: " + fmt_ref_list(match, 'Job_ID', 'Job_Title', 5)
        else:
            q2 = f"I'm a {prof_en} graduate. Are there jobs that specifically require this specialization in {country}?"
            a2 = f"Yes — there are {len(match)} postings matching {prof_en} in {country}. Sample roles: " + fmt_ref_list(match, 'Job_ID', 'Job_Title', 5)

        add(q2, a2, fmt_ref_list(match, 'Job_ID', 'Job_Title', 5), fname)


# ---------------------------------------------------------------------------
# 2) EXPERIENCED-PROFESSIONAL PERSONA — salary & seniority by years of experience
# ---------------------------------------------------------------------------
print("Generating experienced-professional persona questions...")


def parse_max_experience(s):
    if pd.isna(s):
        return None
    nums = [int(x) for x in re.findall(r"\d+", str(s))]
    return max(nums) if nums else None


def parse_max_salary_usd(s):
    if pd.isna(s):
        return None
    nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", str(s))]
    return max(nums) if nums else None


for key, fname in BAYT_FILES.items():
    df = bayt[key].copy()
    df['_max_exp'] = df['Years_of_Experience'].apply(parse_max_experience)
    df['_max_sal'] = df['Salary_Range_USD'].apply(parse_max_salary_usd)
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    country_key = "Qatar" if "Qatar" in key else ("Saudi" if "Saudi" in key else "UAE")
    country_ar = COUNTRY_AR[country_key]
    is_arabic = "_AR_" in key

    for (prof_en, prof_ar, pattern) in PROFESSIONS:
        title_match = df['Job_Title'].astype(str).str.contains(pattern, case=False, na=False, regex=True)
        match = df[title_match]
        if match.empty:
            continue
        with_sal = match.dropna(subset=['Salary_Range_USD'])
        with_exp = match.dropna(subset=['_max_exp'])

        for years in (3, 5, 10, 15):
            band = with_exp[(with_exp['_max_exp'] >= max(1, years - 2)) & (with_exp['_max_exp'] <= years + 2)]
            if band.empty:
                continue
            band_sal = band.dropna(subset=['Salary_Range_USD'])
            if is_arabic:
                q = f"ما النطاق الراتبي لوظيفة {prof_ar} في {country_ar} لشخص لديه {years} سنوات خبرة؟"
                if not band_sal.empty:
                    sal_values = "; ".join(band_sal['Salary_Range_USD'].astype(str).head(5).tolist())
                    a = f"وجدنا {len(band)} إعلانًا يطابق ({years} سنوات خبرة تقريباً)، منها {len(band_sal)} يعلن الراتب. نطاقات الرواتب المعلنة: {sal_values}."
                else:
                    a = f"وجدنا {len(band)} إعلانًا يطابق، لكن أيًا منها لا يفصح عن الراتب صراحة. الرجاء مراجعة الإعلانات الأصلية."
            else:
                q = f"What is the salary range for a {prof_en} role in {country} with about {years} years of experience?"
                if not band_sal.empty:
                    sal_values = "; ".join(band_sal['Salary_Range_USD'].astype(str).head(5).tolist())
                    a = f"Found {len(band)} matching postings near {years} years of experience, of which {len(band_sal)} disclose salary. Disclosed USD ranges: {sal_values}."
                else:
                    a = f"Found {len(band)} matching postings near {years} years of experience, but none disclose salary publicly. Please refer to the listings directly."
            add(q, a, fmt_ref_list(band, 'Job_ID', 'Job_Title', 5), fname)

        # Generic "what's available for someone with N years"
        for years in (5, 10, 15):
            band = with_exp[(with_exp['_max_exp'] >= max(1, years - 2)) & (with_exp['_max_exp'] <= years + 2)]
            if band.empty:
                continue
            if is_arabic:
                q = f"لدي {years} سنوات خبرة في {prof_ar}، ما الوظائف المتاحة في {country_ar}؟"
                a = f"يوجد {len(band)} إعلان وظيفة في {country_ar} يناسب من لديه {years} سنوات خبرة في {prof_ar}. أمثلة: " + fmt_ref_list(band, 'Job_ID', 'Job_Title', 5)
            else:
                q = f"I have {years} years of experience in {prof_en}. What jobs are available in {country}?"
                a = f"There are {len(band)} postings in {country} matching {years} years of experience in {prof_en}. Sample roles: " + fmt_ref_list(band, 'Job_ID', 'Job_Title', 5)
            add(q, a, fmt_ref_list(band, 'Job_ID', 'Job_Title', 5), fname)


# ---------------------------------------------------------------------------
# 3) CAREER-LEVEL QUERIES — entry / mid / senior / manager / director
# ---------------------------------------------------------------------------
print("Generating career-level questions...")

for key, fname in BAYT_FILES.items():
    df = bayt[key]
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    country_key = "Qatar" if "Qatar" in key else ("Saudi" if "Saudi" in key else "UAE")
    country_ar = COUNTRY_AR[country_key]
    is_arabic = "_AR_" in key

    for level_en, level_ar, pattern in [
        ("entry-level",  "المبتدئة",   "entry"),
        ("mid-level",    "المتوسطة",   "mid"),
        ("senior-level", "العليا",     "senior"),
        ("management",   "الإدارية",   "manager"),
        ("executive",    "التنفيذية",  "executive|director"),
    ]:
        m = df[df['Career_Level'].astype(str).str.lower().str.contains(pattern, regex=True, na=False)]
        if m.empty:
            continue
        if is_arabic:
            q = f"ما عدد الوظائف {level_ar} المتاحة حالياً في {country_ar}؟"
            a = f"يوجد {len(m)} إعلان وظيفة {level_ar} في {country_ar}. عينة: " + fmt_ref_list(m, 'Job_ID', 'Job_Title', 5)
        else:
            q = f"How many {level_en} jobs are currently available in {country}?"
            a = f"There are {len(m)} {level_en} postings in {country}. Sample roles: " + fmt_ref_list(m, 'Job_ID', 'Job_Title', 5)
        add(q, a, fmt_ref_list(m, 'Job_ID', 'Job_Title', 5), fname)


# ---------------------------------------------------------------------------
# 4) DEMOGRAPHIC & NATIONALITY QUERIES
# ---------------------------------------------------------------------------
print("Generating demographic / nationality questions...")

for key, fname in BAYT_FILES.items():
    df = bayt[key]
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    country_key = "Qatar" if "Qatar" in key else ("Saudi" if "Saudi" in key else "UAE")
    country_ar = COUNTRY_AR[country_key]
    is_arabic = "_AR_" in key

    # Female-only
    female = df[df['Gender'].astype(str).str.lower() == 'female']
    if not female.empty:
        if is_arabic:
            q = f"أنا امرأة وأبحث عن عمل في {country_ar}. ما الوظائف التي تستهدف الإناث تحديداً؟"
            a = f"يوجد {len(female)} إعلان وظيفة في {country_ar} يستهدف الإناث صراحة. عينة: " + fmt_ref_list(female, 'Job_ID', 'Job_Title', 5)
        else:
            q = f"I'm a woman looking for work in {country}. Which jobs specifically target female candidates?"
            a = f"There are {len(female)} postings in {country} explicitly targeting female candidates. Sample roles: " + fmt_ref_list(female, 'Job_ID', 'Job_Title', 5)
        add(q, a, fmt_ref_list(female, 'Job_ID', 'Job_Title', 5), fname)

    # Male-targeted
    male = df[df['Gender'].astype(str).str.lower() == 'male']
    if not male.empty:
        if is_arabic:
            q = f"ما الوظائف التي تستهدف الذكور تحديداً في {country_ar}؟"
            a = f"يوجد {len(male)} إعلان وظيفة في {country_ar} يستهدف الذكور صراحة. عينة: " + fmt_ref_list(male, 'Job_ID', 'Job_Title', 5)
        else:
            q = f"Which postings in {country} specifically target male candidates?"
            a = f"There are {len(male)} postings in {country} explicitly targeting male candidates. Sample roles: " + fmt_ref_list(male, 'Job_ID', 'Job_Title', 5)
        add(q, a, fmt_ref_list(male, 'Job_ID', 'Job_Title', 5), fname)

    # Saudi nationals
    if country == "Saudi Arabia":
        nat = df[df['Gender'].astype(str).str.lower().str.contains('saudi', na=False)]
        if not nat.empty:
            if is_arabic:
                q = "أنا مواطن سعودي، هل توجد وظائف تفضل السعوديين؟"
                a = f"نعم، يوجد {len(nat)} إعلان وظيفة يفضل أو يقتصر على المواطنين السعوديين. عينة: " + fmt_ref_list(nat, 'Job_ID', 'Job_Title', 5)
            else:
                q = "I'm a Saudi national. Are there jobs in Saudi Arabia that prefer Saudi citizens?"
                a = f"Yes — there are {len(nat)} postings that prefer or restrict to Saudi nationals. Sample roles: " + fmt_ref_list(nat, 'Job_ID', 'Job_Title', 5)
            add(q, a, fmt_ref_list(nat, 'Job_ID', 'Job_Title', 5), fname)

    # UAE / Emirati nationals
    if country == "UAE":
        nat = df[df['Gender'].astype(str).str.lower().str.contains('uae national|emirati', regex=True, na=False)]
        if not nat.empty:
            if is_arabic:
                q = "أنا إماراتي، هل توجد وظائف تفضل المواطنين الإماراتيين؟"
                a = f"نعم، يوجد {len(nat)} إعلان وظيفة يستهدف المواطنين الإماراتيين. عينة: " + fmt_ref_list(nat, 'Job_ID', 'Job_Title', 5)
            else:
                q = "I'm an Emirati national. Are there jobs in the UAE that prefer Emirati citizens?"
                a = f"Yes — there are {len(nat)} postings that target UAE/Emirati nationals. Sample roles: " + fmt_ref_list(nat, 'Job_ID', 'Job_Title', 5)
            add(q, a, fmt_ref_list(nat, 'Job_ID', 'Job_Title', 5), fname)


# ---------------------------------------------------------------------------
# 5) WORK-STYLE QUERIES — remote / part-time / contract / internship / freelance
# ---------------------------------------------------------------------------
print("Generating work-style questions...")

for key, fname in BAYT_FILES.items():
    df = bayt[key]
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    country_key = "Qatar" if "Qatar" in key else ("Saudi" if "Saudi" in key else "UAE")
    country_ar = COUNTRY_AR[country_key]
    is_arabic = "_AR_" in key

    work_styles = [
        ("remote",     "عن بُعد",      "Remote"),
        ("part-time",  "بدوام جزئي",   "Part-Time"),
        ("internship", "تدريب",        "Intern"),
        ("contract",   "بعقد مؤقت",    "Contract"),
        ("freelance",  "عمل حر",       "Freelance"),
    ]
    for en, ar, etype in work_styles:
        m = df[df['Employment_Type'].astype(str).str.contains(etype, case=False, na=False)]
        if m.empty:
            continue
        if is_arabic:
            q = f"أبحث عن وظيفة {ar} في {country_ar}. ما المتاح؟"
            a = f"يوجد {len(m)} إعلان وظيفة {ar} في {country_ar}. عينة: " + fmt_ref_list(m, 'Job_ID', 'Job_Title', 5)
        else:
            q = f"I'm looking for {en} work in {country}. What's available?"
            a = f"There are {len(m)} {en} postings in {country}. Sample roles: " + fmt_ref_list(m, 'Job_ID', 'Job_Title', 5)
        add(q, a, fmt_ref_list(m, 'Job_ID', 'Job_Title', 5), fname)


# ---------------------------------------------------------------------------
# 6) LANGUAGE QUERIES
# ---------------------------------------------------------------------------
print("Generating language questions...")

for key, fname in BAYT_FILES.items():
    df = bayt[key]
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    country_key = "Qatar" if "Qatar" in key else ("Saudi" if "Saudi" in key else "UAE")
    country_ar = COUNTRY_AR[country_key]
    is_arabic = "_AR_" in key

    ar_jobs = df[df['Language_Requirement'].astype(str).str.lower().str.contains('arab', na=False)]
    if not ar_jobs.empty:
        if is_arabic:
            q = f"أتحدث العربية فقط ولا أجيد الإنجليزية. ما الوظائف المتاحة في {country_ar}؟"
            a = f"يوجد {len(ar_jobs)} إعلان وظيفة في {country_ar} يشترط أو يفضل اللغة العربية. عينة: " + fmt_ref_list(ar_jobs, 'Job_ID', 'Job_Title', 5)
        else:
            q = f"Which jobs in {country} require Arabic language skills?"
            a = f"There are {len(ar_jobs)} postings in {country} that require or prefer Arabic. Sample roles: " + fmt_ref_list(ar_jobs, 'Job_ID', 'Job_Title', 5)
        add(q, a, fmt_ref_list(ar_jobs, 'Job_ID', 'Job_Title', 5), fname)

    bilingual = df[df['Language_Requirement'].astype(str).str.lower().str.contains('arabic.*english|english.*arabic|bilingual', regex=True, na=False)]
    if not bilingual.empty:
        if is_arabic:
            q = f"ما الوظائف التي تشترط إجادة العربية والإنجليزية معاً في {country_ar}؟"
            a = f"يوجد {len(bilingual)} إعلان وظيفة ثنائي اللغة (عربي/إنجليزي) في {country_ar}. عينة: " + fmt_ref_list(bilingual, 'Job_ID', 'Job_Title', 5)
        else:
            q = f"Which jobs in {country} require fluency in both Arabic and English?"
            a = f"There are {len(bilingual)} bilingual postings (Arabic + English) in {country}. Sample roles: " + fmt_ref_list(bilingual, 'Job_ID', 'Job_Title', 5)
        add(q, a, fmt_ref_list(bilingual, 'Job_ID', 'Job_Title', 5), fname)


# ---------------------------------------------------------------------------
# 7) EDUCATION-LEVEL QUERIES
# ---------------------------------------------------------------------------
print("Generating education-level questions...")

for key, fname in BAYT_FILES.items():
    df = bayt[key]
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    country_key = "Qatar" if "Qatar" in key else ("Saudi" if "Saudi" in key else "UAE")
    country_ar = COUNTRY_AR[country_key]
    is_arabic = "_AR_" in key

    for en, ar, pattern in [
        ("Master's degree", "درجة الماجستير", "master"),
        ("PhD / doctorate", "درجة الدكتوراه", "phd|doctor"),
        ("high school certificate", "الشهادة الثانوية", "high school"),
        ("diploma", "الدبلوم", "diploma"),
        ("bachelor's degree", "درجة البكالوريوس", "bachelor"),
    ]:
        m = df[df['Education_Level'].astype(str).str.lower().str.contains(pattern, regex=True, na=False)]
        if m.empty or len(m) < 3:
            continue
        if is_arabic:
            q = f"ما الوظائف التي تشترط {ar} في {country_ar}؟"
            a = f"يوجد {len(m)} إعلان وظيفة في {country_ar} يشترط {ar}. عينة: " + fmt_ref_list(m, 'Job_ID', 'Job_Title', 5)
        else:
            q = f"What jobs in {country} require a {en}?"
            a = f"There are {len(m)} postings in {country} requiring a {en}. Sample roles: " + fmt_ref_list(m, 'Job_ID', 'Job_Title', 5)
        add(q, a, fmt_ref_list(m, 'Job_ID', 'Job_Title', 5), fname)


# ---------------------------------------------------------------------------
# 8) CITY-LEVEL RELOCATION QUERIES
# ---------------------------------------------------------------------------
print("Generating city-level relocation questions...")

CITY_AR = {
    "Doha": "الدوحة", "Dubai": "دبي", "Abu Dhabi": "أبوظبي", "Sharjah": "الشارقة",
    "Ajman": "عجمان", "Al Ain": "العين",
    "Riyadh": "الرياض", "Jeddah": "جدة", "Dammam": "الدمام",
    "Mecca": "مكة المكرمة", "Medina": "المدينة المنورة",
}

CITY_FILTERS = {
    "Qatar_EN_12May2026": ["Doha"],
    "Qatar_EN_07Jun2026": ["Doha"],
    "Qatar_AR_12May2026": ["Doha"],
    "Saudi_EN_12May2026": ["Riyadh", "Jeddah", "Dammam", "Mecca", "Medina"],
    "Saudi_EN_07Jun2026": ["Riyadh", "Jeddah", "Dammam", "Mecca", "Medina"],
    "Saudi_AR_12May2026": ["Riyadh", "Jeddah", "Dammam", "Mecca", "Medina"],
    "UAE_EN_12May2026":   ["Dubai", "Abu Dhabi", "Sharjah", "Ajman"],
    "UAE_EN_07Jun2026":   ["Dubai", "Abu Dhabi", "Sharjah", "Ajman"],
    "UAE_AR_12May2026":   ["Dubai", "Abu Dhabi", "Sharjah", "Ajman"],
}

for key, cities in CITY_FILTERS.items():
    df = bayt[key]
    fname = BAYT_FILES[key]
    is_arabic = "_AR_" in key
    for city in cities:
        m = df[df['Job_Location'].astype(str).str.contains(city, case=False, na=False)]
        if m.empty:
            continue
        cats = m['Job_Category'].value_counts().head(3)
        city_ar = CITY_AR.get(city, city)
        if is_arabic:
            q = f"سأنتقل إلى {city_ar} وأبحث عن عمل. ما القطاعات الأكثر طلباً هناك؟"
            a = f"يوجد {len(m)} إعلان وظيفة في {city_ar}. أكبر 3 قطاعات: " + "؛ ".join([f"{n}: {c}" for n, c in cats.items()])
        else:
            q = f"I'm relocating to {city}. Which sectors are hiring the most there?"
            a = f"There are {len(m)} postings in {city}. Top 3 sectors: " + "; ".join([f"{n}: {c}" for n, c in cats.items()])
        add(q, a, fmt_ref_list(m, 'Job_ID', 'Job_Title', 5), fname)

        # Top roles in this city
        titles = m['Job_Title'].value_counts().head(5)
        if not titles.empty:
            if is_arabic:
                q2 = f"ما أكثر المسميات الوظيفية إعلاناً في {city_ar}؟"
                a2 = "; ".join([f"{n} ({c})" for n, c in titles.items()])
            else:
                q2 = f"What are the most frequently posted job titles in {city}?"
                a2 = "; ".join([f"{n} ({c})" for n, c in titles.items()])
            add(q2, a2, fmt_ref_list(m, 'Job_ID', 'Job_Title', 5), fname)


# ---------------------------------------------------------------------------
# 9) INDUSTRY QUERIES (LinkedIn)
# ---------------------------------------------------------------------------
print("Generating industry questions (LinkedIn)...")

INDUSTRY_QUESTIONS = [
    ("IT Services and IT Consulting",        "خدمات تقنية المعلومات والاستشارات"),
    ("Hospitality",                          "الضيافة"),
    ("Hospitals and Health Care",            "المستشفيات والرعاية الصحية"),
    ("Construction",                         "البناء والتشييد"),
    ("Oil and Gas",                          "النفط والغاز"),
    ("Financial Services",                   "الخدمات المالية"),
    ("Software Development",                 "تطوير البرمجيات"),
    ("Retail",                               "التجزئة"),
    ("Real Estate",                          "العقارات"),
    ("Airlines and Aviation",                "الطيران"),
    ("Defense and Space Manufacturing",      "صناعة الدفاع والفضاء"),
]

for key, fname in LINKEDIN_FILES.items():
    df = linkedin[key]
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    for en, ar in INDUSTRY_QUESTIONS:
        m = df[df['company_industry'].astype(str).str.contains(en, case=False, na=False)]
        if m.empty:
            continue
        add(
            f"I work in {en}. How active is the job market in {country} on LinkedIn?",
            f"There are {len(m)} {en} postings on LinkedIn for {country}. Sample roles: " + fmt_ref_list(m, 'id', 'title', 5),
            fmt_ref_list(m, 'id', 'title', 5),
            fname,
        )

    # Top industries
    top_ind = df['company_industry'].value_counts().head(5)
    if not top_ind.empty:
        add(
            f"Which industries are hiring the most in {country} on LinkedIn?",
            "; ".join([f"{n}: {c}" for n, c in top_ind.items()]),
            "Aggregated counts by company_industry",
            fname,
        )

    # Top companies
    top_comp = df['company'].value_counts().head(5)
    if not top_comp.empty:
        add(
            f"Which companies are posting the most jobs in {country} on LinkedIn right now?",
            "; ".join([f"{n}: {c}" for n, c in top_comp.items()]),
            "Aggregated counts by company",
            fname,
        )


# ---------------------------------------------------------------------------
# 10) MARKET-OVERVIEW & AGGREGATION QUERIES (Bayt)
# ---------------------------------------------------------------------------
print("Generating market-overview questions...")

for key, fname in BAYT_FILES.items():
    df = bayt[key]
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    country_key = "Qatar" if "Qatar" in key else ("Saudi" if "Saudi" in key else "UAE")
    country_ar = COUNTRY_AR[country_key]
    is_arabic = "_AR_" in key
    date_label = "12 May 2026" if "12May" in key else "07 Jun 2026"
    date_ar = "12 مايو 2026" if "12May" in key else "7 يونيو 2026"

    if is_arabic:
        q = f"كم عدد الوظائف المنشورة في {country_ar} في {date_ar}؟"
        a = f"يوجد إجمالاً {len(df)} إعلان وظيفة في {country_ar} على موقع Bayt.com بتاريخ {date_ar}."
    else:
        q = f"How many jobs are currently posted in {country} on Bayt as of {date_label}?"
        a = f"There are a total of {len(df)} job postings in {country} on Bayt.com as of {date_label}."
    add(q, a, f"Total row count across the file", fname)

    top_cat = df['Job_Category'].value_counts().head(5)
    if not top_cat.empty:
        if is_arabic:
            q = f"ما أكثر التخصصات طلباً في سوق العمل في {country_ar} حالياً؟"
            a = "أعلى 5 قطاعات حسب عدد الوظائف: " + "؛ ".join([f"{n}: {c}" for n, c in top_cat.items()])
        else:
            q = f"What are the most in-demand job sectors in {country} right now?"
            a = "Top 5 sectors by posting count: " + "; ".join([f"{n}: {c}" for n, c in top_cat.items()])
        add(q, a, "Aggregated counts by Job_Category", fname)


# ---------------------------------------------------------------------------
# 11) SALARY & COMPENSATION QUERIES (Bayt)
# ---------------------------------------------------------------------------
print("Generating salary questions...")

for key, fname in BAYT_FILES.items():
    df = bayt[key].copy()
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    country_key = "Qatar" if "Qatar" in key else ("Saudi" if "Saudi" in key else "UAE")
    country_ar = COUNTRY_AR[country_key]
    is_arabic = "_AR_" in key
    df['_max_sal'] = df['Salary_Range_USD'].apply(parse_max_salary_usd)
    salaried = df.dropna(subset=['_max_sal']).sort_values('_max_sal', ascending=False)
    if len(salaried) >= 3:
        top = salaried.head(5)
        if is_arabic:
            q = f"ما الوظائف الأعلى أجراً في {country_ar} حالياً؟"
            a = "أعلى الوظائف أجراً: " + "; ".join([f"{r['Job_Title']} ({r['Salary_Range_USD']})" for _, r in top.iterrows()])
        else:
            q = f"What are the highest-paying jobs in {country} right now?"
            a = "Top-paying postings: " + "; ".join([f"{r['Job_Title']} ({r['Salary_Range_USD']})" for _, r in top.iterrows()])
        add(q, a, fmt_ref_list(top, 'Job_ID', 'Job_Title', 5), fname)


# ---------------------------------------------------------------------------
# 12) CROSS-COUNTRY COMPARISON (Bayt)
# ---------------------------------------------------------------------------
print("Generating cross-country comparison questions...")

for date_key, date_label, date_ar in [
    ("07Jun2026", "07 Jun 2026", "7 يونيو 2026"),
    ("12May2026", "12 May 2026", "12 مايو 2026"),
]:
    qa_df = bayt.get(f"Qatar_EN_{date_key}")
    sa_df = bayt.get(f"Saudi_EN_{date_key}")
    ae_df = bayt.get(f"UAE_EN_{date_key}")
    if qa_df is None or sa_df is None or ae_df is None:
        continue
    counts = {"Qatar": len(qa_df), "Saudi Arabia": len(sa_df), "UAE": len(ae_df)}
    files = [BAYT_FILES[f"Qatar_EN_{date_key}"], BAYT_FILES[f"Saudi_EN_{date_key}"], BAYT_FILES[f"UAE_EN_{date_key}"]]
    f_join = "; ".join(files)
    largest = max(counts, key=counts.get)
    add(
        f"I'm open to relocating. Which GCC country has the largest job market on Bayt as of {date_label}?",
        f"{largest} has the largest market with {counts[largest]} postings. Full breakdown — " + "; ".join([f"{k}: {v}" for k, v in counts.items()]),
        "Aggregated counts across three country files",
        f_join,
    )
    # IT comparison
    it_counts = {
        "Qatar": int((qa_df['Job_Category'].astype(str).str.upper() == 'IT').sum()),
        "Saudi Arabia": int((sa_df['Job_Category'].astype(str).str.upper() == 'IT').sum()),
        "UAE": int((ae_df['Job_Category'].astype(str).str.upper() == 'IT').sum()),
    }
    add(
        f"Where are most IT jobs being posted on Bayt as of {date_label} — Qatar, Saudi Arabia or UAE?",
        f"{max(it_counts, key=it_counts.get)} has the most IT postings. Breakdown — " + "; ".join([f"{k}: {v}" for k, v in it_counts.items()]),
        "Filtered by Job_Category == IT across three country files",
        f_join,
    )
    # Engineering
    eng_counts = {
        "Qatar": int((qa_df['Job_Category'] == 'Engineering').sum()),
        "Saudi Arabia": int((sa_df['Job_Category'] == 'Engineering').sum()),
        "UAE": int((ae_df['Job_Category'] == 'Engineering').sum()),
    }
    add(
        f"I'm an engineer. Where should I focus my job search across the GCC as of {date_label}?",
        f"{max(eng_counts, key=eng_counts.get)} has the most engineering postings. Breakdown — " + "; ".join([f"{k}: {v}" for k, v in eng_counts.items()]),
        "Filtered by Job_Category == Engineering across three country files",
        f_join,
    )
    # Healthcare
    hc_counts = {
        "Qatar": int((qa_df['Job_Category'] == 'Healthcare').sum()),
        "Saudi Arabia": int((sa_df['Job_Category'] == 'Healthcare').sum()),
        "UAE": int((ae_df['Job_Category'] == 'Healthcare').sum()),
    }
    add(
        f"Which GCC country has the most healthcare jobs on Bayt as of {date_label}?",
        f"{max(hc_counts, key=hc_counts.get)} leads with {hc_counts[max(hc_counts, key=hc_counts.get)]} postings. Breakdown — " + "; ".join([f"{k}: {v}" for k, v in hc_counts.items()]),
        "Filtered by Job_Category == Healthcare across three country files",
        f_join,
    )


# ---------------------------------------------------------------------------
# 13) TIME COMPARISON — May vs June (Bayt)
# ---------------------------------------------------------------------------
print("Generating time-comparison questions...")

for country_key in ["Qatar", "Saudi", "UAE"]:
    cn = COUNTRY_FROM_KEY[country_key]
    may = bayt.get(f"{country_key}_EN_12May2026")
    jun = bayt.get(f"{country_key}_EN_07Jun2026")
    if may is None or jun is None:
        continue
    f_may = BAYT_FILES[f"{country_key}_EN_12May2026"]
    f_jun = BAYT_FILES[f"{country_key}_EN_07Jun2026"]
    delta = len(jun) - len(may)
    trend = "grew" if delta > 0 else ("shrank" if delta < 0 else "stayed the same")
    add(
        f"Did the job market in {cn} grow between May and June 2026?",
        f"The Bayt {cn} listings {trend}: 12 May 2026 had {len(may)} postings while 07 Jun 2026 had {len(jun)} (net change: {delta}).",
        "Time-series comparison across two scrape dates",
        f"{f_may}; {f_jun}",
    )
    new_jobs = set(jun['Job_ID']) - set(may['Job_ID'])
    add(
        f"How many new jobs were posted in {cn} between 12 May and 07 Jun 2026?",
        f"{len(new_jobs)} new postings appeared in the 07 Jun 2026 scrape that weren't present in the 12 May 2026 scrape.",
        "Set difference of Job_ID between two scrape dates",
        f"{f_may}; {f_jun}",
    )


# ---------------------------------------------------------------------------
# 14) SOURCE COMPARISON — Bayt vs LinkedIn
# ---------------------------------------------------------------------------
print("Generating source-comparison questions...")

for country, bk, lk in [
    ("Qatar",        "Qatar_EN_07Jun2026", "Qatar_07Jun2026"),
    ("Saudi Arabia", "Saudi_EN_07Jun2026", "Saudi_07Jun2026"),
    ("UAE",          "UAE_EN_07Jun2026",   "UAE_07Jun2026"),
]:
    bdf = bayt[bk]
    ldf = linkedin[lk]
    add(
        f"Should I search Bayt or LinkedIn for more job opportunities in {country}?",
        f"As of 07 Jun 2026, Bayt has {len(bdf)} postings for {country} while LinkedIn has {len(ldf)}. "
        + ("Bayt has more listings." if len(bdf) > len(ldf) else "LinkedIn has more listings."),
        "Compare row counts across two sources",
        f"{BAYT_FILES[bk]}; {LINKEDIN_FILES[lk]}",
    )
    bayt_rem = int(bdf['Employment_Type'].astype(str).str.contains('Remote', case=False, na=False).sum())
    li_rem = int(ldf['is_remote'].fillna(False).astype(bool).sum())
    add(
        f"Where will I find more remote work in {country} — Bayt or LinkedIn?",
        f"Bayt has {bayt_rem} postings labeled remote and LinkedIn has {li_rem} flagged is_remote=True for {country} as of 07 Jun 2026.",
        "Compare remote-job counts across sources",
        f"{BAYT_FILES[bk]}; {LINKEDIN_FILES[lk]}",
    )


# ---------------------------------------------------------------------------
# 15) SPECIFIC-JOB QUESTIONS (natural phrasing using title + city + company)
#     One question per job, identifying the role by job title and location/company
#     so that a user could plausibly ask it. No Job IDs in the question.
# ---------------------------------------------------------------------------
print("Generating specific-job questions (natural phrasing)...")


def diversify_sample(df, n, seed):
    if 'Job_Category' in df.columns:
        groups = df.dropna(subset=['Job_Category']).groupby('Job_Category')
        rows = []
        per = max(1, n // max(1, len(groups)))
        for name, g in groups:
            rows.append(g.sample(min(len(g), per), random_state=seed))
        out = pd.concat(rows).drop_duplicates('Job_ID')
        return out.head(n)
    return df.head(n)


seed = 100
for key, fname in BAYT_FILES.items():
    df = bayt[key]
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    country_key = "Qatar" if "Qatar" in key else ("Saudi" if "Saudi" in key else "UAE")
    country_ar = COUNTRY_AR[country_key]
    is_arabic = "_AR_" in key
    sample = diversify_sample(df, 25, seed)
    seed += 1

    for _, row in sample.iterrows():
        title = clean_title(row['Job_Title'])
        if not title:
            continue
        city = clean_city(row.get('Job_Location'))
        place = f"in {city}" if city else f"in {country}"
        place_ar = f"في {CITY_AR.get(city, city)}" if city else f"في {country_ar}"
        r = f"{row['Job_ID']} - {title}"

        if pd.notna(row.get('Salary_Range_USD')):
            if is_arabic:
                q = f"ما الراتب المعروض لوظيفة {title} {place_ar}؟"
                a = f"الراتب المعلن: {safe(row['Salary_Range_USD'])}."
            else:
                q = f"What salary is being offered for the {title} role {place}?"
                a = f"The advertised salary is {safe(row['Salary_Range_USD'])}."
            add(q, a, r, fname)

        if pd.notna(row.get('Years_of_Experience')):
            if is_arabic:
                q = f"كم سنة خبرة مطلوبة لوظيفة {title} {place_ar}؟"
                a = f"المطلوب: {safe(row['Years_of_Experience'])}."
            else:
                q = f"How many years of experience are required for the {title} position {place}?"
                a = f"Required experience: {safe(row['Years_of_Experience'])}."
            add(q, a, r, fname)

        if pd.notna(row.get('Job_Skills')):
            if is_arabic:
                q = f"ما المهارات المطلوبة للتقديم على وظيفة {title} {place_ar}؟"
                a = safe(row['Job_Skills'])
            else:
                q = f"What skills are required to apply for the {title} role {place}?"
                a = safe(row['Job_Skills'])
            add(q, a, r, fname)

        if pd.notna(row.get('Education_Level')):
            if is_arabic:
                q = f"ما المؤهل العلمي المطلوب لوظيفة {title} {place_ar}؟"
                a = safe(row['Education_Level'])
            else:
                q = f"What education level is required for the {title} role {place}?"
                a = safe(row['Education_Level'])
            add(q, a, r, fname)

        if pd.notna(row.get('Language_Requirement')):
            if is_arabic:
                q = f"ما اللغات المطلوبة لوظيفة {title} {place_ar}؟"
                a = safe(row['Language_Requirement'])
            else:
                q = f"What language requirements apply to the {title} role {place}?"
                a = safe(row['Language_Requirement'])
            add(q, a, r, fname)

        if pd.notna(row.get('Gender')) and str(row['Gender']).lower() != 'any':
            if is_arabic:
                q = f"هل وظيفة {title} {place_ar} مخصصة لجنس معين؟"
                a = f"الجنس المفضل: {safe(row['Gender'])}."
            else:
                q = f"Does the {title} position {place} specify a gender preference?"
                a = f"Gender preference: {safe(row['Gender'])}."
            add(q, a, r, fname)

        if pd.notna(row.get('Employment_Type')):
            if is_arabic:
                q = f"ما نوع التوظيف لوظيفة {title} {place_ar}؟"
                a = safe(row['Employment_Type'])
            else:
                q = f"What is the employment type for the {title} role {place}?"
                a = safe(row['Employment_Type'])
            add(q, a, r, fname)

        if pd.notna(row.get('Job_Description')):
            desc = safe(row['Job_Description'])
            short = desc if len(desc) < 600 else desc[:600] + "..."
            if is_arabic:
                q = f"ما طبيعة العمل في وظيفة {title} {place_ar}؟"
                a = short
            else:
                q = f"What does the {title} role {place} involve?"
                a = short
            add(q, a, r, fname)


# Same for LinkedIn — use company + city as natural identifier
seed = 200
for key, fname in LINKEDIN_FILES.items():
    df = linkedin[key]
    country = "Qatar" if "Qatar" in key else ("Saudi Arabia" if "Saudi" in key else "UAE")
    # Diversify by industry
    if 'company_industry' in df.columns:
        sample = df.dropna(subset=['title', 'company', 'company_industry']).groupby('company_industry').head(2).head(30)
    else:
        sample = df.dropna(subset=['title', 'company']).head(20)

    for _, row in sample.iterrows():
        title = clean_title(row['title'])
        if not title:
            continue
        company = safe(row.get('company'))
        loc = safe(row.get('location'))
        r = f"{row.get('id', 'N/A')} - {title}"

        add(
            f"What does the {title} role at {company} in {loc} involve?",
            safe(row.get('description'))[:600] + ("..." if len(safe(row.get('description'))) > 600 else ""),
            r, fname,
        )
        if pd.notna(row.get('job_level')):
            add(
                f"What seniority level is the {title} role at {company} in {loc}?",
                safe(row['job_level']),
                r, fname,
            )
        if pd.notna(row.get('job_type')):
            add(
                f"Is the {title} role at {company} in {loc} full-time, contract or part-time?",
                safe(row['job_type']),
                r, fname,
            )
        if pd.notna(row.get('company_industry')):
            add(
                f"In which industry does {company} operate (hiring for {title} in {loc})?",
                safe(row['company_industry']),
                r, fname,
            )
        if row.get('is_remote') is True:
            add(
                f"Is the {title} role at {company} in {loc} a remote role?",
                "Yes — the listing is marked as remote.",
                r, fname,
            )


# ---------------------------------------------------------------------------
# 16) ENGLISH-vs-ARABIC dataset awareness (kept short — most users won't ask this)
# ---------------------------------------------------------------------------
print("Generating English-vs-Arabic dataset questions...")

for country_key in ["Qatar", "Saudi", "UAE"]:
    cn = COUNTRY_FROM_KEY[country_key]
    en = bayt.get(f"{country_key}_EN_12May2026")
    ar = bayt.get(f"{country_key}_AR_12May2026")
    if en is None or ar is None:
        continue
    f_en = BAYT_FILES[f"{country_key}_EN_12May2026"]
    f_ar = BAYT_FILES[f"{country_key}_AR_12May2026"]
    common = set(en['Job_ID']) & set(ar['Job_ID'])
    add(
        f"How consistent are the Arabic and English Bayt listings for {cn} (12 May 2026)?",
        f"{len(common)} of the Job IDs appear in both the English-extracted ({len(en)}) and Arabic-extracted ({len(ar)}) files for {cn}.",
        "Intersection of Job_ID across the two language extractions",
        f"{f_en}; {f_ar}",
    )


# ---------------------------------------------------------------------------
# 17) GLOBAL GCC-WIDE QUERIES
# ---------------------------------------------------------------------------
print("Generating global GCC-wide questions...")

all_bayt_07jun = pd.concat([bayt["Qatar_EN_07Jun2026"], bayt["Saudi_EN_07Jun2026"], bayt["UAE_EN_07Jun2026"]])
add(
    "How many job postings are available across the GCC (Qatar, Saudi Arabia, UAE) on Bayt as of 07 Jun 2026?",
    f"A total of {len(all_bayt_07jun)} postings across Qatar, Saudi Arabia and the UAE.",
    "Total row count across three Bayt country files",
    f"{BAYT_FILES['Qatar_EN_07Jun2026']}; {BAYT_FILES['Saudi_EN_07Jun2026']}; {BAYT_FILES['UAE_EN_07Jun2026']}",
)
cat_all = all_bayt_07jun['Job_Category'].value_counts().head(5)
add(
    "Which sectors dominate the GCC job market on Bayt as of 07 Jun 2026?",
    "Top 5 sectors across the GCC: " + "; ".join([f"{n}: {c}" for n, c in cat_all.items()]),
    "Aggregated Job_Category count across three country files",
    f"{BAYT_FILES['Qatar_EN_07Jun2026']}; {BAYT_FILES['Saudi_EN_07Jun2026']}; {BAYT_FILES['UAE_EN_07Jun2026']}",
)

all_li = pd.concat([linkedin["Qatar_07Jun2026"], linkedin["Saudi_07Jun2026"], linkedin["UAE_07Jun2026"]])
ind_all = all_li['company_industry'].value_counts().head(5)
add(
    "Which industries are most active on LinkedIn across the GCC as of 07 Jun 2026?",
    "Top 5 industries: " + "; ".join([f"{n}: {c}" for n, c in ind_all.items()]),
    "Aggregated company_industry count across three LinkedIn country files",
    f"{LINKEDIN_FILES['Qatar_07Jun2026']}; {LINKEDIN_FILES['Saudi_07Jun2026']}; {LINKEDIN_FILES['UAE_07Jun2026']}",
)


# ---------------------------------------------------------------------------
# 18) DEDUPLICATE & SAVE
# ---------------------------------------------------------------------------
print(f"\nGenerated {len(qa_rows)} raw QA pairs. Deduplicating...")
out = pd.DataFrame(qa_rows).drop_duplicates(subset=['Question', 'Filename'])
print(f"After dedupe: {len(out)} QA pairs.")

out.to_excel(OUT_PATH, index=False)
print(f"\nSaved to {OUT_PATH}")
print(f"Total QA pairs: {len(out)}")
print("\nBreakdown by Filename:")
print(out['Filename'].value_counts())
