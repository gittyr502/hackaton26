import { Link, Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";
import { LANGS, useI18n, type Lang, type MessageKey } from "@/i18n";
import { homeFor, useAuth } from "@/auth/AuthProvider";
import type { Role } from "@/lib/api";

const LOGO =
  "https://lh3.googleusercontent.com/aida/AEtjO1WiJEzpWA1TP0GDTUFKQHPG0O4hev9JTzJ_G9HGGFqnwqOZH7Yep-ipLnXAFNp9V--jcS-dZ4AdUo7Md-NjMjxoL5yV57306FjzYy6er5RgduB2B-tH6jRYLcduCqiEOCjGeo4NDutnIgCDC9ozJcVKSb0jvhDugNUsLvO8q9C396nsHX17OmDtfzDL328Q2IY2eKNnpYRSTlIGGxTshGMZO0g2YoO5_QItJBFA5GwyqbF2v3GUgWfKFKg";

/** The personal-area links of each role, shown outside the batch screens. */
const ROLE_LINKS: Record<Role, { to: string; label: MessageKey }[]> = {
  intake: [
    { to: "/me", label: "nav.myQueue" },
    { to: "/", label: "nav.newUpload" },
  ],
  approver: [{ to: "/me", label: "nav.approvals" }],
  lab_manager: [
    { to: "/dashboard", label: "nav.dashboard" },
    { to: "/", label: "nav.newUpload" },
  ],
};

const initials = (name: string) =>
  name
    .replace(/["״׳']/g, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(-2)
    .map((w) => w[0])
    .join("");

const ACTIVE = "px-4 py-1.5 rounded-full transition-all bg-white/25 text-on-primary font-bold shadow-sm";
const INACTIVE =
  "text-primary-fixed-dim hover:text-on-primary hover:bg-white/10 px-4 py-1.5 rounded-full text-label-md font-label-md transition-all";

function LanguageSwitcher() {
  const { lang, setLang, t } = useI18n();
  return (
    <label className="relative flex items-center gap-1 bg-white/10 hover:bg-white/20 rounded-full ps-2.5 pe-2 h-9 text-on-primary transition-colors cursor-pointer">
      <span className="material-symbols-outlined text-[18px] text-primary-fixed" aria-hidden>
        translate
      </span>
      <select
        aria-label={t("lang.label")}
        title={t("lang.label")}
        value={lang}
        onChange={(e) => setLang(e.target.value as Lang)}
        className="appearance-none bg-transparent font-label-md text-label-md font-bold outline-none cursor-pointer pe-4"
      >
        {LANGS.map((l) => (
          <option key={l.code} value={l.code} lang={l.code} className="text-on-surface">
            {l.name}
          </option>
        ))}
      </select>
      <span className="material-symbols-outlined text-[16px] absolute end-2 pointer-events-none" aria-hidden>
        expand_more
      </span>
    </label>
  );
}

export function Layout() {
  const id = useMatch("/batches/:id/*")?.params.id;
  const { pathname } = useLocation();
  const { t } = useI18n();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const role = user?.role ?? "intake";
  const step = pathname === "/" ? 0 : pathname.endsWith("/processing") ? 1 : pathname.endsWith("/export") ? 3 : 2;
  const steps = [
    { to: role === "approver" ? "" : "/", label: t("nav.upload") },
    { to: id ? `/batches/${id}/processing` : "", label: t("nav.processing") },
    { to: id ? `/batches/${id}` : "", label: t("nav.review") },
    { to: id && role === "lab_manager" ? `/batches/${id}/export` : "", label: t("nav.export") },
  ];
  const inBatchFlow = pathname === "/" || !!id;
  const roleLinks = ROLE_LINKS[role];

  return (
    <>
      <header className="fixed top-0 w-full z-50 shadow-[0_10px_25px_-5px_rgba(43,41,109,0.06)] bg-gradient-to-br from-[#2BB99B] to-[#2B296D]">
        <div className="h-20 w-full px-margin flex items-center justify-between">
          <div className="flex items-center gap-space-md">
            <img alt="MedScan AI" className="h-8 w-auto object-contain" src={LOGO} />
            <div className="flex flex-col">
              <div className="flex items-center gap-space-xs">
                <span className="text-on-primary font-headline-md text-headline-md tracking-tight font-bold">MedScan AI</span>
                <span className="bg-white/20 text-on-primary px-2 py-0.5 rounded-full text-label-sm font-label-sm">v2.4</span>
              </div>
              <span className="text-primary-fixed font-body-sm text-body-sm opacity-90">{t("header.tagline")}</span>
            </div>
          </div>
          <nav className="hidden xl:flex items-center bg-black/15 rounded-full p-1.5 gap-1">
            {!inBatchFlow &&
              roleLinks.map((l) => (
                <Link key={l.to} to={l.to} aria-current={pathname === l.to ? "page" : undefined}
                      className={pathname === l.to ? ACTIVE : INACTIVE}>
                  {t(l.label)}
                </Link>
              ))}
            {inBatchFlow && (
              <Link to={homeFor(role)} className={INACTIVE} title={t(roleLinks[0].label)}>
                <span className="material-symbols-outlined text-[18px] align-middle">home</span>
              </Link>
            )}
            {inBatchFlow && steps.map((s, i) => (
              <Link
                key={i}
                to={s.to || "#"}
                onClick={s.to ? undefined : (e) => e.preventDefault()}
                aria-current={i === step ? "page" : undefined}
                className={i === step ? ACTIVE : INACTIVE}
              >
                {s.label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-space-md">
            <div className="hidden md:flex items-center gap-space-xs bg-white/10 backdrop-blur-md px-3 py-1.5 rounded-full text-on-primary">
              <span className="material-symbols-outlined text-[16px] text-primary-fixed">verified_user</span>
              <span className="font-label-sm text-label-sm tracking-wide">{t("header.secure")}</span>
            </div>
            <LanguageSwitcher />
            <button
              className="flex items-center justify-center w-9 h-9 rounded-full bg-white/10 hover:bg-white/20 text-on-primary transition-colors"
              type="button"
              aria-label={t("header.help")}
              title={t("header.help")}
            >
              <span className="material-symbols-outlined text-[20px]">help_outline</span>
            </button>
            {user && (
              <div className="flex items-center gap-space-sm pe-2">
                <div className="text-end hidden sm:flex flex-col">
                  <span className="text-on-primary font-label-md text-label-md">{user.display_name || user.username}</span>
                  <span className="text-primary-fixed-dim font-body-sm text-body-sm">{t(`role.${user.role}`)}</span>
                </div>
                <span
                  aria-label={t("header.profile")}
                  className="w-8 h-8 rounded-full bg-white/25 text-on-primary flex items-center justify-center font-label-md text-label-md font-bold"
                >
                  {initials(user.display_name || user.username)}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    logout();
                    navigate("/login", { replace: true });
                  }}
                  className="flex items-center justify-center w-9 h-9 rounded-full bg-white/10 hover:bg-white/20 text-on-primary transition-colors"
                  aria-label={t("header.logout")}
                  title={t("header.logout")}
                >
                  <span className="material-symbols-outlined text-[20px]">logout</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </header>
      <main className="w-full pt-20 bg-surface min-h-[calc(100vh-80px)]">
        <div className="flex flex-col w-full">
          <Outlet />
        </div>
      </main>
      <footer className="w-full bg-surface-container-low shadow-[0_1px_8px_rgba(0,0,0,0.04)] py-space-md">
        <div className="w-full px-margin flex flex-col md:flex-row items-center justify-between gap-space-sm text-on-surface-variant font-body-sm text-body-sm">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-primary text-[18px]">lock</span>
            <span>{t("footer.encrypted")}</span>
          </div>
          <div className="flex items-center gap-space-lg">
            <a className="hover:text-primary transition-colors" href="#">
              {t("footer.privacy")}
            </a>
            <a className="hover:text-primary transition-colors" href="#">
              {t("footer.support")}
            </a>
            <span className="font-data-mono-sm text-data-mono-sm" dir="ltr">
              © 2025 MedScan AI Ltd. All rights reserved.
            </span>
          </div>
        </div>
      </footer>
    </>
  );
}
