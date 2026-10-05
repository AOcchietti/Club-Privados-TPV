import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useAuth } from "@/context/AuthContext";
import { apiError } from "@/lib/api";
import { Citrus, Loader2, MapPin } from "lucide-react";

const line = {
  hidden: { y: "110%" },
  show: (i) => ({ y: "0%", transition: { delay: 0.15 + i * 0.12, duration: 0.7, ease: [0.22, 1, 0.36, 1] } }),
};

export default function Login() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (user && user !== false) {
      navigate("/", { replace: true });
    }
  }, [user, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(apiError(err, "No se pudo iniciar sesión"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-[#FDFBF3]">
      {/* Panel visual */}
      <div className="hidden lg:flex w-[46%] relative overflow-hidden bg-amber-400 flex-col justify-between p-10">
        <div
          className="absolute inset-0 opacity-25 bg-cover bg-center"
          style={{ backgroundImage: "url(https://images.pexels.com/photos/5966647/pexels-photo-5966647.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=900&w=1200)" }}
        />
        <div className="absolute inset-0 bg-gradient-to-t from-amber-500/80 via-transparent to-amber-300/40" />
        <div className="relative flex items-center gap-2.5">
          <div className="w-10 h-10 rounded-2xl bg-slate-950 flex items-center justify-center">
            <Citrus className="w-6 h-6 text-amber-400" />
          </div>
          <span className="font-display font-bold text-slate-950 text-lg">Weed Lemon Social Club</span>
        </div>
        <div className="relative">
          {["El club con", "más limón", "de Sevilla."].map((t, i) => (
            <div key={t} className="overflow-hidden">
              <motion.h1
                custom={i}
                variants={line}
                initial="hidden"
                animate="show"
                className="font-display text-5xl xl:text-6xl font-extrabold text-slate-950 leading-[1.05] tracking-tight"
              >
                {t}
              </motion.h1>
            </div>
          ))}
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.7 }}
            className="mt-5 text-slate-900/80 font-medium flex items-center gap-1.5"
          >
            <MapPin className="w-4 h-4" /> Demetrio de los Ríos, 5 · 41003 Sevilla
          </motion.p>
        </div>
      </div>

      {/* Formulario */}
      <div className="flex-1 flex items-center justify-center p-6">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="w-full max-w-sm"
        >
          <div className="lg:hidden flex items-center gap-2.5 mb-8 justify-center">
            <div className="w-10 h-10 rounded-2xl bg-amber-400 flex items-center justify-center">
              <Citrus className="w-6 h-6 text-slate-950" />
            </div>
            <span className="font-display font-bold text-slate-900 text-lg">Weed Lemon</span>
          </div>
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">Acceso del equipo</h2>
          <p className="text-sm text-slate-500 mt-1.5 mb-8">Sistema de ventas y gestión interna del club.</p>

          <form onSubmit={handleSubmit} className="space-y-4" data-testid="login-form">
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1.5" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                data-testid="login-email-input"
                placeholder="tu@weedlemon.es"
                className="w-full px-4 py-3 rounded-xl border border-slate-300 bg-white text-slate-900 focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-amber-400 transition-shadow"
              />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1.5" htmlFor="password">
                Contraseña
              </label>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                data-testid="login-password-input"
                placeholder="••••••••"
                className="w-full px-4 py-3 rounded-xl border border-slate-300 bg-white text-slate-900 focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-amber-400 transition-shadow"
              />
            </div>
            {error && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-3.5 py-2.5" data-testid="login-error">
                {error}
              </p>
            )}
            <button type="submit" disabled={loading} className="btn-primary w-full py-3" data-testid="login-submit-button">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              Entrar al sistema
            </button>
          </form>
        </motion.div>
      </div>
    </div>
  );
}
