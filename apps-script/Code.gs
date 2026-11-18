// 구글 시트 → 확장 프로그램 → Apps Script에 이 파일 내용을 그대로 붙여넣고 "웹 앱"으로 배포한다.
// 페이지가 보내는 익명 결과를 'log' 시트에 한 줄씩 쌓는다. 개인정보(이름·이메일·IP)는 받지 않는다.

const HEAD = ['received', 'sid', 'ev', 'type', 'sc', 'rounds', 'shown', 'picks', 'skips', 'sec', 'friend', 'n_tracks'];
const cut = (v, n) => String(v === undefined || v === null ? '' : v).slice(0, n);  // 가짜 요청이 시트를 터뜨리지 않게 길이 제한

function doPost(e) {
  let d;
  try { d = JSON.parse(e.postData.contents); } catch (err) { return ContentService.createTextOutput('bad json'); }
  if (d.ev !== 'start' && d.ev !== 'done') return ContentService.createTextOutput('bad ev');

  const book = SpreadsheetApp.getActive();
  const sh = book.getSheetByName('log') || book.insertSheet('log');
  if (sh.getLastRow() === 0) sh.appendRow(HEAD);
  sh.appendRow([
    new Date(), cut(d.sid, 40), d.ev, cut(d.type, 40), cut(JSON.stringify(d.sc || ''), 200),
    cut(JSON.stringify(d.rounds || ''), 2000), cut(d.shown, 4), cut(JSON.stringify(d.picks || ''), 500),
    cut(d.skips, 4), cut(d.sec, 8), d.friend ? 1 : 0, cut(d.n, 6),
  ]);
  return ContentService.createTextOutput('ok');
}
