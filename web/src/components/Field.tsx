import { useId, useState } from 'react';
import type { InputHTMLAttributes, ReactNode, Ref } from 'react';
import { Icon } from './Icon';
import { useI18n } from '../i18n';
import './Field.css';

export interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id' | 'children'> {
  label: string;
  /** Guidance shown before anything goes wrong. */
  hint?: ReactNode;
  /** Present means invalid: it sets aria-invalid and renders below the input. */
  error?: string | null;
  /** Adds a show/hide control. Only meaningful on type="password". */
  reveal?: boolean;
  /** Rendered directly under the input, above the hint. This is where the
   *  password strength meter goes. */
  children?: ReactNode;
  inputRef?: Ref<HTMLInputElement>;
  className?: string;
}

export function Field({
  label,
  hint,
  error,
  reveal = false,
  children,
  inputRef,
  className,
  type = 'text',
  required,
  ...rest
}: FieldProps) {
  const { t, locale } = useI18n();
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const [shown, setShown] = useState(false);

  const invalid = typeof error === 'string' && error.length > 0;

  /* Both descriptions are named whether or not they are currently rendered is
   * irrelevant to correctness -- aria-describedby tolerates missing ids -- but
   * listing only what exists keeps the announcement short. */
  const describedBy = [hint ? hintId : null, invalid ? errorId : null].filter(Boolean).join(' ');

  const effectiveType = reveal && shown ? 'text' : type;

  return (
    <div className={['field', className].filter(Boolean).join(' ')}>
      <label className="field__label" htmlFor={id}>
        {label}
        {required ? (
          <span className="field__required">
            <span aria-hidden="true">*</span>
            {/* The asterisk is not a word. The marker is spoken in the reader's
                language, and the space is here rather than inside the catalog
                value so no translation carries an invisible leading space. */}
            <span className="sr-only"> {t('field.required')}</span>
          </span>
        ) : null}
      </label>

      <div className="field__row">
        <input
          id={id}
          ref={inputRef}
          type={effectiveType}
          required={required}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy || undefined}
          className={['field__input', reveal ? 'field__input--reveal' : ''].filter(Boolean).join(' ')}
          {...rest}
        />

        {reveal ? (
          <button
            type="button"
            className="field__reveal"
            onClick={() => setShown((value) => !value)}
            /* The control's own label changes, so its state is spoken rather
               than left to the icon swap. toLocaleLowerCase against the pinned
               tag, not toLowerCase: the case mapping is a language decision and
               this component has the language to hand. */
            aria-label={
              shown
                ? t('field.reveal.hide', { label: label.toLocaleLowerCase(locale) })
                : t('field.reveal.show', { label: label.toLocaleLowerCase(locale) })
            }
            aria-pressed={shown}
          >
            <Icon name={shown ? 'eye-off' : 'eye'} size={20} />
          </button>
        ) : null}
      </div>

      {children ? <div className="field__slot">{children}</div> : null}

      {hint ? (
        <p className="field__hint" id={hintId}>
          {hint}
        </p>
      ) : null}

      {/* Always in the tree so the live region exists before the message does;
          a region inserted at the same moment as its content is often missed. */}
      <div aria-live="polite">
        {invalid ? (
          <p className="field__error" id={errorId}>
            <Icon name="alert" size={16} />
            <span>{error}</span>
          </p>
        ) : null}
      </div>
    </div>
  );
}
