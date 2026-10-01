import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import api, { fmtEUR } from "@/lib/api";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { TrendingUp, ShoppingBag, Leaf, Users, AlertTriangle, Trophy } from "lucide-react";

const CARDS = [
  { key: "today_total", label: "Ventas de hoy", icon: TrendingUp, bg: "bg-amber-100", fg: "text-amber-700", money: true, testid: "stat-ventas-hoy" },
  { key: "today_count", label: "Tickets de hoy", icon: ShoppingBag, bg: "bg-emerald-100", fg: "text-emerald-700", testid: "stat-tickets-hoy" },
  { key: "grams_today", label: "Gramos dispensados hoy", icon: Leaf, bg: "bg-lime-100", fg: "text-lime-700", suffix: " g", testid: "stat-gramos-hoy" },
  { key: "socios_count", label: "Socios registrados", icon: Users, bg: "bg-sky-100", fg: "text-sky-700", testid: "stat-socios" },
];

export default function Dashboard() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.get("/dashboard/stats").then((r) => setStats(r.data)).catch(() => {});
  }, []);

  if (!stats) {
    return <div className="text-sm text-slate-500 py-20 text-center" data-testid="dashboard-loading">Cargando panel…</div>;
  }

  return (
    <div className="space-y-6" data-testid="dashboard-page">
      <div>
        <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">Buenas, ¿qué tal el día?</h1>
        <p className="text-sm text-slate-500 mt-1">Resumen de la actividad del club en tiempo real.</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        {CARDS.map((c, i) => (
          <motion.div
            key={c.key}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.06 }}
            className="card-soft p-4 sm:p-5"
            data-testid={c.testid}
          >
            <div className={`w-9 h-9 rounded-xl ${c.bg} ${c.fg} flex items-center justify-center mb-3`}>
              <c.icon className="w-4.5 h-4.5" style={{ width: 18, height: 18 }} />
            </div>
            <p className="font-display text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
              {c.money ? fmtEUR(stats[c.key]) : `${stats[c.key]}${c.suffix || ""}`}
            </p>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mt-1">{c.label}</p>
          </motion.div>
        ))}
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="card-soft p-5 lg:col-span-2" data-testid="dashboard-chart">
          <h2 className="font-display text-lg font-semibold text-slate-900 mb-4">Ventas · últimos 7 días</h2>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats.daily} margin={{ top: 4, right: 8, left: -14, bottom: 0 }}>
                <defs>
                  <linearGradient id="lemonFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#EAB308" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="#EAB308" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                <XAxis dataKey="dia" tick={{ fontSize: 12, fill: "#64748B" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 12, fill: "#64748B" }} axisLine={false} tickLine={false} />
                <Tooltip
                  formatter={(v) => [fmtEUR(v), "Ventas"]}
                  contentStyle={{ borderRadius: 12, border: "1px solid #E2E8F0", fontSize: 13 }}
                />
                <Area type="monotone" dataKey="total" stroke="#D97706" strokeWidth={2.5} fill="url(#lemonFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="space-y-4">
          <div className="card-soft p-5" data-testid="dashboard-top-products">
            <h2 className="font-display text-lg font-semibold text-slate-900 mb-3 flex items-center gap-2">
              <Trophy className="w-4 h-4 text-amber-500" /> Más vendidos (7 días)
            </h2>
            {stats.top_products.length === 0 && <p className="text-sm text-slate-400">Aún no hay ventas esta semana.</p>}
            <div className="space-y-2.5">
              {stats.top_products.map((p, i) => (
                <div key={p.name} className="flex items-center gap-3">
                  <span className="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 text-xs font-bold flex items-center justify-center">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-slate-800 truncate">{p.name}</p>
                    <p className="text-xs text-slate-400">{p.qty}{p.unit} vendidos</p>
                  </div>
                  <span className="text-sm font-mono-num font-bold text-slate-900">{fmtEUR(p.total)}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="card-soft p-5" data-testid="dashboard-low-stock">
            <h2 className="font-display text-lg font-semibold text-slate-900 mb-3 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-red-500" /> Stock bajo
            </h2>
            {stats.low_stock.length === 0 && <p className="text-sm text-slate-400">Todo el stock está en niveles sanos.</p>}
            <div className="space-y-2">
              {stats.low_stock.map((p) => (
                <div key={p.id} className="flex justify-between items-center text-sm">
                  <span className="text-slate-700 font-medium truncate">{p.name}</span>
                  <span className={`font-mono-num font-bold ${p.stock <= 0 ? "text-red-600" : "text-amber-600"}`}>
                    {p.stock}{p.unit}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
