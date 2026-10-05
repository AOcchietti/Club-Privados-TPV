import { useState } from "react";
import { Outlet, NavLink, useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useAuth } from "@/context/AuthContext";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import {
  Citrus, LayoutDashboard, ShoppingBag, Package, Users, Wallet,
  History, Activity, LogOut, Menu, ClipboardList,
} from "lucide-react";

const NAV = [
  { to: "/", label: "Productos", icon: Package, testid: "nav-item-productos", roles: ["admin", "cajero"] },
  { to: "/tpv", label: "TPV · Vender", icon: ShoppingBag, testid: "nav-item-pos", roles: ["admin", "cajero"] },
  { to: "/gestion", label: "Gestión", icon: ClipboardList, testid: "nav-item-gestion", roles: ["admin", "cajero"] },
  { to: "/usuarios", label: "Socios y equipo", icon: Users, testid: "nav-item-socios", roles: ["admin", "cajero"] },
  { to: "/panel", label: "Panel", icon: LayoutDashboard, testid: "nav-item-panel", roles: ["admin"] },
  { to: "/caja", label: "Caja", icon: Wallet, testid: "nav-item-caja", roles: ["admin", "cajero"] },
  { to: "/historico", label: "Histórico", icon: History, testid: "nav-item-historico", roles: ["admin"] },
  { to: "/actividad", label: "Actividad", icon: Activity, testid: "nav-item-actividad", roles: ["admin"] },
];

function NavItems({ onNavigate }) {
  const { user } = useAuth();
  return (
    <nav className="flex flex-col gap-1 px-3">
      {NAV.filter((n) => n.roles.includes(user.role)).map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          onClick={onNavigate}
          data-testid={item.testid}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-semibold transition-colors ${
              isActive
                ? "bg-amber-400/90 text-slate-950 shadow-sm"
                : "text-slate-600 hover:bg-amber-100/70 hover:text-slate-900"
            }`
          }
        >
          <item.icon className="w-[18px] h-[18px]" />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

function UserCard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };
  return (
    <div className="mt-auto px-3 pb-4">
      <div className="card-soft p-3 flex items-center gap-3">
        <div className="w-9 h-9 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center font-bold text-sm">
          {user.name?.charAt(0)?.toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-bold text-slate-900 truncate" data-testid="user-name">{user.name}</p>
          <p className="text-xs text-slate-500 capitalize" data-testid="user-role-badge">{user.role}</p>
        </div>
        <button
          onClick={handleLogout}
          data-testid="logout-button"
          title="Cerrar sesión"
          className="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

function SidebarContent({ onNavigate }) {
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2.5 px-5 pt-6 pb-6">
        <div className="w-10 h-10 rounded-2xl bg-amber-400 flex items-center justify-center shadow-sm">
          <Citrus className="w-6 h-6 text-slate-950" />
        </div>
        <div>
          <p className="font-display font-bold text-slate-900 leading-tight">Weed Lemon</p>
          <p className="text-[11px] text-slate-500 font-medium tracking-wide uppercase">Social Club · Sevilla</p>
        </div>
      </div>
      <NavItems onNavigate={onNavigate} />
      <UserCard />
    </div>
  );
}

export default function Layout() {
  const location = useLocation();
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen bg-[#FDFBF3]">
      {/* Sidebar escritorio */}
      <aside className="hidden lg:flex fixed inset-y-0 left-0 w-64 flex-col bg-[#FAFAF7] border-r border-slate-200/70 z-30">
        <SidebarContent />
      </aside>

      {/* Topbar móvil */}
      <div className="lg:hidden sticky top-0 z-40 bg-[#FAFAF7]/90 backdrop-blur-md border-b border-slate-200/70 px-4 py-3 flex items-center gap-3">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <button className="p-2 rounded-xl border border-slate-200 bg-white" data-testid="mobile-menu-button">
              <Menu className="w-5 h-5 text-slate-700" />
            </button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 p-0 bg-[#FAFAF7]">
            <SidebarContent onNavigate={() => setOpen(false)} />
          </SheetContent>
        </Sheet>
        <div className="flex items-center gap-2">
          <Citrus className="w-5 h-5 text-amber-500" />
          <span className="font-display font-bold text-slate-900">Weed Lemon</span>
        </div>
      </div>

      <div className="lg:pl-64">
        <motion.main
          key={location.pathname}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
          className="p-4 sm:p-6 lg:p-8 max-w-[1400px]"
        >
          <Outlet />
        </motion.main>
      </div>
    </div>
  );
}
