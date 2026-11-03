import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import api, { apiError } from "@/lib/api";
import { Citrus, Loader2, MailCheck, KeyRound, CheckCircle2, ArrowLeft } from "lucide-react";

const INPUT =
  "w-full px-4 py-3 rounded-xl border border-slate-300 bg-white text-slate-900 focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-amber-400 transition-shadow";
const LABEL = "text-xs font-semibold uppercase tracking-wider text-slate-500 block mb-1.5";

function Shell({ title, subtitle, children, testid }) {
  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-[#FDFBF3]" data-testid={testid}>
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="w-full max-w-sm">
        <div className="flex items-center gap-2.5 mb-8 justify-center">
          <div className="w-10 h-10 rounded-2xl bg-amber-400 flex items-center justify-center">
            <Citrus className="w-6 h-6 text-slate-950" />
          </div>
          <span className="font-display font-bold text-slate-900 text-lg">Weed Lemon</span>
        </div>
        <h2 className="font-display text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">{title}</h2>
        <p className="text-sm text-slate-500 mt-1.5 mb-7">{subtitle}</p>
        {children}
        <Link to="/login" className="mt-6 inline-flex items-center gap-1.5 text-sm font-semibold text-slate-500 hover:text-slate-900" data-testid="back-to-login">
          <ArrowLeft className="w-4 h-4" /> Volver al acceso
        </Link>
      </motion.div>
    </div>
  );
}

/* Paso 1: pedir el enlace por email */
export function RecuperarPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.post("/auth/forgot-password", { email });
      setSent(res.data.message);
    } catch (err) {
      setError(apiError(err, "No se pudo enviar el enlace"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Shell title="¿Has olvidado tu contraseña?" subtitle="Escribe el email de tu cuenta del equipo y te enviaremos un enlace para elegir una nueva." testid="forgot-page">
      {sent ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 flex gap-3" data-testid="forgot-sent">
          <MailCheck className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
          <p className="text-sm text-emerald-900">{sent}</p>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className={LABEL} htmlFor="forgot-email">Email</label>
            <input id="forgot-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="tu@weedlemon.es" autoComplete="email" data-testid="forgot-email-input" className={INPUT} />
          </div>
          {error && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-3.5 py-2.5">{error}</p>}
          <button type="submit" disabled={loading} className="btn-primary w-full py-3" data-testid="forgot-submit-button">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Enviarme el enlace
          </button>
        </form>
      )}
    </Shell>
  );
}

/* Paso 2: elegir la contraseña nueva con el enlace del correo */
export function RestablecerPassword() {
  const [params] = useSearchParams();
  const [token] = useState(() => params.get("token") || "");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  // El token no se queda en la barra de direcciones ni en el historial del navegador
  useEffect(() => {
    try {
      if (params.get("token")) window.history.replaceState(null, "", "/restablecer");
    } catch {
      /* si el navegador no deja reescribir la dirección, la página sigue funcionando */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) return setError("La contraseña debe tener al menos 8 caracteres");
    if (password !== repeat) return setError("Las dos contraseñas no coinciden");
    setLoading(true);
    try {
      await api.post("/auth/reset-password", { token, password });
      setDone(true);
    } catch (err) {
      setError(apiError(err, "No se pudo cambiar la contraseña"));
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <Shell title="Enlace incompleto" subtitle="Abre el enlace tal cual llegó en el correo, o pide uno nuevo." testid="reset-page">
        <Link to="/recuperar" className="btn-primary w-full py-3">Pedir un enlace nuevo</Link>
      </Shell>
    );
  }

  return (
    <Shell title="Elige una contraseña nueva" subtitle="Mínimo 8 caracteres. Al guardarla se cerrarán las sesiones que tengas abiertas." testid="reset-page">
      {done ? (
        <div className="space-y-4" data-testid="reset-done">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 flex gap-3">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
            <p className="text-sm text-emerald-900">Contraseña cambiada. Ya puedes entrar con la nueva.</p>
          </div>
          <Link to="/login" className="btn-primary w-full py-3" data-testid="reset-go-login">Ir al acceso</Link>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className={LABEL} htmlFor="reset-password">Contraseña nueva</label>
            <input id="reset-password" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password" data-testid="reset-password-input" className={INPUT} />
          </div>
          <div>
            <label className={LABEL} htmlFor="reset-repeat">Repite la contraseña</label>
            <input id="reset-repeat" type="password" required value={repeat} onChange={(e) => setRepeat(e.target.value)}
              autoComplete="new-password" data-testid="reset-password-repeat" className={INPUT} />
          </div>
          {error && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-3.5 py-2.5" data-testid="reset-error">
              {error}
              {/caducado|no es válido/i.test(error) && (
                <Link to="/recuperar" className="block mt-1.5 font-semibold underline">Pedir un enlace nuevo</Link>
              )}
            </div>
          )}
          <button type="submit" disabled={loading} className="btn-primary w-full py-3" data-testid="reset-submit-button">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <KeyRound className="w-4 h-4" />}
            Guardar contraseña
          </button>
        </form>
      )}
    </Shell>
  );
}
