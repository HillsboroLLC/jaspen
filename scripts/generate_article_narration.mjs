import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const sourceDirectory = path.join(root, 'docs/marketing/article-drafts');
const outputDirectory = path.join(root, 'Voices/article-scripts');

const articles = [
  'true-cost-of-home-ownership',
  'true-cost-of-renting',
  'cost-of-employee-turnover',
  'cost-of-rework',
];

function narrationText(markdown) {
  return markdown
    // Review notes belong to the editorial room, not the spoken article.
    .replace(/^(# [^\n]+\n\n)(?:>.*\n)+\n?/, '$1')
    // Keep human-readable link text while removing destinations.
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    // Convert Markdown structure into simple narration-friendly text.
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*\d+\.\s+/gm, '')
    .replace(/^\s*>\s?/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/[*_`]/g, '')
    .replace(/[ \t]+$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
    .concat('\n');
}

fs.mkdirSync(outputDirectory, { recursive: true });

for (const slug of articles) {
  const source = path.join(sourceDirectory, `${slug}.md`);
  const output = path.join(outputDirectory, `${slug}.txt`);
  const markdown = fs.readFileSync(source, 'utf8');
  fs.writeFileSync(output, narrationText(markdown), 'utf8');
  console.log(path.relative(root, output));
}
