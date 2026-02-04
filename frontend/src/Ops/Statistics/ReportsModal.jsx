import React, { useState, useEffect } from 'react';
import ReportManager from './ReportManager';
import './ReportsModal.css';

const ReportsModal = ({ isOpen, onClose }) => {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedReport, setSelectedReport] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [sortBy, setSortBy] = useState('created');

  useEffect(() => {
    if (isOpen) {
      loadReports();
    }
  }, [isOpen]);

  const loadReports = async () => {
    setLoading(true);
    try {
      const allReports = await ReportManager.getAllReports();
      setReports(allReports);
    } catch (error) {
      console.error('Failed to load reports:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteReport = async (reportId) => {
    if (window.confirm('Are you sure you want to delete this report?')) {
      await ReportManager.deleteReport(reportId);
      loadReports(); // Refresh the list
    }
  };

  const handleExportJSON = (report) => {
    ReportManager.exportReportAsJSON(report);
  };

  const handleExportHTML = (report) => {
    ReportManager.exportReportAsHTML(report);
  };

  const filteredReports = reports
    .filter(report => 
      report.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      report.dataset.name.toLowerCase().includes(searchTerm.toLowerCase())
    )
    .sort((a, b) => {
      if (sortBy === 'created') {
        return new Date(b.created) - new Date(a.created);
      } else if (sortBy === 'title') {
        return a.title.localeCompare(b.title);
      } else if (sortBy === 'dataset') {
        return a.dataset.name.localeCompare(b.dataset.name);
      }
      return 0;
    });

  if (!isOpen) return null;

  return (
    <div className="reports-modal-overlay">
      <div className="reports-modal">
        <div className="reports-modal-header">
          <h2>
            <i className="fas fa-file-alt" />
            Saved Reports
          </h2>
          <button className="close-btn" onClick={onClose}>
            <i className="fas fa-times" />
          </button>
        </div>

        <div className="reports-modal-controls">
          <div className="search-box">
            <i className="fas fa-search" />
            <input
              type="text"
              placeholder="Search reports..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <select 
            value={sortBy} 
            onChange={(e) => setSortBy(e.target.value)}
            className="sort-select"
          >
            <option value="created">Sort by Date</option>
            <option value="title">Sort by Title</option>
            <option value="dataset">Sort by Dataset</option>
          </select>
        </div>

        <div className="reports-modal-content">
          {loading ? (
            <div className="loading-state">
              <i className="fas fa-spinner fa-spin" />
              Loading reports...
            </div>
          ) : filteredReports.length === 0 ? (
            <div className="empty-state">
              <i className="fas fa-file-alt" />
              <h3>No Reports Found</h3>
              <p>
                {searchTerm 
                  ? 'No reports match your search criteria.' 
                  : 'You haven\'t saved any analysis reports yet.'
                }
              </p>
            </div>
          ) : (
            <div className="reports-list">
              {filteredReports.map(report => (
                <div key={report.id} className="report-card">
                  <div className="report-header">
                    <h3 className="report-title">{report.title}</h3>
                    <div className="report-actions">
                      <button
                        className="action-btn view-btn"
                        onClick={() => setSelectedReport(report)}
                        title="View Details"
                      >
                        <i className="fas fa-eye" />
                      </button>
                      <button
                        className="action-btn export-btn"
                        onClick={() => handleExportHTML(report)}
                        title="Export as HTML"
                      >
                        <i className="fas fa-file-export" />
                      </button>
                      <button
                        className="action-btn json-btn"
                        onClick={() => handleExportJSON(report)}
                        title="Export as JSON"
                      >
                        <i className="fas fa-code" />
                      </button>
                      <button
                        className="action-btn delete-btn"
                        onClick={() => handleDeleteReport(report.id)}
                        title="Delete Report"
                      >
                        <i className="fas fa-trash" />
                      </button>
                    </div>
                  </div>
                  
                  <div className="report-meta">
                    <div className="meta-item">
                      <i className="fas fa-database" />
                      {report.dataset.name} ({report.dataset.rows} rows, {report.dataset.columns} cols)
                    </div>
                    <div className="meta-item">
                      <i className="fas fa-chart-line" />
                      {report.analysis.goal} analysis
                    </div>
                    <div className="meta-item">
                      <i className="fas fa-calendar" />
                      {new Date(report.created).toLocaleDateString()}
                    </div>
                    {report.source && (
                      <div className="meta-item">
                        <i className={`fas fa-${report.source === 'backend' ? 'cloud' : 'hdd'}`} />
                        {report.source === 'backend' ? 'Cloud' : 'Local'}
                      </div>
                    )}
                  </div>

                  <div className="report-insights">
                    <p>{report.insights}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {selectedReport && (
          <ReportDetailModal 
            report={selectedReport} 
            onClose={() => setSelectedReport(null)}
          />
        )}
      </div>
    </div>
  );
};

const ReportDetailModal = ({ report, onClose }) => {
  return (
    <div className="report-detail-overlay">
      <div className="report-detail-modal">
        <div className="report-detail-header">
          <h2>{report.title}</h2>
          <button className="close-btn" onClick={onClose}>
            <i className="fas fa-times" />
          </button>
        </div>
        
        <div className="report-detail-content">
          <div className="detail-section">
            <h3>Dataset Information</h3>
            <div className="detail-grid">
              <div><strong>Name:</strong> {report.dataset.name}</div>
              <div><strong>Rows:</strong> {report.dataset.rows}</div>
              <div><strong>Columns:</strong> {report.dataset.columns}</div>
              <div><strong>Analysis:</strong> {report.analysis.goal}</div>
            </div>
          </div>

          <div className="detail-section">
            <h3>Key Insights</h3>
            <div className="insights-box">
              {report.insights}
            </div>
          </div>

          {report.analysis.results?.stats && (
            <div className="detail-section">
              <h3>Results Summary</h3>
              <div className="results-summary">
                {Object.keys(report.analysis.results.stats.describe || {}).length > 0 && (
                  <div>✓ Descriptive statistics for {Object.keys(report.analysis.results.stats.describe).length} variables</div>
                )}
                {report.analysis.results.stats.correlations?.length > 0 && (
                  <div>✓ {report.analysis.results.stats.correlations.length} correlation pairs analyzed</div>
                )}
                {Object.keys(report.analysis.results.stats.freq || {}).length > 0 && (
                  <div>✓ Frequency analysis for {Object.keys(report.analysis.results.stats.freq).length} categorical variables</div>
                )}
              </div>
            </div>
          )}

          <div className="detail-section">
            <h3>Metadata</h3>
            <div className="detail-grid">
              <div><strong>Created:</strong> {new Date(report.created).toLocaleString()}</div>
              <div><strong>User:</strong> {report.user}</div>
              <div><strong>Provider:</strong> {report.analysis.provider}</div>
              <div><strong>Version:</strong> {report.version}</div>
            </div>
          </div>
        </div>

        <div className="report-detail-actions">
          <button 
            className="btn-secondary"
            onClick={() => ReportManager.exportReportAsHTML(report)}
          >
            <i className="fas fa-file-export" />
            Export HTML
          </button>
          <button 
            className="btn-secondary"
            onClick={() => ReportManager.exportReportAsJSON(report)}
          >
            <i className="fas fa-code" />
            Export JSON
          </button>
        </div>
      </div>
    </div>
  );
};

export default ReportsModal;
