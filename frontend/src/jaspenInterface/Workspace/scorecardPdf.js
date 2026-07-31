import html2canvas from 'html2canvas';
import { jsPDF } from 'jspdf';

function safeFilename(value, kind) {
  const fallback = kind === 'tradeoff' ? 'tradeoff' : 'scorecard';
  const slug = String(value || fallback)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 96);
  return `${slug || fallback}-${fallback}.pdf`;
}

function nextFrame() {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

function visibleHeight(element) {
  return Math.max(element.scrollHeight, element.offsetHeight, element.getBoundingClientRect().height);
}

function safePageBreaks(element, targetHeight) {
  const root = element.getBoundingClientRect();
  const intervals = Array.from(element.querySelectorAll(
    '.react-grid-item, [data-workspace-pdf-break]',
  ))
    .map((node) => {
      const rect = node.getBoundingClientRect();
      return {
        top: Math.max(0, rect.top - root.top),
        bottom: Math.max(0, rect.bottom - root.top),
      };
    })
    .filter((item) => item.bottom > item.top);

  const height = visibleHeight(element);
  const breaks = [];
  let cursor = 0;
  while (height - cursor > targetHeight * 1.02) {
    const ideal = Math.min(height, cursor + targetHeight);
    const earliest = cursor + targetHeight * 0.7;
    let chosen = ideal;
    for (let y = ideal; y >= earliest; y -= 2) {
      const cutsBlock = intervals.some((item) => item.top < y - 4 && item.bottom > y + 4);
      if (!cutsBlock) {
        chosen = y;
        break;
      }
    }
    if (chosen <= cursor + 40) chosen = ideal;
    breaks.push(chosen);
    cursor = chosen;
  }
  breaks.push(height);
  // A card-safe break can leave only the export canvas's trailing padding on
  // a new page. Fold a small tail into the previous page; addImage will scale
  // that page down slightly instead of emitting an empty-looking sheet.
  if (breaks.length > 1) {
    const lastPageHeight = height - breaks[breaks.length - 2];
    if (lastPageHeight < targetHeight * 0.18) breaks.splice(breaks.length - 2, 1);
  }
  return breaks;
}

function hideExportChrome(root) {
  root.querySelectorAll(
    '[data-workspace-export-hide], [data-scorecard-export-hide], .blk-drag-handle, .react-resizable-handle',
  ).forEach((node) => { node.style.display = 'none'; });
}

function makeScrollableContentVisible(root) {
  root.querySelectorAll('*').forEach((node) => {
    if (node.style.overflow === 'auto' || node.style.overflowY === 'auto') {
      node.style.overflow = 'visible';
      node.style.overflowY = 'visible';
      node.style.maxHeight = 'none';
    }
  });
}

/**
 * React Grid Layout uses absolute positions and user-selected fixed heights.
 * Those are useful while editing but create blank cards/pages in a printout.
 * Reflow only the detached export clone into the same 12-column visual order,
 * with each card sized to its complete saved content.
 */
export function compactScorecardGrid(originalRoot, clonedRoot) {
  const originalGrid = originalRoot.querySelector('.jw-block-grid');
  const clonedGrid = clonedRoot.querySelector('.jw-block-grid');
  if (!originalGrid || !clonedGrid) return;

  const gridRect = originalGrid.getBoundingClientRect();
  const gridWidth = Math.max(1, gridRect.width);
  const originals = Array.from(originalGrid.querySelectorAll(':scope > .react-grid-item'));
  const clones = Array.from(clonedGrid.querySelectorAll(':scope > .react-grid-item'));
  const entries = clones.map((clone, index) => {
    const rect = originals[index]?.getBoundingClientRect() || { top: index, left: 0, width: gridWidth };
    const relativeLeft = Math.max(0, rect.left - gridRect.left);
    const column = Math.max(0, Math.min(11, Math.round(relativeLeft / gridWidth * 12)));
    const span = Math.max(1, Math.min(12 - column, Math.round(rect.width / gridWidth * 12)));
    return { clone, top: rect.top - gridRect.top, left: relativeLeft, column, span };
  }).sort((a, b) => (a.top - b.top) || (a.left - b.left));

  Object.assign(clonedGrid.style, {
    display: 'grid',
    gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
    gap: '16px',
    alignItems: 'start',
    height: 'auto',
    minHeight: '0',
    position: 'relative',
  });

  entries.forEach(({ clone, column, span }) => {
    clonedGrid.appendChild(clone);
    Object.assign(clone.style, {
      position: 'relative',
      transform: 'none',
      inset: 'auto',
      left: 'auto',
      top: 'auto',
      width: 'auto',
      height: 'auto',
      minHeight: '0',
      gridColumn: `${column + 1} / span ${span}`,
      gridRow: 'auto',
      transition: 'none',
    });
    const card = clone.firstElementChild;
    if (card) {
      card.style.height = 'auto';
      card.style.minHeight = '0';
      card.style.overflow = 'visible';
    }
    makeScrollableContentVisible(clone);
  });
}

export function createWorkspacePdfClone(element, kind = 'scorecard') {
  const cssWidth = Math.max(element.scrollWidth, element.offsetWidth);
  const wrapper = document.createElement('div');
  Object.assign(wrapper.style, {
    position: 'fixed',
    left: '-100000px',
    top: '0',
    width: `${cssWidth}px`,
    background: '#ffffff',
    pointerEvents: 'none',
  });

  const clone = element.cloneNode(true);
  clone.setAttribute('data-workspace-pdf-export-root', kind);
  Object.assign(clone.style, {
    width: `${cssWidth}px`,
    maxWidth: 'none',
    height: 'auto',
    minHeight: '0',
    overflow: 'visible',
    boxShadow: 'none',
  });
  hideExportChrome(clone);
  makeScrollableContentVisible(clone);
  if (kind === 'scorecard') compactScorecardGrid(element, clone);

  wrapper.appendChild(clone);
  document.body.appendChild(wrapper);
  return { clone, wrapper, cssWidth };
}

/**
 * Export the Workspace surface customers are actually looking at. The PDF is
 * rendered from a detached DOM clone, so saved text, custom blocks, ordering,
 * scorecard colors, and the full trade-off table remain visually consistent.
 */
export async function downloadRenderedWorkspacePdf(element, title, options = {}) {
  if (!element) throw new Error('The workspace view is not ready to export.');
  const kind = options.kind === 'tradeoff' ? 'tradeoff' : 'scorecard';

  if (document.fonts?.ready) await document.fonts.ready;
  // Let an active inline editor commit on blur before copying the DOM.
  await nextFrame();
  await nextFrame();

  const { clone, wrapper, cssWidth } = createWorkspacePdfClone(element, kind);
  let canvas;
  let breaks;
  try {
    await nextFrame();
    const cssHeight = visibleHeight(clone);
    const scale = Math.min(2, Math.max(1.5, Number(window.devicePixelRatio) || 1));
    canvas = await html2canvas(clone, {
      backgroundColor: '#ffffff',
      scale,
      useCORS: true,
      logging: false,
      width: cssWidth,
      height: cssHeight,
      windowWidth: Math.max(document.documentElement.clientWidth, cssWidth),
      onclone: (clonedDocument) => {
        const cloned = clonedDocument.querySelector('[data-workspace-pdf-export-root]');
        if (!cloned) return;
        hideExportChrome(cloned);
      },
    });

    const format = kind === 'tradeoff' ? 'a3' : 'letter';
    const probePdf = new jsPDF({ orientation: 'landscape', unit: 'pt', format, compress: true });
    const margin = 28;
    const imageWidth = probePdf.internal.pageSize.getWidth() - margin * 2;
    const imageHeight = probePdf.internal.pageSize.getHeight() - margin * 2;
    const cssPageHeight = imageHeight * cssWidth / imageWidth;
    breaks = safePageBreaks(clone, cssPageHeight);
  } finally {
    wrapper.remove();
  }

  const format = kind === 'tradeoff' ? 'a3' : 'letter';
  const pdf = new jsPDF({ orientation: 'landscape', unit: 'pt', format, compress: true });
  const margin = 28;
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const availableWidth = pageWidth - margin * 2;
  const availableHeight = pageHeight - margin * 2;
  const canvasPerCssPixel = canvas.width / cssWidth;

  let pageIndex = 0;
  let startCss = 0;
  breaks.forEach((endCss) => {
    const sourceY = Math.max(0, Math.round(startCss * canvasPerCssPixel));
    const sourceEnd = Math.min(canvas.height, Math.round(endCss * canvasPerCssPixel));
    const sourceHeight = sourceEnd - sourceY;
    startCss = endCss;
    if (sourceHeight < 2) return;

    const pageCanvas = document.createElement('canvas');
    pageCanvas.width = canvas.width;
    pageCanvas.height = sourceHeight;
    const context = pageCanvas.getContext('2d');
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, pageCanvas.width, pageCanvas.height);
    context.drawImage(canvas, 0, sourceY, canvas.width, sourceHeight, 0, 0, canvas.width, sourceHeight);

    if (pageIndex > 0) pdf.addPage();
    const scaleToFit = Math.min(availableWidth / canvas.width, availableHeight / sourceHeight);
    const renderedWidth = canvas.width * scaleToFit;
    const renderedHeight = sourceHeight * scaleToFit;
    pdf.addImage(
      pageCanvas.toDataURL('image/png'),
      'PNG',
      margin + (availableWidth - renderedWidth) / 2,
      margin,
      renderedWidth,
      renderedHeight,
      undefined,
      'FAST',
    );
    pageIndex += 1;
  });

  pdf.save(safeFilename(title, kind));
  return pdf;
}

export function downloadRenderedScorecardPdf(element, title) {
  return downloadRenderedWorkspacePdf(element, title, { kind: 'scorecard' });
}
