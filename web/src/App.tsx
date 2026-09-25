import {
  Component,
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ErrorInfo,
  type ReactNode,
} from "react";
import {
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useOutletContext,
} from "react-router-dom";
import { AppShell, IconSprite, NAV_PATHS, TopBar } from "./components";
import { useI18n } from "./i18n";
import { fetchAccount, getSnapshot, subscribe } from "./lib/session";
import type { Account } from "./lib/session";
import { fetchRecord } from "./screens/DashboardParts";
import "./App.css";

/* ──────────────────────────────────────────────────────────────────────────
 * Route table
 *
 *   bare   /  /login  /signup            TopBar + screen
 *   app    /live /record /record/sessions
 *          /formats /demo /account       TopBar + AppShell (rail + track) + screen
 *
 * Both branches hang off one pathless <Shell/> so the session fetch, the skip
 * link and the TopBar mount exactly once.  `#main` is supplied by whichever
 * branch owns the content box (BareRoutes here, AppShell on the app side) so
 * the skip link always lands *after* the navigation, never on it.
 * ────────────────────────────────────────────────────────────────────────── */

// Screens are code-split: a visitor on /login never downloads the dashboard.
const Landing = lazy(() =>
  import("./screens/Landing").then((m) => ({ default: m.Landing })),
);
const Auth = lazy(() =>
  import("./screens/Auth").then((m) => ({ default: m.Auth })),
);
const Dashboard = lazy(() =>
  import("./screens/Dashboard").then((m) => ({ default: m.Dashboard })),
);
const AccountScreen = lazy(() =>
  import("./routes/Account").then((m) => ({ default: m.AccountScreen })),
);
const Live = lazy(() =>
  import("./screens/Live").then((m) => ({ default: m.Live })),
);
const Demo = lazy(() =>
  import("./screens/Demo").then((m) => ({ default: m.Demo })),
);
const Sessions = lazy(() =>
  import("./screens/Sessions").then((m) => ({ default: m.Sessions })),
);
const Formats = lazy(() =>
  import("./screens/Formats").then((m) => ({ default: m.Formats })),
);
const Admin = lazy(() =>
  import("./screens/Admin").then((m) => ({ default: m.Admin })),
);
const Pitch = lazy(() =>
  import("./screens/Pitch").then((m) => ({ default: m.Pitch })),
);

// ───────────────────────────────────────────────────────── shell context ──

export interface ShellContext {
  account: Account | null;
  /** True only while the first /api/auth/me for this token is in flight. */
  loading: boolean;
  /** We hold a token the server could not confirm. Not the same as signed out. */
  unreachable: boolean;
  reload: () => void;
}

export function useShell(): ShellContext {
  const ctx = useOutletContext<ShellContext | undefined>();
  if (import.meta.env.DEV && ctx === undefined) {
    throw new Error(
      "useShell() called outside <Shell/>. Check the route nesting.",
    );
  }
  return ctx as ShellContext;
}

const useToken = () => useSyncExternalStore(subscribe, getSnapshot, () => null);

// ─────────────────────────────────────────────────────────────── hooks ──

interface Written {
  silent: number;
  total: number;
}

/**
 * Silent identifiers over total identifiers — the single figure the rail shows.
 * `undefined` until the server has answered and again on any failure; the rail
 * renders nothing for undefined rather than a placeholder or 0/0.
 */
function useWritten(token: string | null): Written | undefined {
  const [figure, setFigure] = useState<Written>();

  useEffect(() => {
    if (token === null) {
      setFigure(undefined);
      return;
    }
    const controller = new AbortController();

    fetchRecord(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        if (!result.ok) return setFigure(undefined);
        const { captures, counters } = result.data;
        setFigure({
          silent: counters?.silent ?? captures.filter((c) => c.silent).length,
          total: counters?.captures ?? captures.length,
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) setFigure(undefined);
      });

    return () => controller.abort();
  }, [token]);

  return figure;
}

/**
 * On every client-side navigation: reset scroll and move focus to the content
 * box. Without this a screen-reader user stays parked on the link they clicked
 * and hears nothing change.
 */
function useRouteFocus() {
  const { pathname } = useLocation();
  const first = useRef(true);

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const main = document.getElementById("main");
    window.scrollTo({ top: 0, behavior: "instant" });
    main?.focus({ preventScroll: true });
  }, [pathname]);
}

// ──────────────────────────────────────────────────────── error boundary ──

interface BoundaryProps {
  fallback: ReactNode;
  children: ReactNode;
}

class RouteBoundary extends Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (import.meta.env.DEV) console.error(error, info.componentStack);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function RouteFallback() {
  const { t } = useI18n();
  return (
    <div className="notice notice--error" role="alert">
      <span>{t("app.routeFailed")}</span>
    </div>
  );
}

