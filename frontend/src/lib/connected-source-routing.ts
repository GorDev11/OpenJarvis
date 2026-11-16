/**
 * Route explicit requests to search the user's own indexed data through
 * the existing read-only Deep Research path. This does not grant any new
 * permissions and cannot execute mutations (send/delete/archive).
 *
 * Ordinary chat stays fast and uses the configured model.
 */
const SOURCE = /\b(?:gmail|e-?mail|mail|inbox|outlook|google drive|gdrive|slack|notion)\b|(?:նամակ|փոստարկղ|էլեկտրոնային\s+փոստ|почт|письм|входящ)/iu;
const PERSONAL_SEARCH = /\b(?:my|mine|our|read|find|search|check|show|summarize|recent|latest|unread)\b|(?:իմ|մեր|ստուգ|կարդ|փնտր|գտ|ցույց|վերջին|չկարդացված|мо[яйи]|мне|провер|прочит|найд|покаж|последн|непрочитан)/iu;
const MUTATION = /\b(?:send|compose|delete|archive|reply|forward|trash)\b|(?:ուղարկ|ջնջ|արխիվաց|պատասխան|отправ|удал|архивир|ответ|перешл)/iu;

export function shouldSearchConnectedData(query: string): boolean {
  const text = query.trim();
  return text.length > 0 && SOURCE.test(text) &&
    PERSONAL_SEARCH.test(text) && !MUTATION.test(text);
}
