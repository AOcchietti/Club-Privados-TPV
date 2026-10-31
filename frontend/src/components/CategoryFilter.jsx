import { ChevronDown } from "lucide-react";
import { topCategories, subcategoriesOf, parentOf } from "@/lib/api";

// Filtro por categorías con subcategorías opcionales: al elegir una categoría que las tenga,
// aparece debajo una segunda fila para afinar ("Todo Flores", "Índica", "Sativa"…).
export default function CategoryFilter({ categories, value, onChange, allLabel = "Todas", testid = "category" }) {
  const tops = topCategories(categories);
  const activeTop = value ? parentOf(categories, value) || value : null;
  const subs = activeTop ? subcategoriesOf(categories, activeTop) : [];
  const topLabel = categories.find((c) => c.key === activeTop)?.label;

  return (
    <div className="space-y-2">
      <div className="flex gap-2 flex-wrap" data-testid={`${testid}-category-filters`}>
        {[{ key: null, label: allLabel }, ...tops].map((c) => {
          const active = activeTop === c.key;
          const hasSubs = c.key && subcategoriesOf(categories, c.key).length > 0;
          return (
            <button
              key={c.key || "all"}
              onClick={() => onChange(c.key)}
              data-testid={`${testid}-filter-${c.key || allLabel.toLowerCase()}`}
              className={`px-3.5 py-2 rounded-full text-xs font-bold transition-colors border inline-flex items-center gap-1 ${
                active ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
              }`}
            >
              {c.label}
              {hasSubs && <ChevronDown className={`w-3 h-3 transition-transform ${active ? "rotate-180 text-amber-300" : "text-slate-400"}`} />}
            </button>
          );
        })}
      </div>
      {subs.length > 0 && (
        <div className="flex gap-1.5 flex-wrap items-center pl-3 border-l-2 border-amber-300" data-testid={`${testid}-subcategory-filters`}>
          {[{ key: activeTop, label: `Todo ${topLabel}` }, ...subs].map((c) => {
            const active = value === c.key;
            return (
              <button
                key={c.key}
                onClick={() => onChange(c.key)}
                data-testid={`${testid}-subfilter-${c.key}`}
                className={`px-3 py-1.5 rounded-full text-[11px] font-bold transition-colors border ${
                  active ? "bg-amber-400 text-slate-900 border-amber-400" : "bg-amber-50/70 text-slate-600 border-amber-200 hover:border-amber-400"
                }`}
              >
                {c.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
