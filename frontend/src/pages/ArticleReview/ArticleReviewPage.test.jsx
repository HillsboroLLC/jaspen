import fs from 'fs';
import path from 'path';
import { ARTICLES } from './articleCatalog';

describe('published article authors and layout', () => {
  it('assigns the requested author to every live article', () => {
    const authorsBySlug = Object.fromEntries(
      ARTICLES.map((article) => [article.slug, article.author]),
    );

    expect(authorsBySlug).toEqual({
      'true-cost-of-home-ownership': { name: 'Morgan Ellis' },
      'true-cost-of-renting': { name: 'Morgan Ellis' },
      'cost-of-employee-turnover': { name: 'L.Bailey', role: 'Founder' },
      'cost-of-rework': { name: 'L.Bailey', role: 'Founder' },
    });
  });

  it('does not render or style reserved ad placeholders in the article layout', () => {
    const component = fs.readFileSync(
      path.join(process.cwd(), 'src/pages/ArticleReview/ArticleReviewPage.jsx'),
      'utf8',
    );
    const css = fs.readFileSync(
      path.join(process.cwd(), 'src/pages/ArticleReview/ArticleReviewPage.css'),
      'utf8',
    );

    expect(component).not.toMatch(/Reserved ad placement|Reserved advertisement placements/);
    expect(component).not.toMatch(/article-draft-ad-slot|article-draft-ad-stack/);
    expect(css).not.toMatch(/article-draft-ad-slot|article-draft-ad-stack/);
  });
});
