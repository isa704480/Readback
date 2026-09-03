import type { SVGProps } from 'react';

/* One icon family. Every glyph is drawn on the same 24x24 grid at the same
 * stroke weight with the same round caps, so a row of them reads as one set
 * rather than as icons collected from three places.
 *
 * These are <symbol> definitions referenced by <use>. The capture rack renders
 * one icon per row over potentially hundreds of rows, and a sprite defines each
 * path once instead of once per instance. The cost is a mount requirement:
 * <IconSprite /> must be in the tree, which App.tsx does at the root. */

const STROKE = 1.5; // at 24px this is the lightest weight that survives a 1x
// display without the joins filling in

export type IconName =
  // capture states -- these pair with CAPTURE_STATES in lib/api.ts, and exist
  // so that state is never carried by colour alone
  | 'settled'
  | 'repaired'
  | 'heard'
  | 'asking'
  | 'flagged'
  // interface
  | 'arrow-right'
  | 'chevron-down'
  | 'close'
  | 'menu'
  | 'check'
  | 'alert'
  | 'info'
  | 'eye'
  | 'eye-off'
  | 'lock'
  | 'mail'
  | 'user'
  | 'building'
  | 'copy'
  | 'external'
  | 'shield';

const ID = (name: IconName): string => `rb-icon-${name}`;