function ScreenLoading() {
  return <div className="screen-loading" aria-hidden="true" />;
}

// ─────────────────────────────────────────────────────────── branches ──

function BareRoutes() {
  const context = useShell();
  return (
    <div className="shell__plain" id="main" tabIndex={-1}>
      <Outlet context={context} />
    </div>
  );
}

/**
 * Signed-in branch. The guard lives here as well as inside the screens: one
 * gate at the route is cheaper to verify than five in five screens, and the
 * <Pending> routes have no guard of their own.
 *
 * Only the *absence* of a token routes to /login. `unreachable` means we still
 * hold a token the server could not confirm; screens show an offline notice.
 */
function AppRoutes() {
  const context = useShell();
  const { t } = useI18n();
  const token = useToken();
  const written = useWritten(token);

  if (token === null) return <Navigate to="/login" replace />;

  return (
    <AppShell {...(written ? { written } : {})}>
      <Outlet context={context} />
      {/* The interface speaks three languages, the recogniser listens in one.
          Said once, in the flow, on every signed-in screen. The key keeps its
          `landing.` prefix on purpose so the sentence exists exactly once. */}
      <p className="shell__scope">{t("landing.hero.scope")}</p>
    </AppShell>
  );
}

/**
 * /demo sits in neither branch. It is reachable signed out -- DESIGN-BRIEF
 * 4.5: a judge who arrives with no account must reach the experience in one
 * click -- and keeps the rail when signed in, because a signed-in operator
 * who clicks "Demo" on the rail should not lose the rail. The token on this
 * route is attribution, never access (lib/api.ts, demoReplay).
 */
function DemoEntry() {
  const { t } = useI18n();
  const token = useToken();
  const written = useWritten(token);

  if (token === null) {
    return (
      <div className="shell__plain" id="main" tabIndex={-1}>
        <Demo />
      </div>
    );
  }
  return (
    <AppShell {...(written ? { written } : {})}>
      <Demo />
      <p className="shell__scope">{t("landing.hero.scope")}</p>
    </AppShell>
  );
}

// ─────────────────────────────────────────────────────────────── shell ──

function Shell() {
  const { t } = useI18n();
  const token = useToken();
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(false);
  const [unreachable, setUnreachable] = useState(false);
  const [nonce, setNonce] = useState(0);

  useRouteFocus();

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (token === null) {
      setAccount(null);
      setUnreachable(false);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);

    fetchAccount(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setLoading(false);
        if (result.ok) {
          setAccount(result.data);
          setUnreachable(false);
        } else {
          // A 401 already cleared the token inside request(). Anything else
          // means we still believe we are signed in, we just cannot prove it.
          setAccount(null);
          setUnreachable(
            result.kind === "offline" || result.kind === "timeout",
          );
        }
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setLoading(false);
        setAccount(null);
        setUnreachable(true);
      });

    return () => controller.abort();
  }, [token, nonce]);

  const context = useMemo<ShellContext>(
    () => ({ account, loading, unreachable, reload }),
    [account, loading, unreachable, reload],
  );

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        {t("app.skipToContent")}
      </a>
      <TopBar account={account} />
      {/* No id here — see the route-table note at the top of this file. */}
      <main className="shell__main page">
        <RouteBoundary fallback={<RouteFallback />}>
          <Suspense fallback={<ScreenLoading />}>
            <Outlet context={context} />
          </Suspense>
        </RouteBoundary>
      </main>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────── app ──

export default function App() {
  return (
    <>
      <IconSprite />

      <Routes>
        <Route element={<Shell />}>
          <Route element={<BareRoutes />}>
            <Route index element={<Landing />} />
            <Route path="login" element={<Auth mode="login" />} />
            <Route path="signup" element={<Auth mode="signup" />} />
            {/* Pitch Day 3.0 -- ochiq sahifa, xuddi Landing kabi. */}
            <Route path="pitch" element={<Pitch />} />
          </Route>

          <Route element={<AppRoutes />}>
            <Route path={NAV_PATHS.record} element={<Dashboard />} />
            <Route path={NAV_PATHS.account} element={<AccountScreen />} />
            <Route path={NAV_PATHS.live} element={<Live />} />
            <Route path={NAV_PATHS.sessions} element={<Sessions />} />
            <Route path={NAV_PATHS.formats} element={<Formats />} />
            {/* Operators only; the screen itself sends anyone else to the record. */}
            <Route path={NAV_PATHS.admin} element={<Admin />} />
          </Route>

          {/* Neither branch: see DemoEntry. */}
          <Route path={NAV_PATHS.demo} element={<DemoEntry />} />

          {/* Outside both branches: an unmatched URL has no presentation to
              choose, and mounting the rail around a redirect would fire the
              record fetch for one frame on the way out. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </>
  );
}
