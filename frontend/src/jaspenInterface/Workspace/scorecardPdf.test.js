jest.mock('html2canvas', () => jest.fn());
jest.mock('jspdf', () => ({ jsPDF: jest.fn() }));

import { compactScorecardGrid, createWorkspacePdfClone } from './scorecardPdf';

function setRect(node, { top = 0, left = 0, width = 0, height = 0 }) {
  node.getBoundingClientRect = () => ({
    top, left, width, height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON: () => {},
  });
}

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

test('scorecard export clone reflows fixed grid cards to their complete content', () => {
  const root = document.createElement('main');
  const grid = document.createElement('div');
  grid.className = 'jw-block-grid';
  const lower = gridItem('lower');
  const upper = gridItem('upper');
  grid.append(lower, upper);
  root.appendChild(grid);
  document.body.appendChild(root);

  Object.defineProperty(root, 'scrollWidth', { value: 900 });
  Object.defineProperty(root, 'offsetWidth', { value: 900 });
  setRect(grid, { top: 40, left: 20, width: 840, height: 700 });
  setRect(lower, { top: 380, left: 440, width: 420, height: 300 });
  setRect(upper, { top: 40, left: 20, width: 840, height: 300 });

  const clone = root.cloneNode(true);
  compactScorecardGrid(root, clone);
  const clonedGrid = clone.querySelector('.jw-block-grid');
  const items = Array.from(clonedGrid.children);

  expect(clonedGrid.style.display).toBe('grid');
  expect(items.map((item) => item.textContent)).toEqual(['upper', 'lower']);
  expect(items[0].style.gridColumn).toBe('1 / span 12');
  expect(items[1].style.gridColumn).toBe('7 / span 6');
  expect(items[0].style.position).toBe('relative');
  expect(items[0].style.height).toBe('auto');
  expect(items[0].firstElementChild.style.height).toBe('auto');
  expect(items[0].querySelector('section > div').style.overflow).toBe('visible');
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
