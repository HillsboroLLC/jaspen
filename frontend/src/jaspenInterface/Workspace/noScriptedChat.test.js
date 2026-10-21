const fs = require('fs');
const path = require('path');

const read = (rel) => fs.readFileSync(path.join(__dirname, '..', rel), 'utf8');

// Code is for labels and UI; the conversation is the AI's. These sentences
// were once written into the chat by code and must not come back.
test('no code-written chat sentences in Jaspen\'s voice', () => {
  const chat = read('Workspace/JaspenChat.jsx');
  [
    'Built an AI execution plan.',
    'Generated an AI project WBS',
    'I could not generate the project WBS',
    'Scenario accepted:',
    'Sorry — I hit an error',
    'Sorry, I encountered an error',
  ].forEach((sentence) => expect(chat).not.toContain(sentence));
  expect(read('Connectors/ConnectorsManage.jsx')).not.toContain('I hit an issue');
  expect(read('Scores/Scores.jsx')).not.toContain('I hit an issue');
});
