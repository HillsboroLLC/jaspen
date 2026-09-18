import { mergePersistedSectionLayout } from './scorecardSectionLayout';

const DEFAULTS = [
  { key: 'score', x: 0, y: 0, w: 12, h: 4 },
  { key: 'confidence', x: 0, y: 4, w: 12, h: 7 },
  { key: 'executive', x: 0, y: 12, w: 12, h: 5 },
  { key: 'dimensions', x: 0, y: 17, w: 12, h: 8 },
  { key: 'risks', x: 0, y: 25, w: 12, h: 8 },
  { key: 'scenario', x: 0, y: 33, w: 12, h: 6 },
  { key: 'impact', x: 0, y: 39, w: 12, h: 12 },
];


it('restores exact saved coordinates instead of reflowing full-width cards', () => {
  const saved = [
    { key: 'score', x: 0, y: 0, w: 4, h: 4 },
    { key: 'executive', x: 4, y: 0, w: 8, h: 4 },
    { key: 'confidence', x: 0, y: 4, w: 12, h: 7 },
    { key: 'dimensions', x: 0, y: 11, w: 12, h: 8 },
    { key: 'risks', x: 0, y: 19, w: 12, h: 8 },
    { key: 'scenario', x: 0, y: 27, w: 12, h: 6 },
    { key: 'impact', x: 0, y: 33, w: 12, h: 12 },
  ];

  const restored = mergePersistedSectionLayout(saved, DEFAULTS);

  expect(restored.find((section) => section.key === 'score')).toMatchObject({
    x: 0, y: 0, w: 4, h: 4,
  });
  expect(restored.find((section) => section.key === 'executive')).toMatchObject({
    x: 4, y: 0, w: 8, h: 4,
  });
  expect(restored.find((section) => section.key === 'confidence')).toMatchObject({
    x: 0, y: 4, w: 12, h: 7,
  });
});


it('places a newly introduced section below an older saved arrangement', () => {
  const saved = [
    { key: 'score', x: 0, y: 0, w: 12, h: 4 },
    { key: 'executive', x: 0, y: 4, w: 12, h: 5 },
    { key: 'dimensions', x: 0, y: 9, w: 12, h: 8 },
    { key: 'risks', x: 0, y: 17, w: 12, h: 8 },
    { key: 'scenario', x: 0, y: 25, w: 12, h: 6 },
  ];

  const restored = mergePersistedSectionLayout(saved, DEFAULTS);
  const confidence = restored.find((section) => section.key === 'confidence');
  const impact = restored.find((section) => section.key === 'impact');

  expect(confidence.y).toBeGreaterThanOrEqual(31);
  expect(impact.y).toBeGreaterThanOrEqual(confidence.y + confidence.h);
});
