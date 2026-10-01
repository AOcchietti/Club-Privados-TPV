import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api, { fmtEUR, fmtDateTime, fmtDate } from "@/lib/api";
import TicketDialog from "@/components/TicketDialog";
import RechargeDialog from "@/components/RechargeDialog";
import { ArrowLeft, Coins, ShoppingBag, Phone, Mail, IdCard, Banknote, CreditCard, Receipt, UserRound } from "lucide-react";

export default function SocioFicha() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [socio, setSocio] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [sales, setSales] = useState([]);
  const [recharges, setRecharges] = useState([]);
  const [rechargeOpen, setRechargeOpen] = useState(false);
  const [selectedSale, setSelectedSale] = useState(null);

  const load = () => {
    api.get(`/users/${id}`).then((r) => setSocio(r.data)).catch(() => setNotFound(true));
    api.get("/sales", { params: { range: "all", socio_id: id } }).then((r) => setSales(r.data)).catch(() => {});
    api.get(`/users/${id}/recharges`).then((r) => setRecharges(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (notFound) {
    return (
      <div className="text-center py-20" data-testid="socio-not-found">
        <UserRound className="w-10 h-10 mx-auto text-slate-300 mb-3" />
        <p className="text-slate-500">Socio no encontrado.</p>
        <button onClick={() => navigate("/usuarios")} className="btn-outline mt-4">Volver a socios</button>
      </div>
    );
  }
  if (!socio) {
    return <div className="text-sm text-slate-500 py-20 text-center">Cargando ficha…</div>;
  }

  const totalGastado = sales.reduce((a, s) => a + s.total, 0);
  const gramos = sales.reduce((a, s) => a + s.items.filter((i) => i.unit === "g").reduce((x, i) => x + i.qty, 0), 0);
  const totalRecargado = recharges.reduce((a, r) => a + r.amount, 0);

  return (
    <div className="space-y-5" data-testid="socio-ficha-page">
      <button onClick={() => navigate("/usuarios")} className="btn-outline py-2 text-sm" data-testid="socio-back-btn">
        <ArrowLeft className="w-4 h-4" /> Volver a socios
      </button>

      {/* Cabecera de la ficha */}
      <div className="card-soft p-6 flex flex-col md:flex-row md:items-center gap-6">
        <div className="w-20 h-20 rounded-3xl bg-amber-100 text-amber-700 flex items-center justify-center font-display font-extrabold text-3xl shrink-0">
          {socio.name.charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="font-display text-3xl font-bold tracking-tight text-slate-900" data-testid="socio-name">{socio.name}</h1>
            <span className={socio.status === "activa" ? "badge-active" : "badge-inactive"} data-testid="socio-status">{socio.status}</span>
          </div>
          <p className="text-sm text-slate-500 mt-1 font-mono-num font-bold">{socio.member_number}</p>
          <div className="flex gap-4 mt-2 text-sm text-slate-500 flex-wrap">
            {socio.dni && <span className="flex items-center gap-1.5"><IdCard className="w-4 h-4" /> {socio.dni}</span>}
            {socio.phone && <span className="flex items-center gap-1.5"><Phone className="w-4 h-4" /> {socio.phone}</span>}
            {socio.email && <span className="flex items-center gap-1.5"><Mail className="w-4 h-4" /> {socio.email}</span>}
            <span>Socio desde {fmtDate(socio.created_at)}</span>
          </div>
        </div>
        <div className="flex flex-col items-stretch gap-3 md:w-64">
          <div className={`rounded-2xl px-5 py-3 border ${(socio.balance || 0) < 0 ? "bg-red-50 border-red-200" : "bg-emerald-50 border-emerald-200"}`}>
            <p className={`text-xs font-semibold uppercase tracking-wider ${(socio.balance || 0) < 0 ? "text-red-500" : "text-emerald-600"}`}>
              {(socio.balance || 0) < 0 ? "Deuda pendiente" : "Saldo disponible"}
            </p>
            <p className={`font-display text-3xl font-extrabold ${(socio.balance || 0) < 0 ? "text-red-600" : "text-emerald-700"}`} data-testid="socio-balance">{fmtEUR(socio.balance || 0)}</p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => setRechargeOpen(true)} className="btn-secondary flex-1 px-3" data-testid="socio-recharge-btn">
              <Coins className="w-4 h-4" /> Recargar
            </button>
            <button onClick={() => navigate(`/tpv?socio=${socio.id}`)} className="btn-primary flex-1 px-3" data-testid="socio-sell-btn">
              <ShoppingBag className="w-4 h-4" /> Vender
            </button>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: "Compras", value: sales.length, testid: "socio-stat-compras" },
          { label: "Total gastado", value: fmtEUR(totalGastado), testid: "socio-stat-gastado" },
          { label: "Gramos totales", value: `${Math.round(gramos * 10) / 10} g`, testid: "socio-stat-gramos" },
          { label: "Total recargado", value: fmtEUR(totalRecargado), testid: "socio-stat-recargado" },
        ].map((s) => (
          <div key={s.label} className="card-soft p-4" data-testid={s.testid}>
            <p className="font-display text-2xl font-extrabold text-slate-900">{s.value}</p>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mt-1">{s.label}</p>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-3 gap-4 items-start">
        {/* Histórico de compras */}
        <div className="card-soft p-5 lg:col-span-2" data-testid="socio-sales-history">
          <h2 className="font-display text-lg font-semibold text-slate-900 mb-3">Histórico de compras</h2>
          {sales.length === 0 ? (
            <div className="py-10 text-center text-slate-400">
              <Receipt className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">Este socio aún no tiene compras.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-200">
                    <th className="py-2 pr-4">Ticket</th>
                    <th className="py-2 pr-4">Fecha</th>
                    <th className="py-2 pr-4">Productos</th>
                    <th className="py-2 pr-4">Pago</th>
                    <th className="py-2 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {sales.map((s) => (
                    <tr key={s.id} onClick={() => setSelectedSale(s)} className="border-b border-slate-100 hover:bg-amber-50/50 cursor-pointer transition-colors" data-testid={`socio-sale-${s.id}`}>
                      <td className="py-2.5 pr-4 font-mono-num font-bold text-slate-900">{s.ticket_number}</td>
                      <td className="py-2.5 pr-4 text-slate-600">{fmtDateTime(s.created_at)}</td>
                      <td className="py-2.5 pr-4 text-slate-600">{s.items.map((i) => `${i.name} ×${i.qty}${i.unit}`).join(", ")}</td>
                      <td className="py-2.5 pr-4">
                        <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full border ${
                          s.payment_method === "efectivo" ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                          : s.payment_method === "tarjeta" ? "bg-sky-50 text-sky-700 border-sky-200"
                          : "bg-purple-50 text-purple-700 border-purple-200"
                        }`}>
                          {s.payment_method === "efectivo" ? <Banknote className="w-3 h-3" /> : s.payment_method === "tarjeta" ? <CreditCard className="w-3 h-3" /> : <Coins className="w-3 h-3" />}
                          {s.payment_method}
                        </span>
                      </td>
                      <td className="py-2.5 text-right font-mono-num font-bold text-slate-900">{fmtEUR(s.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Histórico de recargas */}
        <div className="card-soft p-5" data-testid="socio-recharges-history">
          <h2 className="font-display text-lg font-semibold text-slate-900 mb-3">Recargas de saldo</h2>
          {recharges.length === 0 ? (
            <p className="text-sm text-slate-400 py-6 text-center">Sin recargas todavía.</p>
          ) : (
            <div className="divide-y divide-slate-100">
              {recharges.map((r) => (
                <div key={r.id} className="py-2.5 flex items-center gap-3" data-testid={`socio-recharge-${r.id}`}>
                  <span className={`w-8 h-8 rounded-lg flex items-center justify-center ${r.method === "efectivo" ? "bg-emerald-100 text-emerald-600" : "bg-sky-100 text-sky-600"}`}>
                    {r.method === "efectivo" ? <Banknote className="w-4 h-4" /> : <CreditCard className="w-4 h-4" />}
                  </span>
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-slate-800 font-mono-num">+{fmtEUR(r.amount)}</p>
                    <p className="text-xs text-slate-400">{r.created_by} · {fmtDateTime(r.created_at)}</p>
                  </div>
                  <span className="text-xs text-slate-400 capitalize">{r.method}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <TicketDialog sale={selectedSale} open={!!selectedSale} onClose={() => setSelectedSale(null)} />
      <RechargeDialog socio={socio} open={rechargeOpen} onClose={() => setRechargeOpen(false)} onDone={load} />
    </div>
  );
}
