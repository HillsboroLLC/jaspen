import { submitLead, leadsMockMode, isLeadsMockEnabled, LEADS_ENDPOINT } from './leadClient';

const ORIGINAL_ENV = process.env.REACT_APP_LEADS_MOCK;

afterEach(() => {
  process.env.REACT_APP_LEADS_MOCK = ORIGINAL_ENV;
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
  // Reset any URL override jsdom may have picked up.
  window.history.pushState({}, '', '/');
  jest.restoreAllMocks();
});

describe('leadClient dev mock gating', () => {
  it('defaults to the real API (no env, no override)', () => {
    delete process.env.REACT_APP_LEADS_MOCK;
    expect(leadsMockMode()).toBeNull();
    expect(isLeadsMockEnabled()).toBe(false);
  });

  it('enables mock via env var in development', () => {
    process.env.REACT_APP_LEADS_MOCK = 'success';
    expect(leadsMockMode()).toBe('success');
    expect(isLeadsMockEnabled()).toBe(true);
  });

  it('lets a URL param override the env and persists it to localStorage', () => {
    process.env.REACT_APP_LEADS_MOCK = 'success';
    window.history.pushState({}, '', '/?leadsMock=fail');
    expect(leadsMockMode()).toBe('fail');
    expect(window.localStorage.getItem('jaspen_leads_mock')).toBe('fail');
  });

  it('treats "off" as a forced real-API override even when env asks for mock', () => {
    process.env.REACT_APP_LEADS_MOCK = 'success';
    window.history.pushState({}, '', '/?leadsMock=off');
    expect(leadsMockMode()).toBeNull();
  });
});

describe('submitLead', () => {
  it('calls the real endpoint when the mock is off', async () => {
    delete process.env.REACT_APP_LEADS_MOCK;
    const fetchSpy = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue({ ok: true, status: 201, json: async () => ({ ok: true }) });

    const res = await submitLead({ email: 'a@b.com', source: 'decision-planning-toolkit' });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, options] = fetchSpy.mock.calls[0];
    expect(url).toBe(LEADS_ENDPOINT);
    expect(JSON.parse(options.body)).toEqual({ email: 'a@b.com', source: 'decision-planning-toolkit' });
    expect(res.ok).toBe(true);
  });

  it('returns a mocked ok response without calling fetch in success mode', async () => {
    process.env.REACT_APP_LEADS_MOCK = 'success';
    const fetchSpy = jest.spyOn(global, 'fetch');

    const res = await submitLead({ email: 'a@b.com', source: 'decision-style-assessment' });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(res).toMatchObject({ ok: true, mocked: true });
  });

  it('throws without calling fetch in fail mode', async () => {
    process.env.REACT_APP_LEADS_MOCK = 'fail';
    const fetchSpy = jest.spyOn(global, 'fetch');

    await expect(submitLead({ email: 'a@b.com', source: 'x' })).rejects.toThrow();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
