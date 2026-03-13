const fs = require('fs');
const path = require('path');

const FRONTEND_SRC = path.join(process.cwd(), 'frontend', 'src');

const importMappings = [
  { old: /from ['"]\.\.\/components\/Dashboard\//g, new: "from '../Dashboard/" },
  { old: /from ['"]\.\/components\/Dashboard\//g, new: "from './Dashboard/" },
  { old: /from ['"]components\/Dashboard\//g, new: "from 'Dashboard/" },
  { old: /from ['"]\.\.\/components\/Strategy\//g, new: "from '../Jaspen/" },
  { old: /from ['"]\.\/components\/Strategy\//g, new: "from './Jaspen/" },
  { old: /from ['"]components\/Strategy\//g, new: "from 'Jaspen/" },
  { old: /from ['"]\.\.\/components\/Sessions\//g, new: "from '../Sessions/" },
  { old: /from ['"]\.\/components\/Sessions\//g, new: "from './Sessions/" },
  { old: /from ['"]components\/Sessions\//g, new: "from 'Sessions/" },
  { old: /from ['"]\.\.\/components\/Wizard\//g, new: "from '../Wizard/" },
  { old: /from ['"]\.\/components\/Wizard\//g, new: "from './Wizard/" },
  { old: /from ['"]components\/Wizard\//g, new: "from 'Wizard/" }
];

function updateFile(filePath) {
  let content = fs.readFileSync(filePath, 'utf8');
  let modified = false;
  importMappings.forEach(({ old, new: newPath }) => {
    if (old.test(content)) {
      content = content.replace(old, newPath);
      modified = true;
    }
  });
  if (modified) {
    fs.writeFileSync(filePath, content, 'utf8');
    console.log(`✅ Updated: ${filePath}`);
    return true;
  }
  return false;
}

function walkDirectory(dir, fileCallback) {
  const files = fs.readdirSync(dir);
  files.forEach(file => {
    const filePath = path.join(dir, file);
    const stat = fs.statSync(filePath);
    if (stat.isDirectory()) {
      if (file !== 'node_modules' && file !== 'build' && file !== '.git') {
        walkDirectory(filePath, fileCallback);
      }
    } else if (file.endsWith('.js') || file.endsWith('.jsx') || file.endsWith('.ts') || file.endsWith('.tsx')) {
      fileCallback(filePath);
    }
  });
}

let updatedCount = 0;
walkDirectory(FRONTEND_SRC, (filePath) => {
  if (updateFile(filePath)) {
    updatedCount++;
  }
});

console.log(`\n✨ Updated ${updatedCount} files`);
