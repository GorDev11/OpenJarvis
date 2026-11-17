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

/**
 * The indexed-data research endpoint cannot open external web pages. Even
 * when its toggle is on, explicit Browser/URL requests should use the agent
 * tool executor instead. A request to find a URL *in the user's mailbox*
 * remains personal research.
 */
const WEB_URL = /https?:\/\/[^\s<>"']+/iu;
const BROWSE_INTENT = /\b(?:browser|browse|open|visit|webpage|website|youtube|video|watch|summarize|read|fetch)\b|(?:բրաուզ|բրաուզեր|բացիր|նայիր|դիտիր|կարդա|տեսանյութ|վիդեո|վիդեոն|բացատրի|открой|браузер|видео|посмотри|прочитай)/iu;

export function shouldUseLiveWebTools(query: string): boolean {
  return WEB_URL.test(query) &&
    BROWSE_INTENT.test(query) &&
    !shouldSearchConnectedData(query);
}

export function shouldUseIndexedResearch(query: string, researchSelected: boolean): boolean {
  if (shouldSearchConnectedData(query)) return true;
  return researchSelected && !shouldUseLiveWebTools(query);
}
