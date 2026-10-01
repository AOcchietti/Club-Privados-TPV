import { useEffect, useState } from "react";
import api, { fmtEUR, fmtDateTime } from "@/lib/api";
import TicketDialog from "@/components/TicketDialog";
import { History, Receipt, Banknote, CreditCard, Coins } from "lucide-react";

const RANGES = [
  { id: "today", label: "Hoy" },
  { id: "7d", label: "7 días" },
  { id: "30d", label: "30 días" },
  { id: "all", label: "Todo" },
];

export default function Historico() {
  const [sales, setSales] = useState([]);
  const [range, setRange] = useState("today");
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .get("/sales", { params: { range } })
      .then((r) => setSales(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [range]);

  const totalSum = sales.reduce((a, s) => a + s.total, 0);

  return (
    <div className="space-y-5" data-testid="historico-page">
      <div>
        <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">Histórico de ventas</h1>
        <p className="text-sm text-slate-500 mt-1">
          {sales.length} tickets · <span className="font-bold text-slate-700">{fmtEUR(totalSum)}</span> en el periodo.
        </p>
      </div>

      <div className="flex gap-2 flex-wrap">
        {RANGES.map((r) => (
          <button
            key={r.id}
            onClick={() => setRange(r.id)}
            data-testid={`sales-filter-${r.id}`}
            className={`px-3.5 py-2 rounded-full text-xs font-bold border transition-colors ${
              range === r.id ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
            }`}
          >
            {r.label}
          </button>
        ))}
        <span className="w-px bg-slate-200 mx-1 hidden sm:block" />
        <span className="text-xs text-slate-400 self-center">Todas las ventas se cobran del saldo del socio</span>
      </div>

      <div className="card-soft overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="sales-table">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-200 bg-slate-50/60">
                <th className="px-4 py-3">Ticket</th>
                <th className="px-4 py-3">Fecha</th>
                <th className="px-4 py-3">Socio</th>
                <th className="px-4 py-3">Cajero</th>
                <th className="px-4 py-3">Pago</th>
                <th className="px-4 py-3 text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {sales.map((s) => (
                <tr
                  key={s.id}
                  onClick={() => setSelected(s)}
                  className="border-b border-slate-100 hover:bg-amber-50/50 cursor-pointer transition-colors"
                  data-testid={`sale-row-${s.id}`}
                >
                  <td className="px-4 py-3 font-mono-num font-bold text-slate-900">{s.ticket_number}</td>
                  <td className="px-4 py-3 text-slate-600">{fmtDateTime(s.created_at)}</td>
                  <td className="px-4 py-3 text-slate-700 font-medium">{s.socio_name || <span className="text-slate-300">—</span>}</td>
                  <td className="px-4 py-3 text-slate-600">{s.cajero_name}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ${
                      s.payment_method === "saldo"
                        ? "bg-purple-50 text-purple-700 border-purple-200"
                        : s.payment_method === "efectivo"
                          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                          : "bg-sky-50 text-sky-700 border-sky-200"
                    }`}>
                      {s.payment_method === "saldo" ? <Coins className="w-3.5 h-3.5" /> : s.payment_method === "efectivo" ? <Banknote className="w-3.5 h-3.5" /> : <CreditCard className="w-3.5 h-3.5" />}
                      {s.payment_method}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono-num font-bold text-slate-900">{fmtEUR(s.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && sales.length === 0 && (
            <div className="py-16 text-center text-slate-400">
              <Receipt className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No hay ventas en este periodo.</p>
            </div>
          )}
          {loading && (
            <div className="py-16 text-center text-slate-400">
              <History className="w-8 h-8 mx-auto mb-2 opacity-50 animate-spin" />
            </div>
          )}
        </div>
      </div>

      <TicketDialog sale={selected} open={!!selected} onClose={() => setSelected(null)} />
    </div>
  );
}
