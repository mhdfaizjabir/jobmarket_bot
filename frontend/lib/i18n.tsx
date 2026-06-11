'use client';

import { createContext, useContext, useEffect, useState, ReactNode } from 'react';

export type Lang = 'en' | 'ar';

const dictionaries: Record<Lang, Record<string, any>> = {
  en: {
    nav: {
      brand: 'GCC Job Market Intel',
      features: 'Features',
      services: 'Services',
      faq: 'FAQ',
      getStarted: 'Get Started',
    },
    hero: {
      badge: 'AI-Powered Labor Market Intelligence',
      title: 'Understand the GCC Job Market in Real Time',
      highlight: 'Real Time',
      subtitle:
        'Fanar-powered analytics and a conversational assistant built on live job postings from Bayt.com and LinkedIn across Qatar, the UAE, and Saudi Arabia.',
      cta: 'Get Started',
      ctaSecondary: 'How it works',
    },
    pipeline: {
      title: 'How It Works',
      subtitle: 'From raw job postings to actionable insight — fully automated.',
      step1Title: 'Collect',
      step1Desc: 'Job postings are continuously gathered from Bayt.com and LinkedIn across the GCC.',
      step2Title: 'Structure',
      step2Desc: 'Postings are cleaned, deduplicated, and organized into structured Excel datasets.',
      step3Title: 'Analyze',
      step3Desc: 'Fanar, an Arabic-first LLM, extracts skills, salaries, sectors, and trends from the data.',
      step4Title: 'Deliver',
      step4Desc: 'Insights surface in an interactive dashboard and a conversational chatbot.',
    },
    features: {
      title: 'Everything you need to read the market',
      subtitle: 'Powerful tools for exploring GCC job market data, in one place.',
      item1Title: 'Live Dashboards',
      item1Desc: 'Explore postings by country, sector, career level, and time with interactive charts.',
      item2Title: 'AI Chat Assistant',
      item2Desc: 'Ask natural-language questions about salaries, skills, and hiring trends.',
      item3Title: 'Multi-Country Coverage',
      item3Desc: 'Qatar, UAE, and Saudi Arabia job markets in one place.',
      item4Title: 'Bilingual & Themeable',
      item4Desc: 'Full English/Arabic support with light and dark modes.',
    },
    trusted: {
      title: 'Powered by data & models from',
    },
    faq: {
      title: 'Frequently Asked Questions',
      q1: 'Where does the data come from?',
      a1: 'Job postings are collected from Bayt.com and LinkedIn across GCC countries and refreshed regularly.',
      q2: 'What is Fanar?',
      a2: 'Fanar is an Arabic-first large language model that analyzes job postings to extract skills, salaries, sectors, and market trends.',
      q3: 'Can I ask questions directly?',
      a3: 'Yes — the chat assistant lets you ask natural-language questions and get answers grounded in the real data.',
      q4: 'Which countries are covered?',
      a4: 'The platform currently covers Qatar, the UAE, and Saudi Arabia, with more on the way.',
    },
    footer: {
      tagline: 'AI-powered GCC labor market insights.',
      rights: 'All rights reserved.',
    },
    app: {
      title: 'GCC Job Market Intelligence',
      dashboard: 'Dashboard',
      chat: 'Chat',
      home: 'Home',
    },
  },
  ar: {
    nav: {
      brand: 'ذكاء سوق العمل الخليجي',
      features: 'المميزات',
      services: 'الخدمات',
      faq: 'الأسئلة الشائعة',
      getStarted: 'ابدأ الآن',
    },
    hero: {
      badge: 'تحليلات سوق العمل بالذكاء الاصطناعي',
      title: 'افهم سوق العمل الخليجي في الوقت الفعلي',
      highlight: 'الوقت الفعلي',
      subtitle:
        'تحليلات مدعومة بنموذج Fanar ومساعد محادثة ذكي مبني على إعلانات وظائف حقيقية من Bayt.com وLinkedIn في قطر والإمارات والسعودية.',
      cta: 'ابدأ الآن',
      ctaSecondary: 'كيف يعمل',
    },
    pipeline: {
      title: 'كيف يعمل',
      subtitle: 'من إعلانات الوظائف الخام إلى رؤى قابلة للتنفيذ — بشكل آلي بالكامل.',
      step1Title: 'الجمع',
      step1Desc: 'يتم جمع إعلانات الوظائف باستمرار من Bayt.com وLinkedIn في جميع أنحاء الخليج.',
      step2Title: 'التنظيم',
      step2Desc: 'يتم تنظيف الإعلانات وإزالة التكرار وتنظيمها في ملفات إكسل منظمة.',
      step3Title: 'التحليل',
      step3Desc: 'يقوم Fanar، النموذج اللغوي العربي، باستخراج المهارات والرواتب والقطاعات والاتجاهات من البيانات.',
      step4Title: 'العرض',
      step4Desc: 'تظهر النتائج في لوحة تحكم تفاعلية ومساعد محادثة ذكي.',
    },
    features: {
      title: 'كل ما تحتاجه لقراءة السوق',
      subtitle: 'أدوات قوية لاستكشاف بيانات سوق العمل الخليجي في مكان واحد.',
      item1Title: 'لوحات تحكم حية',
      item1Desc: 'استكشف الإعلانات حسب الدولة والقطاع والمستوى الوظيفي والزمن من خلال رسوم بيانية تفاعلية.',
      item2Title: 'مساعد محادثة ذكي',
      item2Desc: 'اطرح أسئلة بلغة طبيعية حول الرواتب والمهارات واتجاهات التوظيف.',
      item3Title: 'تغطية متعددة الدول',
      item3Desc: 'أسواق العمل في قطر والإمارات والسعودية في مكان واحد.',
      item4Title: 'ثنائي اللغة وقابل للتخصيص',
      item4Desc: 'دعم كامل للغتين العربية والإنجليزية مع وضعين فاتح وداكن.',
    },
    trusted: {
      title: 'مدعوم ببيانات ونماذج من',
    },
    faq: {
      title: 'الأسئلة الشائعة',
      q1: 'من أين تأتي البيانات؟',
      a1: 'يتم جمع إعلانات الوظائف من Bayt.com وLinkedIn عبر دول مجلس التعاون الخليجي وتحديثها بشكل دوري.',
      q2: 'ما هو Fanar؟',
      a2: 'Fanar هو نموذج لغوي عربي كبير يحلل إعلانات الوظائف لاستخراج المهارات والرواتب والقطاعات واتجاهات السوق.',
      q3: 'هل يمكنني طرح الأسئلة مباشرة؟',
      a3: 'نعم — يتيح لك مساعد المحادثة طرح أسئلة بلغة طبيعية والحصول على إجابات مبنية على البيانات الفعلية.',
      q4: 'ما هي الدول المشمولة؟',
      a4: 'تغطي المنصة حالياً قطر والإمارات والسعودية، مع المزيد قريباً.',
    },
    footer: {
      tagline: 'رؤى سوق العمل الخليجي مدعومة بالذكاء الاصطناعي.',
      rights: 'جميع الحقوق محفوظة.',
    },
    app: {
      title: 'ذكاء سوق العمل الخليجي',
      dashboard: 'لوحة التحكم',
      chat: 'المحادثة',
      home: 'الرئيسية',
    },
  },
};

