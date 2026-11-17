import { describe, expect, it } from 'vitest';
import { shouldSearchConnectedData, shouldUseIndexedResearch, shouldUseLiveWebTools } from './connected-source-routing';

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

describe('external web versus indexed personal research', () => {
  it('uses live Browser tools for the exact Armenian YouTube request even if research is on', () => {
    const request = 'Օգտագործիր Browser գործիքը, բացիր https://www.youtube.com/watch?v=jA5Snm8mLgk և ասա՝ ինչի մասին է';
    expect(shouldUseLiveWebTools(request)).toBe(true);
    expect(shouldUseIndexedResearch(request, true)).toBe(false);
  });

  it('uses live tools when asked to open a public page', () => {
    expect(shouldUseIndexedResearch('Open https://example.com in Browser', true)).toBe(false);
    expect(shouldUseIndexedResearch('Summarize https://example.com', true)).toBe(false);
  });

  it('preserves personal Gmail searches including links appearing in email', () => {
    const query = 'Գտիր իմ Gmail-ի նամակը, որտեղ կա https://youtube.com/watch?v=xyz';
    expect(shouldUseIndexedResearch(query, true)).toBe(true);
    expect(shouldUseLiveWebTools(query)).toBe(false);
  });

  it('keeps research selected for indexed searches without external links', () => {
    expect(shouldUseIndexedResearch('Գտիր իմ վերջին նամակները', false)).toBe(true);
    expect(shouldUseIndexedResearch('Summary of my notes', true)).toBe(true);
    expect(shouldUseIndexedResearch('What does this mean?', false)).toBe(false);
  });
});
