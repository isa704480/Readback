/* The five identifier formats the solver arbitrates, with a valid example of
 * each. Shared by the Formats reference and the landing page's carousel, so
 * the two cannot show different numbers.
 *
 * Every example is checksum-valid: each was run through the actual solver
 * (server/readback/solver.py) before being written here. A made-up example
 * that failed its own check would be exactly the fabricated data this product
 * refuses. */

import type { PlainKey } from '../i18n';

export interface FormatDef {
  id: string;
  name: PlainKey;
  length: PlainKey;
  check: PlainKey;
  strength: PlainKey;
  measured: readonly PlainKey[];
  /** Who says this out loud on a call today: the line that tells a visitor
   *  whether the product is for them, before they read any arithmetic. */
  who: PlainKey;
  /** A valid identifier, verified against the solver. */
  example: string;
  /** 0-indexed positions that hold the computed check character(s). */
  checkPos: readonly number[];
  /** Rendered when the format identifies a real person. */
  sensitive: PlainKey | null;
}

export const FORMATS: readonly FormatDef[] = [
  {
    id: 'iso6346',
    who: 'formats.who.iso6346',
    name: 'account.format.iso6346.name',
    length: 'account.format.iso6346.length',
    check: 'account.format.iso6346.check',
    strength: 'account.format.iso6346.strength',
    measured: ['account.format.iso6346.measured.1', 'account.format.iso6346.measured.2'],
    example: 'MSKU4158005',
    checkPos: [10],
    sensitive: null,
  },
  {
    id: 'iban',
    who: 'formats.who.iban',
    name: 'account.format.iban.name',
    length: 'account.format.iban.length',
    check: 'account.format.iban.check',
    strength: 'account.format.iban.strength',
    measured: ['account.format.iban.measured.1', 'account.format.iban.measured.2'],
    example: 'GB82WEST12345698765432',
    checkPos: [2, 3],
    sensitive: null,
  },
  {
    id: 'vin',
    who: 'formats.who.vin',
    name: 'account.format.vin.name',
    length: 'account.format.vin.length',
    check: 'account.format.vin.check',
    strength: 'account.format.vin.strength',
    measured: [],
    example: '1HGCM82633A004352',
    checkPos: [8],
    sensitive: null,
  },
  {
    id: 'nhs',
    who: 'formats.who.nhs',
    name: 'account.format.nhs.name',
    length: 'account.format.nhs.length',
    check: 'account.format.nhs.check',
    strength: 'account.format.nhs.strength',
    measured: ['account.format.nhs.measured.1'],
    example: '9434765919',
    checkPos: [9],
    sensitive: 'account.format.nhs.sensitive',
  },
  {
    id: 'luhn',
    who: 'formats.who.luhn',
    name: 'account.format.luhn.name',
    length: 'account.format.luhn.length',
    check: 'account.format.luhn.check',
    strength: 'account.format.luhn.strength',
    measured: [],
    example: '4111111111111111',
    checkPos: [15],
    sensitive: 'account.format.luhn.sensitive',
  },
];
