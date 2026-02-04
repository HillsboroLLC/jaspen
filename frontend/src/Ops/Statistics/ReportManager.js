// ReportManager.js - Utility for managing statistical analysis reports

class ReportManager {
  constructor() {
    this.storageKey = 'sekki_analysis_reports';
    this.apiBaseUrl = 'https://api.sekki.io/api/reports';
  }

  // Generate a unique report ID
  generateReportId() {
    return `report_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  // Create a report object from analysis session
  createReport({
    title,
    dataset,
    goal,
    result,
    aiAnalysisResults = null,
    fileName = '',
    plan = [],
    user = null
  }) {
    return {
      id: this.generateReportId(),
      title: title || `${goal.charAt(0).toUpperCase() + goal.slice(1)} Analysis - ${new Date().toLocaleDateString()}`,
      created: new Date().toISOString(),
      lastModified: new Date().toISOString(),
      dataset: {
        name: fileName || 'Unknown Dataset',
        rows: dataset.rows?.length || 0,
        columns: Object.keys(dataset.columns || {}).length,
        columnTypes: dataset.columns || {}
      },
      analysis: {
        goal,
        provider: 'local-js',
        plan,
        results: result,
        aiResults: aiAnalysisResults
      },
      insights: this.generateInsights(result, goal),
      user: user?.email || user?.name || 'Anonymous',
      version: '1.0'
    };
  }

  // Generate AI-like insights from results
  generateInsights(result, goal) {
    if (!result?.stats) return 'No analysis results available.';

    let insights = [];

    // Descriptive insights
    if (result.stats.describe && Object.keys(result.stats.describe).length > 0) {
      const numericVars = Object.keys(result.stats.describe).length;
      insights.push(`Analysis includes ${numericVars} numeric variable${numericVars > 1 ? 's' : ''}.`);
      
      // Find variables with high variability
      Object.entries(result.stats.describe).forEach(([col, stats]) => {
        const cv = stats.sd / stats.mean; // Coefficient of variation
        if (cv > 1) {
          insights.push(`${col} shows high variability (CV: ${(cv * 100).toFixed(1)}%).`);
        }
      });
    }

    // Correlation insights
    if (result.stats.correlations && result.stats.correlations.length > 0) {
      const strongCorrs = result.stats.correlations.filter(c => Math.abs(c.r) > 0.7);
      if (strongCorrs.length > 0) {
        insights.push(`Found ${strongCorrs.length} strong correlation${strongCorrs.length > 1 ? 's' : ''}.`);
        strongCorrs.forEach(c => {
          const strength = Math.abs(c.r) > 0.9 ? 'very strong' : 'strong';
          const direction = c.r > 0 ? 'positive' : 'negative';
          insights.push(`${c.a} and ${c.b} show a ${strength} ${direction} correlation (r=${c.r.toFixed(3)}).`);
        });
      }
    }

    // Frequency insights
    if (result.stats.freq && Object.keys(result.stats.freq).length > 0) {
      Object.entries(result.stats.freq).forEach(([col, freq]) => {
        const total = freq.reduce((sum, item) => sum + item.count, 0);
        const topCategory = freq.reduce((max, item) => item.count > max.count ? item : max, freq[0]);
        const percentage = ((topCategory.count / total) * 100).toFixed(1);
        insights.push(`${col}: "${topCategory.level}" is the most common category (${percentage}%).`);
      });
    }

    // Group comparison insights
    if (result.stats.groups && result.stats.groups.groups) {
      const groups = Object.entries(result.stats.groups.groups);
      if (groups.length > 1) {
        const means = groups.map(([name, stats]) => ({ name, mean: stats.mean }));
        means.sort((a, b) => b.mean - a.mean);
        insights.push(`Group comparison: ${means[0].name} has the highest mean ${result.stats.groups.target} (${means[0].mean.toFixed(2)}).`);
      }
    }

    return insights.length > 0 ? insights.join(' ') : 'Analysis completed successfully.';
  }

  // Save report locally
  saveReportLocally(report) {
    try {
      const existingReports = this.getLocalReports();
      const updatedReports = [...existingReports.filter(r => r.id !== report.id), report];
      
      // Keep only the last 50 reports to avoid storage issues
      const reportsToKeep = updatedReports
        .sort((a, b) => new Date(b.created) - new Date(a.created))
        .slice(0, 50);
      
      localStorage.setItem(this.storageKey, JSON.stringify(reportsToKeep));
      return { success: true, location: 'local' };
    } catch (error) {
      console.error('Failed to save report locally:', error);
      return { success: false, error: error.message };
    }
  }

  // Save report to backend
  async saveReportToBackend(report) {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`${this.apiBaseUrl}/statistical-analysis`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(report)
      });

      if (response.ok) {
        const savedReport = await response.json();
        return { success: true, location: 'backend', data: savedReport };
      } else {
        throw new Error(`Backend save failed: ${response.status}`);
      }
    } catch (error) {
      console.error('Failed to save report to backend:', error);
      return { success: false, error: error.message };
    }
  }

  // Hybrid save - try backend first, fallback to local
  async saveReport(report, forceLocal = false) {
    const results = {
      local: null,
      backend: null,
      primary: null
    };

    // Always save locally for quick access
    results.local = this.saveReportLocally(report);

    // Try backend save unless forced local-only
    if (!forceLocal) {
      results.backend = await this.saveReportToBackend(report);
      results.primary = results.backend.success ? 'backend' : 'local';
    } else {
      results.primary = 'local';
    }

    return results;
  }

  // Get local reports
  getLocalReports() {
    try {
      const reports = localStorage.getItem(this.storageKey);
      return reports ? JSON.parse(reports) : [];
    } catch (error) {
      console.error('Failed to load local reports:', error);
      return [];
    }
  }

  // Get backend reports
  async getBackendReports() {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`${this.apiBaseUrl}/statistical-analysis`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        return await response.json();
      } else {
        throw new Error(`Failed to fetch reports: ${response.status}`);
      }
    } catch (error) {
      console.error('Failed to load backend reports:', error);
      return [];
    }
  }

  // Get all reports (merged from local and backend)
  async getAllReports() {
    const localReports = this.getLocalReports();
    const backendReports = await this.getBackendReports();
    
    // Merge and deduplicate by ID
    const allReports = [...localReports];
    backendReports.forEach(backendReport => {
      if (!allReports.find(r => r.id === backendReport.id)) {
        allReports.push({ ...backendReport, source: 'backend' });
      }
    });

    // Sort by creation date (newest first)
    return allReports.sort((a, b) => new Date(b.created) - new Date(a.created));
  }

  // Delete report
  async deleteReport(reportId) {
    const results = {
      local: false,
      backend: false
    };

    // Delete from local storage
    try {
      const reports = this.getLocalReports();
      const filteredReports = reports.filter(r => r.id !== reportId);
      localStorage.setItem(this.storageKey, JSON.stringify(filteredReports));
      results.local = true;
    } catch (error) {
      console.error('Failed to delete local report:', error);
    }

    // Delete from backend
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`${this.apiBaseUrl}/statistical-analysis/${reportId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      results.backend = response.ok;
    } catch (error) {
      console.error('Failed to delete backend report:', error);
    }

    return results;
  }

