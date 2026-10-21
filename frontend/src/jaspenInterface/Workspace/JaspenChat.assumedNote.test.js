const fs = require('fs');
const path = require('path');

test('the scorecard discloses criteria scored without information', () => {
  const chat = fs.readFileSync(path.join(__dirname, 'JaspenChat.jsx'), 'utf8');
  expect(chat).toContain('jas-scorecard-assumed-note');
  expect(chat).toContain('result.neutral_criteria.map');
});
