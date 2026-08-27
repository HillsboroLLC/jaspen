import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import RecordDecisionPanel from './RecordDecisionPanel';

jest.mock('../../shared/auth/http', () => ({
  buildAuthHeaders: (h) => h || {},
}));
jest.mock('../../config/apiBase', () => ({ API_BASE: '' }));

const PENDING_RECORD = {
  id: 'rec-1',
  thread_id: 't-1',
  title: 'Warehouse automation',
  status: 'recorded',
  current_state: 'unknown',
  final_decision: null,
  decided_at: null,
  can_edit: true,
  recommendation: 'Pilot in one facility first.',
  alternatives: ['Option A', 'Option B'],
};

function mockFetch(handlers) {
  return jest.fn(async (url, options = {}) => {
    const method = options.method || 'GET';
    for (const [match, respond] of handlers) {
      if (url.includes(match) && (!match.method || match.method === method)) {
        const body = respond(options, method);
        if (body === undefined) continue;
        return { ok: true, status: 200, json: async () => body };
      }
    }
    return { ok: true, status: 200, json: async () => ({ records: [], results: [] }) };
  });
}

afterEach(() => {
  jest.resetAllMocks();
});

describe('RecordDecisionPanel', () => {
  it('shows the pending state without implying the recommendation is the decision', async () => {
    global.fetch = mockFetch([
      ['?thread_id=', () => ({ records: [PENDING_RECORD] })],
    ]);

    render(<RecordDecisionPanel threadId="t-1" alternatives={['Option A']} />);

    expect(await screen.findByText('Decision pending')).toBeInTheDocument();
    expect(screen.getByText(/No decision has been recorded yet/i)).toBeInTheDocument();
    // The recommendation text must not be presented as the decision.
    expect(screen.queryByText('Pilot in one facility first.')).not.toBeInTheDocument();
  });

  it('offers the record action to an editor', async () => {
    global.fetch = mockFetch([
      ['?thread_id=', () => ({ records: [PENDING_RECORD] })],
    ]);

    render(<RecordDecisionPanel threadId="t-1" alternatives={['Option A']} />);
    expect(await screen.findByRole('button', { name: /record decision/i })).toBeInTheDocument();
  });

  it('does not offer the action to a view-only user', async () => {
    global.fetch = mockFetch([
      ['?thread_id=', () => ({ records: [{ ...PENDING_RECORD, can_edit: false }] })],
    ]);

    render(<RecordDecisionPanel threadId="t-1" />);

    expect(await screen.findByText('Decision pending')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /record decision/i })).not.toBeInTheDocument();
  });

  it('shows a recorded decision and its current state to a viewer', async () => {
    global.fetch = mockFetch([
      ['?thread_id=', () => ({
        records: [{
          ...PENDING_RECORD,
          can_edit: false,
          current_state: 'current',
          status: 'decided',
          final_decision: 'We will pilot in Rotterdam.',
          decided_at: '2026-08-01T00:00:00',
        }],
      })],
    ]);

    render(<RecordDecisionPanel threadId="t-1" />);

    expect(await screen.findByText('Current decision')).toBeInTheDocument();
    expect(screen.getByText('We will pilot in Rotterdam.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /record/i })).not.toBeInTheDocument();
  });

  it('labels a superseded decision as superseded', async () => {
    global.fetch = mockFetch([
      ['?thread_id=', () => ({
        records: [{
          ...PENDING_RECORD,
          current_state: 'superseded',
          final_decision: 'Old plan.',
        }],
      })],
    ]);

    render(<RecordDecisionPanel threadId="t-1" />);
    expect(await screen.findByText('Superseded')).toBeInTheDocument();
  });

  it('requires an explicit confirmation and sends the human decision text', async () => {
    const patches = [];
    global.fetch = mockFetch([
      ['/search', () => ({ results: [] })],
      ['?thread_id=', () => ({ records: [PENDING_RECORD] })],
      ['/rec-1', (options, method) => {
        if (method !== 'PATCH') return undefined;
        patches.push(JSON.parse(options.body));
        return {
          record: {
            ...PENDING_RECORD,
            current_state: 'current',
            final_decision: JSON.parse(options.body).final_decision,
          },
        };
      }],
    ]);

    render(<RecordDecisionPanel threadId="t-1" alternatives={['Option A', 'Option B']} />);

    fireEvent.click(await screen.findByRole('button', { name: /record decision/i }));

    const textarea = await screen.findByPlaceholderText(/what is the organization deciding/i);
    fireEvent.change(textarea, { target: { value: 'We are choosing Option B despite the score.' } });

    // Review step first: no write happens on the first click.
    fireEvent.click(screen.getByRole('button', { name: /^review$/i }));
    expect(patches).toHaveLength(0);
    expect(screen.getByText(/becomes part of its decision history/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /confirm decision/i }));

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].final_decision).toBe('We are choosing Option B despite the score.');
  });

  it('lets the human decision differ from the AI recommendation', async () => {
    const patches = [];
    global.fetch = mockFetch([
      ['/search', () => ({ results: [] })],
      ['?thread_id=', () => ({ records: [PENDING_RECORD] })],
      ['/rec-1', (options, method) => {
        if (method !== 'PATCH') return undefined;
        patches.push(JSON.parse(options.body));
        return { record: { ...PENDING_RECORD, final_decision: 'No.' } };
      }],
    ]);

    render(<RecordDecisionPanel threadId="t-1" alternatives={['Option A']} />);
    fireEvent.click(await screen.findByRole('button', { name: /record decision/i }));

    const textarea = await screen.findByPlaceholderText(/what is the organization deciding/i);
    fireEvent.change(textarea, { target: { value: 'We are not proceeding at all.' } });
    fireEvent.click(screen.getByRole('button', { name: /^review$/i }));
    fireEvent.click(screen.getByRole('button', { name: /confirm decision/i }));

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].final_decision).toBe('We are not proceeding at all.');
    expect(patches[0].final_decision).not.toBe(PENDING_RECORD.recommendation);
  });

  it('refuses to submit an empty decision', async () => {
    const patches = [];
    global.fetch = mockFetch([
      ['/search', () => ({ results: [] })],
      ['?thread_id=', () => ({ records: [PENDING_RECORD] })],
      ['/rec-1', (options, method) => {
        if (method !== 'PATCH') return undefined;
        patches.push(JSON.parse(options.body));
        return { record: PENDING_RECORD };
      }],
    ]);

    render(<RecordDecisionPanel threadId="t-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /record decision/i }));
    fireEvent.click(screen.getByRole('button', { name: /^review$/i }));
    fireEvent.click(screen.getByRole('button', { name: /confirm decision/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/enter the decision/i);
    expect(patches).toHaveLength(0);
  });

  it('only offers predecessors the search endpoint returned', async () => {
    global.fetch = mockFetch([
      ['/search', () => ({
        results: [
          { id: 'rec-old', thread_id: 't-old', title: 'Pricing v1' },
          { id: 'rec-1', thread_id: 't-1', title: 'This same thread' },
        ],
      })],
      ['?thread_id=', () => ({ records: [PENDING_RECORD] })],
    ]);

    render(<RecordDecisionPanel threadId="t-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /record decision/i }));

    expect(await screen.findByText('Pricing v1')).toBeInTheDocument();
    // The record's own thread is not a predecessor of itself.
    expect(screen.queryByText('This same thread')).not.toBeInTheDocument();
  });

  it('renders nothing when no decision record exists yet', async () => {
    global.fetch = mockFetch([['?thread_id=', () => ({ records: [] })]]);
    const { container } = render(<RecordDecisionPanel threadId="t-1" />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it('renders nothing without a thread', () => {
    global.fetch = mockFetch([]);
    const { container } = render(<RecordDecisionPanel threadId={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

const DECIDED_RECORD = {
  ...PENDING_RECORD,
  current_state: 'current',
  status: 'decided',
  final_decision: 'We will pilot in Rotterdam.',
  decided_at: '2026-08-01T00:00:00',
  outcomes: [],
  lessons_learned: [],
};

describe('RecordDecisionPanel — outcome and lesson loop', () => {
  it('does not offer outcome capture before a decision exists', async () => {
    global.fetch = mockFetch([['?thread_id=', () => ({ records: [PENDING_RECORD] })]]);
    render(<RecordDecisionPanel threadId="t-1" />);

    expect(await screen.findByText('Decision pending')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /record outcome/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add lesson/i })).not.toBeInTheDocument();
  });

  it('offers outcome and lesson capture once decided', async () => {
    global.fetch = mockFetch([['?thread_id=', () => ({ records: [DECIDED_RECORD] })]]);
    render(<RecordDecisionPanel threadId="t-1" />);

    expect(await screen.findByRole('button', { name: /record outcome/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add lesson/i })).toBeInTheDocument();
    expect(screen.getByText('No outcome recorded yet.')).toBeInTheDocument();
  });

  it('submits an outcome with its status', async () => {
    const posts = [];
    global.fetch = mockFetch([
      ['/outcomes', (options, method) => {
        if (method !== 'POST') return undefined;
        posts.push(JSON.parse(options.body));
        return { record: { ...DECIDED_RECORD, outcomes: [{ id: 'out_1', summary: 'Late.' }] } };
      }],
      ['?thread_id=', () => ({ records: [DECIDED_RECORD] })],
    ]);

    render(<RecordDecisionPanel threadId="t-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /record outcome/i }));

    fireEvent.change(screen.getByPlaceholderText(/what actually happened/i), {
      target: { value: 'Launched six weeks late.' },
    });
    fireEvent.change(screen.getByLabelText(/outcome status/i), {
      target: { value: 'partially_achieved' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save outcome/i }));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({
      summary: 'Launched six weeks late.',
      status: 'partially_achieved',
    });
  });

  it('submits a lesson separately from the outcome', async () => {
    const posts = [];
    global.fetch = mockFetch([
      ['/lessons', (options, method) => {
        if (method !== 'POST') return undefined;
        posts.push(JSON.parse(options.body));
        return { record: DECIDED_RECORD };
      }],
      ['?thread_id=', () => ({ records: [DECIDED_RECORD] })],
    ]);

    render(<RecordDecisionPanel threadId="t-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /add lesson/i }));

    fireEvent.change(screen.getByPlaceholderText(/what should we do differently/i), {
      target: { value: 'Involve procurement earlier.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save lesson/i }));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({ lesson: 'Involve procurement earlier.' });
  });

  it('shows every recorded observation and lesson, not just the latest', async () => {
    global.fetch = mockFetch([
      ['?thread_id=', () => ({
        records: [{
          ...DECIDED_RECORD,
          outcomes: [
            { id: 'out_1', summary: 'Too early to tell.', status: 'too_early', recorded_by_name: 'Ada' },
            { id: 'out_2', summary: 'Target met at six months.', status: 'achieved', recorded_by_name: 'Ada' },
          ],
          lessons_learned: [
            { id: 'les_1', lesson: 'Pilot first.', recorded_by_name: 'Ada' },
            { id: 'les_2', lesson: 'Budget contingency.', recorded_by_name: 'Bo' },
          ],
        }],
      })],
    ]);

    render(<RecordDecisionPanel threadId="t-1" />);

    expect(await screen.findByText('Too early to tell.')).toBeInTheDocument();
    expect(screen.getByText('Target met at six months.')).toBeInTheDocument();
    expect(screen.getByText('Pilot first.')).toBeInTheDocument();
    expect(screen.getByText('Budget contingency.')).toBeInTheDocument();
  });

  it('does not offer outcome or lesson actions to a viewer', async () => {
    global.fetch = mockFetch([
      ['?thread_id=', () => ({
        records: [{
          ...DECIDED_RECORD,
          can_edit: false,
          outcomes: [{ id: 'out_1', summary: 'It shipped.' }],
        }],
      })],
    ]);

    render(<RecordDecisionPanel threadId="t-1" />);

    expect(await screen.findByText('It shipped.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /record outcome/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add lesson/i })).not.toBeInTheDocument();
  });

  it('refuses an empty outcome', async () => {
    const posts = [];
    global.fetch = mockFetch([
      ['/outcomes', (options, method) => {
        if (method !== 'POST') return undefined;
        posts.push(JSON.parse(options.body));
        return { record: DECIDED_RECORD };
      }],
      ['?thread_id=', () => ({ records: [DECIDED_RECORD] })],
    ]);

    render(<RecordDecisionPanel threadId="t-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /record outcome/i }));
    fireEvent.click(screen.getByRole('button', { name: /save outcome/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/describe what happened/i);
    expect(posts).toHaveLength(0);
  });
});