  // Export report as JSON
  exportReportAsJSON(report) {
    const dataStr = JSON.stringify(report, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = `${report.title.replace(/[^a-z0-9]/gi, '_')}_report.json`;
    a.click();
    
    URL.revokeObjectURL(url);
  }

  // Export report as HTML
  exportReportAsHTML(report) {
    const html = this.generateHTMLReport(report);
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = `${report.title.replace(/[^a-z0-9]/gi, '_')}_report.html`;
    a.click();
    
    URL.revokeObjectURL(url);
  }

  // Generate HTML report
  generateHTMLReport(report) {
    return `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${report.title}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 40px; line-height: 1.6; }
        .header { border-bottom: 2px solid #007bff; padding-bottom: 20px; margin-bottom: 30px; }
        .title { color: #007bff; margin: 0; }
        .meta { color: #6c757d; margin-top: 10px; }
        .section { margin-bottom: 30px; }
        .section h2 { color: #2c3e50; border-bottom: 1px solid #e9ecef; padding-bottom: 10px; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
        th { background: #f8f9fa; font-weight: 600; }
        .insights { background: #f8f9fa; padding: 20px; border-radius: 8px; border-left: 4px solid #007bff; }
        .dataset-info { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }
        .info-card { background: #fff; border: 1px solid #e9ecef; padding: 15px; border-radius: 6px; }
    </style>
</head>
<body>
    <div class="header">
        <h1 class="title">${report.title}</h1>
        <div class="meta">
            Generated on ${new Date(report.created).toLocaleString()} | 
            User: ${report.user} | 
            Analysis: ${report.analysis.goal}
        </div>
    </div>

    <div class="section">
        <h2>Dataset Information</h2>
        <div class="dataset-info">
            <div class="info-card">
                <strong>Dataset:</strong> ${report.dataset.name}<br>
                <strong>Rows:</strong> ${report.dataset.rows}<br>
                <strong>Columns:</strong> ${report.dataset.columns}
            </div>
        </div>
    </div>

    <div class="section">
        <h2>Key Insights</h2>
        <div class="insights">
            ${report.insights}
        </div>
    </div>

    ${this.generateResultsHTML(report.analysis.results)}

    <div class="section">
        <h2>Analysis Details</h2>
        <p><strong>Goal:</strong> ${report.analysis.goal}</p>
        <p><strong>Provider:</strong> ${report.analysis.provider}</p>
        <p><strong>Generated:</strong> ${new Date(report.created).toLocaleString()}</p>
    </div>
</body>
</html>`;
  }

  // Generate HTML for results section
  generateResultsHTML(results) {
    if (!results?.stats) return '';

    let html = '<div class="section"><h2>Analysis Results</h2>';

    // Descriptive statistics
    if (results.stats.describe && Object.keys(results.stats.describe).length > 0) {
      html += '<h3>Descriptive Statistics</h3>';
      html += '<table><thead><tr><th>Column</th><th>Count</th><th>Mean</th><th>Std Dev</th><th>Min</th><th>Max</th></tr></thead><tbody>';
      Object.entries(results.stats.describe).forEach(([col, stats]) => {
        html += `<tr><td>${col}</td><td>${stats.n}</td><td>${stats.mean.toFixed(4)}</td><td>${stats.sd.toFixed(4)}</td><td>${stats.min.toFixed(4)}</td><td>${stats.max.toFixed(4)}</td></tr>`;
      });
      html += '</tbody></table>';
    }

    // Correlations
    if (results.stats.correlations && results.stats.correlations.length > 0) {
      html += '<h3>Correlations</h3>';
      html += '<table><thead><tr><th>Variable A</th><th>Variable B</th><th>Correlation (r)</th></tr></thead><tbody>';
      results.stats.correlations.forEach(corr => {
        html += `<tr><td>${corr.a}</td><td>${corr.b}</td><td>${corr.r.toFixed(4)}</td></tr>`;
      });
      html += '</tbody></table>';
    }

    html += '</div>';
    return html;
  }
}

// Export singleton instance
export default new ReportManager();