/** Mounted once, at the root. Every <Icon> in the tree points into this. */
export function IconSprite() {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      style={{ position: 'absolute', width: 0, height: 0, overflow: 'hidden' }}
    >
      <defs>
        <g
          id="rb-icon-defs"
          fill="none"
          stroke="currentColor"
          strokeWidth={STROKE}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </defs>

      {/* settled: the number is written down and correct */}
      <symbol id={ID('settled')} viewBox="0 0 24 24">
        <path d="M20 6.5 9.5 17 4 11.5" />
      </symbol>

      {/* repaired: a character was swapped without anyone being asked */}
      <symbol id={ID('repaired')} viewBox="0 0 24 24">
        <path d="M4 8.5h13M14 5.5l3 3-3 3" />
        <path d="M20 15.5H7M10 12.5l-3 3 3 3" />
      </symbol>

      {/* heard, not settled: received, still open */}
      <symbol id={ID('heard')} viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="2.75" fill="currentColor" stroke="none" />
      </symbol>

      {/* asking: the one-character question */}
      <symbol id={ID('asking')} viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8.5" />
        <path d="M9.4 9.6a2.7 2.7 0 1 1 3.4 3.2c-.7.3-1 .9-1 1.7" />
        <path d="M12 17.3h.01" />
      </symbol>

      {/* flagged: handed to a person */}
      <symbol id={ID('flagged')} viewBox="0 0 24 24">
        <path d="M5.25 21V3.75" />
        <path d="M5.25 4.5h12.5l-2.6 4 2.6 4H5.25" />
      </symbol>

      <symbol id={ID('arrow-right')} viewBox="0 0 24 24">
        <path d="M4 12h15M13 6l6 6-6 6" />
      </symbol>

      <symbol id={ID('chevron-down')} viewBox="0 0 24 24">
        <path d="m6 9.5 6 6 6-6" />
      </symbol>

      <symbol id={ID('close')} viewBox="0 0 24 24">
        <path d="m6 6 12 12M18 6 6 18" />
      </symbol>

      <symbol id={ID('menu')} viewBox="0 0 24 24">
        <path d="M4 7h16M4 12h16M4 17h16" />
      </symbol>

      <symbol id={ID('check')} viewBox="0 0 24 24">
        <path d="M20 6.5 9.5 17 4 11.5" />
      </symbol>

      <symbol id={ID('alert')} viewBox="0 0 24 24">
        <path d="M12 3.75 21.5 20.25H2.5z" />
        <path d="M12 9.75v4.25M12 17.5h.01" />
      </symbol>

      <symbol id={ID('info')} viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 11.25v5M12 8h.01" />
      </symbol>

      <symbol id={ID('eye')} viewBox="0 0 24 24">
        <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12" />
        <circle cx="12" cy="12" r="3" />
      </symbol>

      <symbol id={ID('eye-off')} viewBox="0 0 24 24">
        <path d="M9.9 5.8A9.3 9.3 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.7 3.6" />
        <path d="M6.3 7.7A17 17 0 0 0 2.5 12S6 18.5 12 18.5a9 9 0 0 0 3.6-.73" />
        <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
        <path d="M3.5 3.5l17 17" />
      </symbol>

      <symbol id={ID('lock')} viewBox="0 0 24 24">
        <rect x="4.75" y="10.5" width="14.5" height="9.75" rx="2" />
        <path d="M8.5 10.5V7.75a3.5 3.5 0 0 1 7 0v2.75" />
      </symbol>

      <symbol id={ID('mail')} viewBox="0 0 24 24">
        <rect x="2.75" y="5" width="18.5" height="14" rx="2" />
        <path d="m3.5 6.75 8.5 6 8.5-6" />
      </symbol>

      <symbol id={ID('user')} viewBox="0 0 24 24">
        <circle cx="12" cy="8.25" r="3.75" />
        <path d="M4.75 20.25a7.25 7.25 0 0 1 14.5 0" />
      </symbol>

      <symbol id={ID('building')} viewBox="0 0 24 24">
        <path d="M4.25 20.5V5a1.5 1.5 0 0 1 1.5-1.5h9a1.5 1.5 0 0 1 1.5 1.5v15.5" />
        <path d="M16.25 9.5h2.5a1.5 1.5 0 0 1 1.5 1.5v9.5" />
        <path d="M3 20.5h18M8 7.5h4.5M8 11.5h4.5M8 15.5h4.5" />
      </symbol>

      <symbol id={ID('copy')} viewBox="0 0 24 24">
        <rect x="8.75" y="8.75" width="11.5" height="11.5" rx="2" />
        <path d="M15.5 4.75h-9a1.75 1.75 0 0 0-1.75 1.75v9" />
      </symbol>

      <symbol id={ID('external')} viewBox="0 0 24 24">
        <path d="M14 4h6v6M20 4l-8.5 8.5" />
        <path d="M18 14.5V19a1.5 1.5 0 0 1-1.5 1.5H5.5A1.5 1.5 0 0 1 4 19V7.5A1.5 1.5 0 0 1 5.5 6H10" />
      </symbol>

      <symbol id={ID('shield')} viewBox="0 0 24 24">
        <path d="M12 3.25 19.25 6v6c0 4.4-3 8-7.25 9.25C7.75 20 4.75 16.4 4.75 12V6z" />
        <path d="m9 12 2.25 2.25L15.25 10.25" />
      </symbol>
    </svg>
  );
}

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: IconName;
  /** px. Defaults to 20, which optically matches 16px Archivo. */
  size?: number;
  /** Supply when the icon is the only carrier of its meaning; otherwise the
   *  icon stays aria-hidden and the adjacent text does the talking. */
  title?: string;
}

export function Icon({ name, size = 20, title, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={STROKE}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      <use href={`#${ID(name)}`} />
    </svg>
  );
}

export interface LogoProps {
  size?: number;
  className?: string;
}

/* The mark: a bracketed field of three characters with the middle one lit.
 * That is literally the product -- a constrained slot, and the single character
 * it will interrupt you about. The lit bar is the one place --hiviz is load
 * bearing, and it is a fill, not an ink. */
export function Logo({ size = 26, className }: LogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <path
        d="M8 3.5H4.5v17H8M16 3.5h3.5v17H16"
        stroke="currentColor"
        strokeWidth={STROKE}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x="8.75" y="8" width="1.75" height="8" rx="0.875" fill="currentColor" opacity="0.45" />
      <rect x="11.5" y="6.25" width="1.75" height="11.5" rx="0.875" fill="var(--hiviz)" />
      <rect x="14.25" y="8" width="1.75" height="8" rx="0.875" fill="currentColor" opacity="0.45" />
    </svg>
  );
}
