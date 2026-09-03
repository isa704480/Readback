import { useEffect, useId, useState } from 'react';
import { Button, Icon } from '../components';
import { request } from '../lib/session';
import { useI18n } from '../i18n';
import type { ConsentRecord } from '../lib/useLiveSession';
import './Consent.css';

/* THE CONSENT STEP. ARCHITECTURE 3.12, made into a screen.
 *
 * Three things have to be true before /api/session/start is called with
 * consent.accepted = true, and this component is where all three are made
 * true rather than assumed:
 *
 *   1. The person has SEEN the disclosure. It is on the page, in their
 *      interface language, above the controls -- not behind a link, not in a
 *      tooltip, not a one-line summary of a policy that lives elsewhere.
 *   2. The person has ACCEPTED it, by a control that starts unticked. A
 *      pre-ticked box is a claim the person never made.
 *   3. The OTHER PARTY has been told. All-party consent is not a setting and
 *      not a jurisdiction, so the second box is required too, and there is no
 *      variant of this screen without it.
 *
 * The version string comes from /health, because the words on this page
 * change and "did this session consent" is a question about which words. If
 * the server cannot be reached the version is unknown, and a session cannot
 * start -- the button stays disabled and the reason is on the page.
 *
 * getUserMedia is NOT called here. It is not called anywhere until the server
 * has accepted this record; see useLiveSession.start(). Browser permission is
 * not consent, and this component never gets the chance to confuse the two. */

interface HealthShape {
  consent_version?: unknown;
  live_capture?: unknown;
}

type Health =
  | { status: 'loading' }
  | { status: 'unreachable' }
  | { status: 'ready'; version: string; liveCapture: boolean };

export interface ConsentProps {
  onStart: (consent: ConsentRecord) => void;
  /** The session is being opened; the controls freeze. */
  busy: boolean;
  /** The cap, if known, for the disclosure's fourth point. */
  capSeconds: number | null;
}

export function Consent({ onStart, busy, capSeconds }: ConsentProps) {
  const { t, n } = useI18n();
  const id = useId();
  const [health, setHealth] = useState<Health>({ status: 'loading' });
  const [accepted, setAccepted] = useState(false);
  const [played, setPlayed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    request<HealthShape>('/health', { signal: controller.signal }).then((result) => {
      if (controller.signal.aborted) return;
      if (!result.ok || typeof result.data?.consent_version !== 'string') {
        setHealth({ status: 'unreachable' });
        return;
      }
      setHealth({
        status: 'ready',
        version: result.data.consent_version,
        liveCapture: result.data.live_capture === true,
      });
    });
    return () => controller.abort();
  }, []);

  const ready = health.status === 'ready' && health.liveCapture;
  const canStart = ready && accepted && played && !busy;

  return (
    <section className="consent stack" aria-labelledby={`${id}-title`}>
      <p className="consent__eyebrow mono">
        <Icon name="shield" size={16} />
        <span>{t('consent.eyebrow')}</span>
      </p>
      <h1 className="consent__title" id={`${id}-title`}>
        {t('consent.title')}
      </h1>
      <p className="consent__lede measure">{t('consent.lede')}</p>

      {/* The disclosure. One panel, hairline-separated points, no tint. */}
      <div className="consent__panel card">
        <h2 className="consent__h2">{t('consent.what.title')}</h2>
        <ol className="consent__points">
          <li>{t('consent.what.1')}</li>
          <li>{t('consent.what.2')}</li>
          <li>{t('consent.what.3')}</li>
          <li>{t('consent.what.4', { seconds: n(capSeconds ?? 150) })}</li>
        </ol>
        <p className="consent__allParty">
          <Icon name="alert" size={16} />
          <span>{t('consent.allParty')}</span>
        </p>
        <p className="consent__version mono">
          <span>{t('consent.version')}</span>
          {/* The version is an identifier the server owns: not translated,
              not reshaped. */}
          <span translate="no" dir="ltr">
            {health.status === 'ready' ? health.version : health.status === 'loading' ? '…' : '—'}
          </span>
        </p>
      </div>

      {health.status === 'loading' ? (
        <p className="consent__note" role="status">
          {t('consent.version.loading')}
        </p>
      ) : null}
      {health.status === 'unreachable' ? (
        <div className="notice notice--error" role="alert">
          <Icon name="alert" size={16} />
          <span>{t('consent.version.unavailable')}</span>
        </div>
      ) : null}
      {health.status === 'ready' && !health.liveCapture ? (
        <div className="notice" role="status">
          <Icon name="info" size={16} />
          <span>{t('consent.replayOnly')}</span>
        </div>
      ) : null}

      {/* The two boxes. Native inputs, so the keyboard and the screen reader
          get the real control; styled to a 24px box inside a 44px row. */}
      <div className="consent__controls card">
        <label className="consent__check">
          <input
            type="checkbox"
            checked={accepted}
            disabled={!ready || busy}
            onChange={(event) => setAccepted(event.target.checked)}
          />
          <span>{t('consent.accept.label')}</span>
        </label>
        <label className="consent__check">
          <input
            type="checkbox"
            checked={played}
            disabled={!ready || busy}
            onChange={(event) => setPlayed(event.target.checked)}
          />
          <span>{t('consent.played.label')}</span>
        </label>

        <div className="consent__go">
          <Button
            variant="primary"
            disabled={!canStart}
            busy={busy}
            busyLabel={t('consent.starting')}
            onClick={() => {
              if (health.status !== 'ready' || !canStart) return;
              onStart({ version: health.version, disclosurePlayed: played });
            }}
          >
            {t('consent.start')}
          </Button>
          <p className="consent__micNote">{t('consent.mic.note')}</p>
        </div>
      </div>
    </section>
  );
}
