// postcss.config.js
const isProd = process.env.NODE_ENV === 'production';

module.exports = {
  map: false,
  plugins: [
    // 1) Combine repeated selectors and drop duplicate props inside them
    require('postcss-combine-duplicated-selectors')({
      removeDuplicatedProperties: true,
    }),

    // 2) Merge compatible adjacent rules (helps reduce repetition)
    require('postcss-merge-rules'),

    // 3) Ensure selector lists are unique (removes dup selectors in a rule)
    require('postcss-unique-selectors'),

    // 4) Sort declarations consistently (SMACSS order)
    require('css-declaration-sorter')({ order: 'smacss' }),

    // 5) Minify ONLY in production (keeps dev output readable)
    ...(isProd
      ? [
          require('cssnano')({
            preset: [
              'default',
              {
                // keep your existing nano prefs
                discardDuplicates: true,
                mergeLonghand: true,
                mergeRules: true,
                // avoid overly aggressive normalizations that might surprise
                normalizeWhitespace: false,
              },
            ],
          }),
        ]
      : []),
  ],
};
