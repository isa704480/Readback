import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { LinkProps } from 'react-router-dom';
import { useI18n } from '../i18n';
import './Button.css';

export type ButtonVariant = 'primary' | 'secondary' | 'quiet';

function classes(variant: ButtonVariant, block: boolean, extra?: string): string {
  return ['btn', `btn--${variant}`, block ? 'btn--block' : '', extra ?? '']
    .filter(Boolean)
    .join(' ');
}

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> {
  variant?: ButtonVariant;
  block?: boolean;
  /** Disables the control and swaps the label. */
  busy?: boolean;
  /** Shown while busy. A word, not a spinner: under prefers-reduced-motion an
   *  animation collapses to nothing and a spinner-only button would go silent.
   *  Omit it and the button says so in the interface language; pass one when the
   *  verb matters ("Checking", "Creating"), already localised by the caller. */
  busyLabel?: string;
  className?: string;
  children?: ReactNode;
}

export function Button({
  variant = 'primary',
  block = false,
  busy = false,
  busyLabel,
  className,
  children,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  const { t } = useI18n();
  return (
    <button
      type={type}
      className={classes(variant, block, className)}
      disabled={disabled === true || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <span className="btn__busy">{busyLabel ?? t('button.busy')}</span> : children}
    </button>
  );
}

export interface ButtonLinkProps extends Omit<LinkProps, 'className'> {
  variant?: ButtonVariant;
  block?: boolean;
  className?: string;
}

/** Same skin, but it navigates. A control that changes the URL is an anchor, so
 *  middle-click and copy-link keep working. */
export function ButtonLink({
  variant = 'primary',
  block = false,
  className,
  children,
  ...rest
}: ButtonLinkProps) {
  return (
    <Link className={classes(variant, block, className)} {...rest}>
      {children}
    </Link>
  );
}
