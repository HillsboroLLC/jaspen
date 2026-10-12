import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ExecutionPlanExportButton from './ExecutionPlanExportButton';
import { Jaspen } from './JaspenClient';

const mockShowToast = jest.fn();
jest.mock('../../shared/components/Toast', () => ({ useToast: () => ({ showToast: mockShowToast }) }));
jest.mock('./JaspenClient', () => ({ Jaspen: { downloadWbsXlsx: jest.fn() } }));

beforeEach(() => {
  jest.clearAllMocks();
  URL.createObjectURL = jest.fn(() => 'blob:test');
  URL.revokeObjectURL = jest.fn();
  jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
});

it('downloads the shared Excel export and reports success', async () => {
  Jaspen.downloadWbsXlsx.mockResolvedValue({ blob: new Blob(['xlsx']), filename: 'Launch-plan.xlsx' });
  render(<ExecutionPlanExportButton threadId="thread-1" scorecardId="score-1" />);
  fireEvent.click(screen.getByRole('button', { name: 'Export to Excel' }));
  await waitFor(() => expect(Jaspen.downloadWbsXlsx).toHaveBeenCalledWith('thread-1', { scorecardId: 'score-1' }));
  expect(mockShowToast).toHaveBeenCalledWith('Exported execution plan Excel workbook', 'success');
});

it('shows export failures', async () => {
  Jaspen.downloadWbsXlsx.mockRejectedValue(new Error('Export unavailable'));
  render(<ExecutionPlanExportButton threadId="thread-1" />);
  fireEvent.click(screen.getByRole('button', { name: 'Export to Excel' }));
  await waitFor(() => expect(mockShowToast).toHaveBeenCalledWith('Export unavailable', 'error'));
});
