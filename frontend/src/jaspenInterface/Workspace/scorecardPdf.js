import html2canvas from 'html2canvas';
import { jsPDF } from 'jspdf';

function safeFilename(value) {
  const slug = String(value || 'scorecard')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 96);
  return `${slug || 'scorecard'}-scorecard.pdf`;
}

function nextFrame() {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

function safePageBreaks(element, targetHeight) {
  const root = element.getBoundingClientRect();
  const intervals = Array.from(element.querySelectorAll('.react-grid-item'))
    .map((node) => {
      const rect = node.getBoundingClientRect();
      return {
        top: Math.max(0, rect.top - root.top),
        bottom: Math.max(0, rect.bottom - root.top),
      };
    })
    .filter((item) => item.bottom > item.top);

  const height = Math.max(element.scrollHeight, element.offsetHeight);
  const breaks = [];
  let cursor = 0;
  while (height - cursor > targetHeight * 1.08) {
    const ideal = Math.min(height, cursor + targetHeight);
    const earliest = cursor + targetHeight * 0.72;
    let chosen = ideal;
    for (let y = ideal; y >= earliest; y -= 2) {
      const cutsTile = intervals.some((item) => item.top < y - 4 && item.bottom > y + 4);
      if (!cutsTile) {
        chosen = y;
        break;
      }
    }
    if (chosen <= cursor + 40) chosen = ideal;
    breaks.push(chosen);
    cursor = chosen;
  }
  breaks.push(height);
  return breaks;
}

/**
 * Export the scorecard customers are actually looking at. This intentionally
 * captures the rendered Workspace canvas rather than rebuilding a second,
 * lossy report from raw API fields. User text, custom blocks, accent color,
 * order, and tile sizing therefore remain consistent with the saved design.
 */
export async function downloadRenderedScorecardPdf(element, title) {
  if (!element) throw new Error('The scorecard is not ready to export.');

  if (document.fonts?.ready) await document.fonts.ready;
  // Let an active inline editor commit on blur before html2canvas clones it.
  await nextFrame();
  await nextFrame();

  const cssWidth = Math.max(element.scrollWidth, element.offsetWidth);
  const cssHeight = Math.max(element.scrollHeight, element.offsetHeight);
  const scale = Math.min(2, Math.max(1.5, Number(window.devicePixelRatio) || 1));
  const canvas = await html2canvas(element, {
    backgroundColor: '#ffffff',
    scale,
    useCORS: true,
    logging: false,
    width: cssWidth,
    height: cssHeight,
    windowWidth: Math.max(document.documentElement.clientWidth, cssWidth),
    onclone: (clonedDocument) => {
      const cloned = clonedDocument.querySelector('[data-scorecard-export]');
      if (!cloned) return;
      cloned.style.boxShadow = 'none';
      cloned.querySelectorAll(
        '[data-scorecard-export-hide], .blk-drag-handle, .react-resizable-handle',
      ).forEach((node) => { node.style.display = 'none'; });
      cloned.querySelectorAll('.react-grid-item').forEach((node) => {
        node.style.transition = 'none';
      });
    },
  });

  const pdf = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'letter', compress: true });
  const margin = 28;
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const imageWidth = pageWidth - margin * 2;
  const imageHeight = pageHeight - margin * 2;
  const cssPageHeight = imageHeight * cssWidth / imageWidth;
  const breaks = safePageBreaks(element, cssPageHeight);
  const canvasPerCssPixel = canvas.width / cssWidth;

  let startCss = 0;
  breaks.forEach((endCss, index) => {
    const sourceY = Math.max(0, Math.round(startCss * canvasPerCssPixel));
    const sourceEnd = Math.min(canvas.height, Math.round(endCss * canvasPerCssPixel));
    const sourceHeight = Math.max(1, sourceEnd - sourceY);
    const pageCanvas = document.createElement('canvas');
    pageCanvas.width = canvas.width;
    pageCanvas.height = sourceHeight;
    const context = pageCanvas.getContext('2d');
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, pageCanvas.width, pageCanvas.height);
    context.drawImage(canvas, 0, sourceY, canvas.width, sourceHeight, 0, 0, canvas.width, sourceHeight);

    if (index > 0) pdf.addPage();
    const renderedHeight = sourceHeight * imageWidth / canvas.width;
    pdf.addImage(pageCanvas.toDataURL('image/png'), 'PNG', margin, margin, imageWidth, renderedHeight, undefined, 'FAST');
    startCss = endCss;
  });

  pdf.save(safeFilename(title));
}

