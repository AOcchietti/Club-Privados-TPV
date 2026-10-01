import { useEffect, useState } from "react";
import api, { fmtDateTime } from "@/lib/api";
import {
  Activity, LogIn, LogOut, ShoppingBag, Package, UserPlus, Pencil,
  Trash2, Wallet, Lock, ArrowDownLeft, ArrowUpRight, Power,
} from "lucide-react";

const ICONS = {
  login: { icon: LogIn, bg: "bg-emerald-100 text-emerald-600" },
  logout: { icon: LogOut, bg: "bg-slate-100 text-slate-500" },
  venta: { icon: ShoppingBag, bg: "bg-amber-100 text-amber-600" },
  producto_creado: { icon: Package, bg: "bg-sky-100 text-sky-600" },
  producto_editado: { icon: Pencil, bg: "bg-sky-100 text-sky-600" },
  producto_estado: { icon: Power, bg: "bg-sky-100 text-sky-600" },
  producto_eliminado: { icon: Trash2, bg: "bg-red-100 text-red-500" },
  usuario_creado: { icon: UserPlus, bg: "bg-purple-100 text-purple-600" },
  usuario_editado: { icon: Pencil, bg: "bg-purple-100 text-purple-600" },
  usuario_eliminado: { icon: Trash2, bg: "bg-red-100 text-red-500" },
  caja_abierta: { icon: Wallet, bg: "bg-emerald-100 text-emerald-600" },
  caja_cerrada: { icon: Lock, bg: "bg-amber-100 text-amber-600" },
  movimiento_caja: { icon: ArrowDownLeft, bg: "bg-orange-100 text-orange-600" },
};

export default function Actividad() {
  const [items, setItems] = useState(null);

  useEffect(() => {
    api.get("/activity").then((r) => setItems(r.data)).catch(() => setItems([]));
  }, []);

  return (
    <div className="space-y-5" data-testid="actividad-page">
      <div>
        <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">Registro de actividad</h1>
        <p className="text-sm text-slate-500 mt-1">Todas las operaciones del sistema, en orden cronológico.</p>
      </div>

      <div className="card-soft p-5">
        {items === null ? (
          <p className="text-sm text-slate-400 text-center py-10">Cargando actividad…</p>
        ) : items.length === 0 ? (
          <div className="py-16 text-center text-slate-400">
            <Activity className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">Aún no hay actividad registrada.</p>
          </div>
        ) : (
          <div className="relative pl-6">
            <div className="absolute left-[15px] top-2 bottom-2 w-px bg-slate-200" />
            <div className="space-y-4">
              {items.map((a) => {
                const cfg = ICONS[a.action] || { icon: Activity, bg: "bg-slate-100 text-slate-500" };
                return (
                  <div key={a.id} className="flex items-start gap-3 relative" data-testid={`activity-item-${a.id}`}>
                    <span className={`w-8 h-8 rounded-lg ${cfg.bg} flex items-center justify-center shrink-0 -ml-6 ring-4 ring-white`}>
                      <cfg.icon className="w-4 h-4" />
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-slate-800">
                        <span className="font-bold">{a.user_name}</span>{" "}
                        <span className="text-slate-500 capitalize text-xs">({a.user_role})</span>
                      </p>
                      <p className="text-sm text-slate-600">{a.details}</p>
                    </div>
                    <span className="text-xs text-slate-400 whitespace-nowrap pt-0.5">{fmtDateTime(a.created_at)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
