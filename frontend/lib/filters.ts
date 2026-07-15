// Mirrors the `label` field of each RAG/filter_registry.py entry, for display
// only (wire keys stay the same on the API boundary). Keep in sync manually —
// there's no shared runtime between the Python registry and this frontend.
export const FILTER_LABELS: Record<string, string> = {
  sector: 'sector',
  employment_type: 'employment type',
  career_level: 'career level',
  company: 'company',
  experience: 'experience',
  salary_bucket: 'salary range',
};

export function filterLabel(key: string): string {
  return FILTER_LABELS[key] ?? key;
}
