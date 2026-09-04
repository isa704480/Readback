import { useCallback, useState } from 'react';
import { Button, Icon, Rack } from '../components';
import type { RackRow } from '../components';
import { useI18n } from '../i18n';
import type { TranslationKey } from '../i18n';
import { outcomeOf, replayAsRecord, replayFixture, slotsFor } from './DashboardParts';
import type { ReplayCapture } from './DashboardParts';
import './Demo.css';

/* The screen the rail's "Demo" item promised: pick a fixture, run it, see
 * what the pipeline wrote down.
 *
 * NOTHING HERE IS TYPED IN. Every rack on this screen is the answer to a
 * POST /api/demo/replay, which pushes the fixture through the same
 * runner.run_session a live call goes through -- tape, detector, normaliser,
 * solver, decider. The screen never knows the right answer; it shows what
 * came back, and the fixture copy describes the INPUT, not the outcome. If
 * the pipeline gets one wrong, this screen says so, because it cannot say
 * anything else.
 *
 * Two groups, and the second is the one that matters more. Four fixtures
 * contain a container number. Four contain no identifier at all -- a
 * conversation, two dates, a meter reading, a phone number -- and the right
 * answer for those is silence. A false capture on one of them is shown
 * rather than hidden; the whole product is the claim that it does not happen.
 *
 * Reachable signed out (App.tsx: DemoEntry). DESIGN-BRIEF 4.5: a judge who
 * arrives with no account must reach the experience in one click. */

type RunState =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'ok'; captures: ReplayCapture[] }
  | { status: 'failed' };

interface Fixture {
  /** The file stem under tests/fixtures/, which is what the API accepts. */
  name: string;
  title: TranslationKey;
  body: TranslationKey;
}

/* `as const satisfies`, never an annotation -- see Pending.tsx for why. */
const CAPTURES = [
  { name: 'iso_clean_single_turn', title: 'demo.fx.clean.title', body: 'demo.fx.clean.body' },
  { name: 'iso_straddle_three_turns', title: 'demo.fx.straddle.title', body: 'demo.fx.straddle.body' },
  { name: 'iso_visible_substitution', title: 'demo.fx.visible.title', body: 'demo.fx.visible.body' },
  { name: 'iso_blind_substitution', title: 'demo.fx.blind.title', body: 'demo.fx.blind.body' },
] as const satisfies readonly Fixture[];

const REFUSALS = [
  { name: 'conversation_no_identifier', title: 'demo.fx.conversation.title', body: 'demo.fx.conversation.body' },
  { name: 'date_range_welded', title: 'demo.fx.dates.title', body: 'demo.fx.dates.body' },
  { name: 'meter_reading_sixteen_digits', title: 'demo.fx.meter.title', body: 'demo.fx.meter.body' },
  { name: 'phone_number_in_conversation', title: 'demo.fx.phone.title', body: 'demo.fx.phone.body' },
] as const satisfies readonly Fixture[];

function rowsOf(name: string, captures: readonly ReplayCapture[]): RackRow[] {
  return captures.map((capture, i) => {
    const asRecord = replayAsRecord(capture, `${name}-${i}`);
    return {
      id: asRecord.id,
      format: capture.format,
      state: outcomeOf(asRecord),
      slots: slotsFor(asRecord),
      questions: capture.questions,
    };
  });
}

function FixtureRow({
  fixture,
  run,
  onRun,
  expectCapture,
}: {
  fixture: Fixture;
  run: RunState;
  onRun: (name: string) => void;
  expectCapture: boolean;
}) {
  const { t } = useI18n();
  const rows = run.status === 'ok' ? rowsOf(fixture.name, run.captures) : [];

  return (
    <li className="demo__row">
      <div className="demo__what">
        <p className="demo__name mono">{fixture.name}</p>
        <h3 className="demo__fixture">{t(fixture.title)}</h3>
        <p className="demo__body measure">{t(fixture.body)}</p>
      </div>

      <div className="demo__actions">
        <Button
          onClick={() => onRun(fixture.name)}
          busy={run.status === 'running'}
          busyLabel={t('demo.running')}
          variant={run.status === 'ok' ? 'secondary' : 'primary'}
        >
          {run.status === 'ok' ? t('demo.runAgain') : t('demo.run')}
        </Button>
      </div>

      {run.status === 'failed' ? (
        <div className="demo__failed" role="status">
          <Icon name="alert" size={18} />
          <span>{t('demo.failed')}</span>
        </div>
      ) : run.status === 'ok' && rows.length === 0 ? (
        <p className="demo__result" role="status">
          {expectCapture ? t('demo.nothing') : t('demo.nothingRight')}
        </p>
      ) : run.status === 'ok' ? (
        <div className="demo__result stack">
          {!expectCapture && (
            <p className="demo__unexpected" role="status">
              <Icon name="alert" size={16} />
              <span>{t('demo.unexpected')}</span>
            </p>
          )}
          <Rack rows={rows} title={t('demo.rackTitle')} legend />
        </div>
      ) : null}
    </li>
  );
}

function Group({
  heading,
  fixtures,
  runs,
  onRun,
  expectCapture,
}: {
  heading: string;
  fixtures: readonly Fixture[];
  runs: Readonly<Record<string, RunState>>;
  onRun: (name: string) => void;
  expectCapture: boolean;
}) {
  return (
    <section className="demo__group stack">
      <h2 className="demo__heading">{heading}</h2>
      <ul className="demo__list">
        {fixtures.map((fixture) => (
          <FixtureRow
            key={fixture.name}
            fixture={fixture}
            run={runs[fixture.name] ?? { status: 'idle' }}
            onRun={onRun}
            expectCapture={expectCapture}
          />
        ))}
      </ul>
    </section>
  );
}

export function Demo() {
  const { t } = useI18n();
  const [runs, setRuns] = useState<Record<string, RunState>>({});

  const run = useCallback((name: string) => {
    setRuns((current) => ({ ...current, [name]: { status: 'running' } }));
    void replayFixture(name).then((result) => {
      setRuns((current) => ({
        ...current,
        [name]: result.ok ? { status: 'ok', captures: result.data } : { status: 'failed' },
      }));
    });
  }, []);

  return (
    <section className="demo stack">
      {/* Non-dismissible, and the same words the record uses: anything
          simulated for a demo says so, on screen. */}
      <p className="demo__stamp">
        <Icon name="alert" size={16} />
        <span>{t('record.empty.chip')}</span>
      </p>

      <h1 className="demo__title">{t('demo.title')}</h1>
      <p className="demo__intro measure">{t('demo.intro')}</p>

      <Group heading={t('demo.group.captures')} fixtures={CAPTURES} runs={runs} onRun={run} expectCapture />
      <Group heading={t('demo.group.refusals')} fixtures={REFUSALS} runs={runs} onRun={run} expectCapture={false} />
    </section>
  );
}
