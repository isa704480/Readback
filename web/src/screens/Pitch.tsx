import type { ReactNode } from 'react';
import { ButtonLink, NAV_PATHS } from '../components';
import { useI18n } from '../i18n';
import './Pitch.css';

/* Pitch Day 3.0 (submission) and LabLab AssemblyAI hackathon pitch. Every
 * string routes through the i18n catalog so an English-speaking judge and an
 * Uzbek Pitch Day judge see the same page in their own language.
 *
 * Every figure here has a source in docs/. No invented data. When the video
 * lands, set DEMO_VIDEO_URL; when the repo is public, set GITHUB_URL. */

const DEMO_VIDEO_URL: string | null = null;
const GITHUB_URL: string = 'https://github.com/isa704480/Readback';

function Section({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="pitch__section">
      <p className="pitch__eyebrow">{eyebrow}</p>
      <h2 className="pitch__h2">{title}</h2>
      <div className="pitch__body">{children}</div>
    </section>
  );
}

function Stage({
  n,
  label,
  when,
  state,
  children,
}: {
  n: string;
  label: string;
  when: string;
  state: 'done' | 'now' | 'next';
  children: ReactNode;
}) {
  return (
    <li className={`stage stage--${state}`}>
      <span className="stage__mark" aria-hidden="true">
        {state === 'done' ? '✓' : state === 'now' ? '●' : n}
      </span>
      <div>
        <h3 className="stage__head">
          {label}
          <span className="stage__when">{when}</span>
        </h3>
        <p className="stage__body">{children}</p>
      </div>
    </li>
  );
}