interface LanguageContextValue {
  lang: Lang;
  dir: 'ltr' | 'rtl';
  toggleLang: () => void;
  t: (path: string) => string;
}

const LanguageContext = createContext<LanguageContextValue>({
  lang: 'en',
  dir: 'ltr',
  toggleLang: () => {},
  t: (path: string) => path,
});

function lookup(dict: Record<string, any>, path: string): string {
  const value = path.split('.').reduce<any>((acc, key) => (acc == null ? acc : acc[key]), dict);
  return typeof value === 'string' ? value : path;
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>('en');

  useEffect(() => {
    const stored = localStorage.getItem('lang') as Lang | null;
    const initial = stored === 'ar' || stored === 'en' ? stored : 'en';
    applyLang(initial);
    setLang(initial);
  }, []);

  function applyLang(next: Lang) {
    document.documentElement.lang = next;
    document.documentElement.dir = next === 'ar' ? 'rtl' : 'ltr';
  }

  function toggleLang() {
    setLang(prev => {
      const next: Lang = prev === 'en' ? 'ar' : 'en';
      applyLang(next);
      localStorage.setItem('lang', next);
      return next;
    });
  }

  const dir: 'ltr' | 'rtl' = lang === 'ar' ? 'rtl' : 'ltr';
  const t = (path: string) => lookup(dictionaries[lang], path);

  return (
    <LanguageContext.Provider value={{ lang, dir, toggleLang, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  return useContext(LanguageContext);
}
