import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import { Citrus } from "lucide-react";
import Login from "@/pages/Login";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import POS from "@/pages/POS";
import Productos from "@/pages/Productos";
import Usuarios from "@/pages/Usuarios";
import Caja from "@/pages/Caja";
import Historico from "@/pages/Historico";
import Actividad from "@/pages/Actividad";
import SocioFicha from "@/pages/SocioFicha";
import Gestion from "@/pages/Gestion";

function Splash() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-[#FDFBF3]" data-testid="app-loading">
      <Citrus className="w-10 h-10 text-amber-500 animate-pulse" />
      <p className="text-sm text-slate-500 font-medium">Cargando Weed Lemon…</p>
    </div>
  );
}

function AdminOnly({ children }) {
  const { user } = useAuth();
  if (user && user.role !== "admin") return <Navigate to="/" replace />;
  return children;
}

function Protected({ children }) {
  const { user } = useAuth();
  if (user === null) return <Splash />;
  if (user === false) return <Navigate to="/login" replace />;
  return children;
}

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              path="/"
              element={
                <Protected>
                  <Layout />
                </Protected>
              }
            >
              <Route index element={<Productos />} />
              <Route path="panel" element={<AdminOnly><Dashboard /></AdminOnly>} />
              <Route path="tpv" element={<POS />} />
              <Route path="gestion" element={<Gestion />} />
              <Route path="productos" element={<Navigate to="/" replace />} />
              <Route path="socios/:id" element={<SocioFicha />} />
              <Route path="usuarios" element={<Usuarios />} />
              <Route path="caja" element={<AdminOnly><Caja /></AdminOnly>} />
              <Route path="historico" element={<AdminOnly><Historico /></AdminOnly>} />
              <Route path="actividad" element={<AdminOnly><Actividad /></AdminOnly>} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
        <Toaster position="top-right" richColors closeButton />
      </AuthProvider>
    </div>
  );
}

export default App;