export function Pitch() {
  const { t } = useI18n();
  return (
    <article className="pitch">
      <header className="pitch__hero">
        <p className="pitch__kicker">{t('pitch.kicker')}</p>
        <h1 className="pitch__title">
          {t('pitch.title.before')}
          <em>{t('pitch.title.em')}</em>
          {t('pitch.title.after')}
        </h1>
        <p className="pitch__lede">{t('pitch.lede')}</p>
        <div className="pitch__cta">
          <ButtonLink to={NAV_PATHS.demo} variant="primary">
            {t('pitch.cta.tryDemo')}
          </ButtonLink>
          <ButtonLink to="/" variant="secondary">
            {t('pitch.cta.product')}
          </ButtonLink>
        </div>
      </header>

      <Section eyebrow="01" title={t('pitch.problem.title')}>
        <div className="grid-2">
          <div>
            <h3 className="pitch__h3">{t('pitch.problem.h3')}</h3>
            <p>{t('pitch.problem.p1')}</p>
            <p>{t('pitch.problem.p2')}</p>
          </div>
          <div>
            <h3 className="pitch__h3">{t('pitch.solution.h3')}</h3>
            <p>{t('pitch.solution.p1')}</p>
            <p>{t('pitch.solution.p2')}</p>
          </div>
        </div>
      </Section>

      <Section eyebrow="02" title={t('pitch.team.title')}>
        <div className="team">
          <div className="team__card">
            <p className="team__name">Islombek Fayzullaev</p>
            <p className="team__role">{t('pitch.team.role')}</p>
            <ul className="team__list">
              <li>{t('pitch.team.list.python')}</li>
              <li>{t('pitch.team.list.typescript')}</li>
              <li>{t('pitch.team.list.voice')}</li>
              <li>{t('pitch.team.list.visual')}</li>
              <li>{t('pitch.team.list.infra')}</li>
            </ul>
            <p className="team__contact">
              <a href="mailto:info@fayzinc.com">info@fayzinc.com</a>
              {' · '}
              <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                GitHub
              </a>
            </p>
          </div>
          <p className="team__note">{t('pitch.team.note')}</p>
        </div>
      </Section>

      <Section eyebrow="03" title={t('pitch.reasons.title')}>
        <ul className="reasons">
          <li>
            <h3 className="pitch__h3">{t('pitch.reasons.constraint.h3')}</h3>
            <p>{t('pitch.reasons.constraint.p')}</p>
          </li>
          <li>
            <h3 className="pitch__h3">{t('pitch.reasons.engineering.h3')}</h3>
            <p>{t('pitch.reasons.engineering.p')}</p>
          </li>
          <li>
            <h3 className="pitch__h3">{t('pitch.reasons.market.h3')}</h3>
            <p>{t('pitch.reasons.market.p')}</p>
          </li>
        </ul>
      </Section>

      <Section eyebrow="04" title={t('pitch.roadmap.title')}>
        <ol className="stages">
          <Stage
            n="1"
            label={t('pitch.roadmap.idea.label')}
            when={t('pitch.roadmap.idea.when')}
            state="done"
          >
            {t('pitch.roadmap.idea.body')}
          </Stage>
          <Stage
            n="2"
            label={t('pitch.roadmap.prototype.label')}
            when={t('pitch.roadmap.prototype.when')}
            state="done"
          >
            {t('pitch.roadmap.prototype.body')}
          </Stage>
          <Stage
            n="3"
            label={t('pitch.roadmap.mvp.label')}
            when={t('pitch.roadmap.mvp.when')}
            state="now"
          >
            {t('pitch.roadmap.mvp.body')}
          </Stage>
          <Stage
            n="4"
            label={t('pitch.roadmap.launch.label')}
            when={t('pitch.roadmap.launch.when')}
            state="next"
          >
            {t('pitch.roadmap.launch.body')}
          </Stage>
        </ol>
      </Section>

      <Section eyebrow="05" title={t('pitch.plan.title')}>
        <div className="plan">
          <div>
            <h3 className="pitch__h3">{t('pitch.plan.stack.h3')}</h3>
            <ul>
              <li>{t('pitch.plan.stack.voice')}</li>
              <li>{t('pitch.plan.stack.server')}</li>
              <li>{t('pitch.plan.stack.web')}</li>
              <li>{t('pitch.plan.stack.security')}</li>
            </ul>
          </div>
          <div>
            <h3 className="pitch__h3">{t('pitch.plan.stages.h3')}</h3>
            <ol>
              <li>{t('pitch.plan.stages.sept')}</li>
              <li>{t('pitch.plan.stages.oct')}</li>
              <li>{t('pitch.plan.stages.novDec')}</li>
              <li>{t('pitch.plan.stages.jan2027')}</li>
            </ol>
          </div>
          <div>
            <h3 className="pitch__h3">{t('pitch.plan.ai.h3')}</h3>
            <ul>
              <li>{t('pitch.plan.ai.assemblyai')}</li>
              <li>{t('pitch.plan.ai.gateway')}</li>
              <li>{t('pitch.plan.ai.claudeCode')}</li>
              <li>{t('pitch.plan.ai.solver')}</li>
            </ul>
          </div>
        </div>
      </Section>

      <Section eyebrow="06" title={t('pitch.demo.title')}>
        <div className="demo-block">
          {DEMO_VIDEO_URL ? (
            <div className="demo-block__video">
              <iframe
                src={DEMO_VIDEO_URL}
                title={t('pitch.demo.videoTitle')}
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
              />
            </div>
          ) : (
            <div className="demo-block__placeholder">
              <p>{t('pitch.demo.placeholder')}</p>
            </div>
          )}

          <div>
            <h3 className="pitch__h3">{t('pitch.demo.about.h3')}</h3>
            <p>{t('pitch.demo.about.p')}</p>

            <h3 className="pitch__h3">{t('pitch.demo.prototype.h3')}</h3>
            <ul className="demo-block__links">
              <li>
                <span>{t('pitch.demo.prototype.demoLine')}</span>
                <ButtonLink to={NAV_PATHS.demo} variant="secondary">
                  {t('pitch.demo.prototype.open')}
                </ButtonLink>
              </li>
              <li>
                <span>{t('pitch.demo.prototype.liveLine')}</span>
                <ButtonLink to={NAV_PATHS.live} variant="secondary">
                  {t('pitch.demo.prototype.open')}
                </ButtonLink>
              </li>
              <li>
                <span>{t('pitch.demo.prototype.formatsLine')}</span>
                <ButtonLink to={NAV_PATHS.formats} variant="secondary">
                  {t('pitch.demo.prototype.open')}
                </ButtonLink>
              </li>
            </ul>

            <h3 className="pitch__h3">{t('pitch.demo.source.h3')}</h3>
            <p>
              {t('pitch.demo.source.before')}
              <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                {t('pitch.demo.source.link')}
              </a>
              {t('pitch.demo.source.after')}
            </p>
          </div>
        </div>
      </Section>

      <footer className="pitch__footer">
        <p>
          {t('pitch.footer.contact')}{' '}
          <a href="mailto:info@fayzinc.com">info@fayzinc.com</a>
        </p>
      </footer>
    </article>
  );
}
