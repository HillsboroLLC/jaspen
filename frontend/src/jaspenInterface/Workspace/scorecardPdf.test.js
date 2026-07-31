jest.mock('html2canvas', () => jest.fn());
jest.mock('jspdf', () => ({ jsPDF: jest.fn() }));

import { createWorkspacePdfClone } from './scorecardPdf';

function gridItem(label) {
  const item = document.createElement('div');
  item.className = 'react-grid-item';
  item.style.position = 'absolute';
  item.style.height = '300px';
  const card = document.createElement('section');
  card.style.height = '100%';
  card.style.overflow = 'hidden';
  const body = document.createElement('div');
  body.style.overflow = 'auto';
  body.textContent = label;
  card.appendChild(body);
  item.appendChild(card);
  return item;
}

afterEach(() => {
  document.body.innerHTML = '';
});

test('scorecard export clone preserves saved grid positions, heights, and clipping', () => {
  const root = document.createElement('main');
  const grid = document.createElement('div');
  grid.className = 'jw-block-grid';
  grid.style.position = 'relative';
  grid.style.height = '700px';
  const score = gridItem('score');
  score.style.transform = 'translate(0px, 0px)';
  score.style.width = '420px';
  const dimensions = gridItem('dimensions');
  dimensions.style.transform = 'translate(0px, 320px)';
  dimensions.style.width = '840px';
  dimensions.style.height = '360px';
  grid.append(score, dimensions);
  root.appendChild(grid);

  Object.defineProperty(root, 'scrollWidth', { value: 900 });
  Object.defineProperty(root, 'offsetWidth', { value: 900 });

  const { clone, wrapper } = createWorkspacePdfClone(root, 'scorecard');
  const clonedGrid = clone.querySelector('.jw-block-grid');
  const items = Array.from(clonedGrid.children);

  expect(clonedGrid.style.position).toBe('relative');
  expect(clonedGrid.style.height).toBe('700px');
  expect(items.map((item) => item.textContent)).toEqual(['score', 'dimensions']);
  expect(items[0].style.transform).toBe('translate(0px, 0px)');
  expect(items[0].style.width).toBe('420px');
  expect(items[0].style.height).toBe('300px');
  expect(items[1].style.transform).toBe('translate(0px, 320px)');
  expect(items[1].style.width).toBe('840px');
  expect(items[1].style.height).toBe('360px');
  expect(items[0].firstElementChild.style.height).toBe('100%');
  expect(items[0].firstElementChild.style.overflow).toBe('hidden');
  expect(items[0].querySelector('section > div').style.overflow).toBe('auto');
  wrapper.remove();
});

test('trade-off export clone preserves the page layout while exposing scroll content', () => {
  const root = document.createElement('main');
  const content = document.createElement('div');
  content.style.overflow = 'auto';
  content.textContent = 'portfolio';
  root.appendChild(content);
  Object.defineProperty(root, 'scrollWidth', { value: 1200 });
  Object.defineProperty(root, 'offsetWidth', { value: 1200 });

  const { clone, wrapper } = createWorkspacePdfClone(root, 'tradeoff');
  expect(clone.style.width).toBe('1200px');
  expect(clone.querySelector('div').style.overflow).toBe('visible');
  expect(document.body.contains(wrapper)).toBe(true);
  wrapper.remove();
});
