/* The four primitives the account screen needs and nothing else has asked for
 * yet: a switch, a skeleton, a proportion bar, and the two small marks that
 * carry state and provenance.
 *
 * They live beside the screen rather than in src/components because none of
 * them has a second caller. Promoting one to the shared barrel is a decision for
 * whoever finds the second use, not for the first.
 */

import type { CSSProperties, ReactNode } from 'react';
import { Icon } from '../components';
import { CAPTURE_STATES } from '../lib/api';
import type { CaptureState } from '../lib/api';
import { useI18n } from '../i18n';
import './Account.css';

// ---------------------------------------------------------------- switch --

export interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** The accessible name of the control. The visible word carries the state. */
  label: string;
  disabled?: boolean;
}

/* The track is --text when on, not the accent.
 *
 * The system's default for a toggle-on fill is the view's one accent. In this
 * product the accent means "this state wants a human", and on this screen it is
 * already spent on the two consent decisions further down; a format being
 * switched on is not asking anybody anything. --text means settled, and a
 * format you have switched on is a settled fact about your configuration.
 *
 * The word On/Off ships alongside because the on and off tracks differ by
 * luminance alone, and a luminance difference is not a label. */
export function Toggle({ checked, onChange, label, disabled = false }: ToggleProps) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className="switch"
      onClick={() => onChange(!checked)}
    >
      <span className="switch__track" aria-hidden="true">
        <span className="switch__knob" />
      </span>
      <span className="switch__word">{t(checked ? 'parts.toggle.on' : 'parts.toggle.off')}</span>
    </button>
  );
}

// -------------------------------------------------------------- skeleton --

export interface SkeletonProps {
  width?: string;
  height?: number;
  className?: string;
}

/** A block where content will be. Never a spinner: a spinner says "waiting",
 *  a skeleton says "waiting, and here is the shape of what arrives". */
export function Skeleton({ width = '100%', height = 16, className }: SkeletonProps) {
  const style: CSSProperties = { width, height };
  return (
    <span className={['skel', className].filter(Boolean).join(' ')} style={style} aria-hidden="true" />
  );
}

/** Wraps a run of skeletons so assistive tech is told once what is loading,
 *  rather than reading out a screenful of empty boxes. */
export function Loading({ what, children }: { what: string; children: ReactNode }) {
  return (
    <div aria-busy="true" aria-live="polite" aria-label={what}>
      {children}
    </div>
  );
}

// ------------------------------------------------------------------- bar --

export interface BarProps {
  /** 0..1, or null when the server has reported no allowance to divide by. */
  fraction: number | null;
  /** The capture state this reading is in, or null when there is none.
   *
   *  A state, not a colour token. The fill's tone is decided once, in
   *  Account.css, from the state vocabulary; nothing about a colour crosses
   *  this boundary, so retiring or re-pointing a token never has to be chased
   *  through the screens. */
  state: CaptureState | null;
  /** Announced instead of a percentage. */
  valueText: string;
  label: string;
}

/* The fill is a scaleX transform rather than a width.
 *
 * Two reasons, and the second is the real one. Transform and opacity are the
 * only two properties in the motion budget, and animating width would relayout
 * the row on every frame. But also: a bar whose width is 0 has no box, so a
 * zero-length reading and a missing reading render identically. A scaled fill
 * keeps its box either way, which is what lets the no-reading track below say
 * something instead of disappearing. */
export function Bar({ fraction, state, valueText, label }: BarProps) {
  const { t } = useI18n();
  if (fraction === null) {
    return (
      <div
        className="bar bar--noread"
        role="progressbar"
        aria-label={label}
        aria-valuetext={valueText}
      >
        <span className="bar__noread mono">{t('parts.bar.noReading')}</span>
      </div>
    );
  }

  const clamped = Math.max(0, Math.min(1, fraction));
  const style: CSSProperties = { transform: `scaleX(${clamped})` };

  return (
    <div
      className="bar"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped * 100)}
      aria-valuetext={valueText}
    >
      <span className="bar__fill" data-state={state ?? undefined} style={style} />
    </div>
  );
}

// ------------------------------------------------------------- state tag --

export interface StateTagProps {
  state: CaptureState;
  /** Overrides the vocabulary's own word. Use sparingly: the rack's word is
   *  usually the right one, and changing it is how a vocabulary comes apart. */
  text?: string;
}

/** Word, shape and tone together, in that order of importance. Measured
 *  greyscale luminance put the old state hues between 8.0 and 9.3 -- one grey to
 *  a monochrome display and to most colour-blind readers -- so the word and the
 *  icon were always the carriers. Tone now comes from the state vocabulary in
 *  Account.css, keyed on data-state; it is not injected as an inline colour, and
 *  the outline the colour used to draw around the tag is gone with it. */
export function StateTag({ state, text }: StateTagProps) {
  const { t } = useI18n();
  const meta = CAPTURE_STATES[state];
  return (
    <span className="tag" data-state={state}>
      <Icon name={meta.icon} size={16} />
      {/* labelKey, not label. CAPTURE_STATES keeps the English `label` for the
          screens that have not moved onto the catalog; this one has. */}
      <span>{text ?? t(meta.labelKey)}</span>
    </span>
  );
}

// ------------------------------------------------------------ provenance --

export interface PendingProps {
  /** The endpoint this control is waiting on, written as it will appear in the
   *  contract. Shown to the reader, not only to whoever opens the source. */
  endpoint: string;
  children: ReactNode;
}

/* Every control on this screen that cannot persist says so where it is, in the
 * interface. A settings page that accepts a change, shows it applied, and drops
 * it on reload is a worse failure than one that admits the endpoint is not
 * built. */
export function Pending({ endpoint, children }: PendingProps) {
  return (
    <p className="pending">
      <Icon name="info" size={16} />
      <span>
        {children} <code className="pending__endpoint">{endpoint}</code>
      </span>
    </p>
  );
}
