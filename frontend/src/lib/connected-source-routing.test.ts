import { describe, expect, it } from 'vitest';
import { shouldSearchConnectedData } from './connected-source-routing';

describe('connected-source query routing', () => {
  it('searches indexed Gmail data for a personal Armenian request', () => {
    expect(shouldSearchConnectedData('Կարո՞ղ ես ստուգել իմ Gmail-ը։')).toBe(true);
    expect(shouldSearchConnectedData('Գտիր իմ վերջին նամակները։')).toBe(true);
    expect(shouldSearchConnectedData('Կարո՞ղ ես ստուգել իմ mail-ը։')).toBe(true);
  });

  it('works with English and Russian personal mail queries', () => {
    expect(shouldSearchConnectedData('Check my inbox for unread mail')).toBe(true);
    expect(shouldSearchConnectedData('Проверь мою почту')).toBe(true);
  });

  it('does not turn normal conversation into expensive research', () => {
    expect(shouldSearchConnectedData('What is Gmail?')).toBe(false);
    expect(shouldSearchConnectedData('Explain how email works')).toBe(false);
    expect(shouldSearchConnectedData('Hello')).toBe(false);
  });

  it('does not route writes to the read-only research endpoint', () => {
    expect(shouldSearchConnectedData('Send an email from my Gmail')).toBe(false);
    expect(shouldSearchConnectedData('Ջնջիր իմ Gmail-ի նամակները')).toBe(false);
    expect(shouldSearchConnectedData('Отправь письмо с моей почты')).toBe(false);
  });
});
