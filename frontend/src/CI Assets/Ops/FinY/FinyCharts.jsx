import React, { useState, useEffect, useMemo } from 'react';
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  ComposedChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ScatterChart,
  Scatter,
  ReferenceLine,
  ReferenceArea
} from 'recharts';
import styles from './FinY.module.css';

const FinYCharts = ({ 
  metrics, 
  periods, 
  selectedMetric, 
  financialSummary, 
  projectInfo,
  viewSettings 
}) => {
  const [activeChart, setActiveChart] = useState('trend');
  const [chartData, setChartData] = useState([]);
  const [comparisonData, setComparisonData] = useState([]);
  const [financialBreakdown, setFinancialBreakdown] = useState([]);
  const [performanceData, setPerformanceData] = useState([]);

  // Color palette for charts
  const colors = {
    baseline: '#8884d8',
    actual: '#ff7300',
    projected: '#82ca9d',
    target: '#ffc658',
    positive: '#00C49F',
    negative: '#FF8042',
    neutral: '#FFBB28'
  };

  // Prepare trend chart data
  useEffect(() => {
    if (!metrics[selectedMetric]) return;

    const metric = metrics[selectedMetric];
    const data = periods.map((period, index) => ({
      period,
      baseline: metric.baseline[index],
      actual: metric.actual[index] || null,
      projected: metric.projected[index],
      target: metric.target[index],
      variance: metric.actual[index] ? 
        ((metric.actual[index] - metric.baseline[index]) / metric.baseline[index] * 100) : null,
      improvement: metric.projected[index] ? 
        ((metric.projected[index] - metric.baseline[index]) / metric.baseline[index] * 100) : 0
    }));

    setChartData(data);
  }, [metrics, selectedMetric, periods]);

  // Prepare comparison data for all metrics
  useEffect(() => {
    const data = metrics.map(metric => {
      const totalBaseline = metric.baseline.reduce((sum, val) => sum + val, 0);
      const totalActual = metric.actual.reduce((sum, val) => sum + val, 0);
      const totalProjected = metric.projected.reduce((sum, val) => sum + val, 0);
      const totalTarget = metric.target.reduce((sum, val) => sum + val, 0);

      return {
        name: metric.name.substring(0, 15) + (metric.name.length > 15 ? '...' : ''),
        fullName: metric.name,
        baseline: totalBaseline,
        actual: totalActual,
        projected: totalProjected,
        target: totalTarget,
        category: metric.category,
        impact: metric.financialImpact,
        performance: totalActual > 0 ? ((totalActual - totalBaseline) / totalBaseline * 100) : 0
      };
    });

    setComparisonData(data);
  }, [metrics]);

  // Prepare financial breakdown data
  useEffect(() => {
    const breakdown = metrics.map(metric => {
      let totalBenefit = 0;
      
      metric.projected.forEach((projected, index) => {
        const baseline = metric.baseline[index];
        const improvement = projected - baseline;
        const benefit = improvement * metric.costPerUnit;
        
        if (metric.financialImpact === 'Cost Reduction' && improvement < 0) {
          totalBenefit += Math.abs(benefit);
        } else if (metric.financialImpact === 'Revenue Increase' && improvement > 0) {
          totalBenefit += benefit;
        } else if (metric.financialImpact === 'Cost Avoidance' && improvement > 0) {
          totalBenefit += benefit;
        }
      });

      return {
        name: metric.name,
        benefit: totalBenefit,
        category: metric.category,
        impact: metric.financialImpact,
        percentage: financialSummary.totalBenefit > 0 ? 
          (totalBenefit / financialSummary.totalBenefit * 100) : 0
      };
    }).filter(item => item.benefit > 0);

    setFinancialBreakdown(breakdown);
  }, [metrics, financialSummary]);

  // Prepare performance radar data
  useEffect(() => {
    const categories = [...new Set(metrics.map(m => m.category))];
    const data = categories.map(category => {
      const categoryMetrics = metrics.filter(m => m.category === category);
      
      const avgPerformance = categoryMetrics.reduce((sum, metric) => {
        const totalBaseline = metric.baseline.reduce((a, b) => a + b, 0);
        const totalActual = metric.actual.reduce((a, b) => a + b, 0);
        return sum + (totalActual > 0 ? ((totalActual - totalBaseline) / totalBaseline * 100) : 0);
      }, 0) / categoryMetrics.length;

      const avgTarget = categoryMetrics.reduce((sum, metric) => {
        const totalBaseline = metric.baseline.reduce((a, b) => a + b, 0);
        const totalTarget = metric.target.reduce((a, b) => a + b, 0);
        return sum + ((totalTarget - totalBaseline) / totalBaseline * 100);
      }, 0) / categoryMetrics.length;

      return {
        category,
        performance: Math.max(0, Math.min(100, avgPerformance + 50)), // Normalize to 0-100
        target: Math.max(0, Math.min(100, avgTarget + 50)),
        count: categoryMetrics.length
      };
    });

    setPerformanceData(data);
  }, [metrics]);

  // Custom tooltip for trend chart
  const TrendTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div className={styles.customTooltip}>
          <p className={styles.tooltipLabel}>{`Period: ${label}`}</p>
          {payload.map((entry, index) => (
            <p key={index} style={{ color: entry.color }}>
              {`${entry.dataKey}: ${entry.value?.toFixed(2)} ${metrics[selectedMetric]?.unit || ''}`}
            </p>
          ))}
          {payload.find(p => p.dataKey === 'variance') && (
            <p className={styles.tooltipVariance}>
              Variance: {payload.find(p => p.dataKey === 'variance')?.value?.toFixed(1)}%
            </p>
          )}
        </div>
      );
    }
    return null;
  };

  // Custom tooltip for financial breakdown
  const FinancialTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className={styles.customTooltip}>
          <p className={styles.tooltipLabel}>{data.name}</p>
          <p style={{ color: payload[0].color }}>
            Benefit: {projectInfo.currency} {data.benefit.toLocaleString()}
          </p>
          <p>Percentage: {data.percentage.toFixed(1)}%</p>
          <p>Category: {data.category}</p>
          <p>Impact Type: {data.impact}</p>
        </div>
      );
    }
    return null;
  };

  // Render trend analysis chart
  const renderTrendChart = () => (
    <div className={styles.chartContainer}>
      <div className={styles.chartHeader}>
        <h4>Trend Analysis - {metrics[selectedMetric]?.name}</h4>
        <div className={styles.chartControls}>
          <button 
            className={`${styles.chartBtn} ${activeChart === 'trend' ? styles.active : ''}`}
            onClick={() => setActiveChart('trend')}
          >
            Line Chart
          </button>
          <button 
            className={`${styles.chartBtn} ${activeChart === 'area' ? styles.active : ''}`}
            onClick={() => setActiveChart('area')}
          >
            Area Chart
          </button>
          <button 
            className={`${styles.chartBtn} ${activeChart === 'composed' ? styles.active : ''}`}
            onClick={() => setActiveChart('composed')}
          >
            Combined
          </button>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={400}>
        {activeChart === 'trend' && (
          <LineChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="period" />
            <YAxis />
            <Tooltip content={<TrendTooltip />} />
            <Legend />
            <Line 
              type="monotone" 
              dataKey="baseline" 
              stroke={colors.baseline} 
              strokeWidth={2}
              name="Baseline"
              dot={{ r: 4 }}
            />
            <Line 
              type="monotone" 
              dataKey="actual" 
              stroke={colors.actual} 
              strokeWidth={2}
              name="Actual"
              connectNulls={false}
              dot={{ r: 4 }}
            />
            <Line 
              type="monotone" 
              dataKey="projected" 
              stroke={colors.projected} 
              strokeWidth={2}
              strokeDasharray="5 5"
              name="AI Projected"
              dot={{ r: 4 }}
            />
            <Line 
              type="monotone" 
              dataKey="target" 
              stroke={colors.target} 
              strokeWidth={2}
              strokeDasharray="10 5"
              name="Target"
              dot={{ r: 4 }}
            />
          </LineChart>
        )}

        {activeChart === 'area' && (
          <AreaChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="period" />
            <YAxis />
            <Tooltip content={<TrendTooltip />} />
            <Legend />
            <Area 
              type="monotone" 
              dataKey="baseline" 
              stackId="1"
              stroke={colors.baseline} 
              fill={colors.baseline}
              fillOpacity={0.3}
              name="Baseline"
            />
            <Area 
              type="monotone" 
              dataKey="projected" 
              stackId="2"
              stroke={colors.projected} 
              fill={colors.projected}
              fillOpacity={0.3}
              name="AI Projected"
            />
            <Line 
              type="monotone" 
              dataKey="actual" 
              stroke={colors.actual} 
              strokeWidth={3}
              name="Actual"
              connectNulls={false}
            />
          </AreaChart>
        )}

        {activeChart === 'composed' && (
          <ComposedChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="period" />
            <YAxis yAxisId="left" />
            <YAxis yAxisId="right" orientation="right" />
            <Tooltip content={<TrendTooltip />} />
            <Legend />
            <Bar yAxisId="left" dataKey="variance" fill={colors.neutral} name="Variance %" />
            <Line 
              yAxisId="right"
              type="monotone" 
              dataKey="baseline" 
              stroke={colors.baseline} 
              strokeWidth={2}
              name="Baseline"
            />
            <Line 
              yAxisId="right"
              type="monotone" 
              dataKey="projected" 
              stroke={colors.projected} 
              strokeWidth={2}
              name="AI Projected"
            />
            <Line 
              yAxisId="right"
              type="monotone" 
              dataKey="actual" 
              stroke={colors.actual} 
              strokeWidth={2}
              name="Actual"
              connectNulls={false}
            />
          </ComposedChart>
        )}
      </ResponsiveContainer>
    </div>
  );

  // Render metrics comparison chart
  const renderComparisonChart = () => (
    <div className={styles.chartContainer}>
      <div className={styles.chartHeader}>
        <h4>Metrics Performance Comparison</h4>
      </div>

      <ResponsiveContainer width="100%" height={400}>
        <BarChart data={comparisonData} margin={{ top: 20, right: 30, left: 20, bottom: 60 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis 
            dataKey="name" 
            angle={-45}
            textAnchor="end"
            height={80}
            interval={0}
          />
          <YAxis />
          <Tooltip 
            content={({ active, payload, label }) => {
              if (active && payload && payload.length) {
                const data = payload[0].payload;
                return (
                  <div className={styles.customTooltip}>
                    <p className={styles.tooltipLabel}>{data.fullName}</p>
                    <p>Category: {data.category}</p>
                    <p>Impact: {data.impact}</p>
                    <p>Performance: {data.performance.toFixed(1)}%</p>
                  </div>
                );
              }
              return null;
            }}
          />
          <Legend />
          <Bar dataKey="baseline" fill={colors.baseline} name="Baseline" />
          <Bar dataKey="actual" fill={colors.actual} name="Actual" />
          <Bar dataKey="projected" fill={colors.projected} name="Projected" />
          <Bar dataKey="target" fill={colors.target} name="Target" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );

  // Render financial breakdown pie chart
  const renderFinancialBreakdown = () => (
    <div className={styles.chartContainer}>
      <div className={styles.chartHeader}>
        <h4>Financial Benefit Breakdown</h4>
        <div className={styles.totalBenefit}>
          Total: {projectInfo.currency} {financialSummary.totalBenefit.toLocaleString()}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={400}>
        <PieChart>
          <Pie
            data={financialBreakdown}
            cx="50%"
            cy="50%"
            labelLine={false}
            label={({ name, percentage }) => `${name}: ${percentage.toFixed(1)}%`}
            outerRadius={120}
            fill="#8884d8"
            dataKey="benefit"
          >
            {financialBreakdown.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={Object.values(colors)[index % Object.values(colors).length]} />
            ))}
          </Pie>
          <Tooltip content={<FinancialTooltip />} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );

  // Render performance radar chart
  const renderPerformanceRadar = () => (
    <div className={styles.chartContainer}>
      <div className={styles.chartHeader}>
        <h4>Category Performance Analysis</h4>
      </div>

      <ResponsiveContainer width="100%" height={400}>
        <RadarChart data={performanceData} margin={{ top: 20, right: 80, bottom: 20, left: 80 }}>
          <PolarGrid />
          <PolarAngleAxis dataKey="category" />
          <PolarRadiusAxis 
            angle={90} 
            domain={[0, 100]}
            tick={false}
          />
          <Radar
            name="Current Performance"
            dataKey="performance"
            stroke={colors.actual}
            fill={colors.actual}
            fillOpacity={0.3}
            strokeWidth={2}
          />
          <Radar
            name="Target Performance"
            dataKey="target"
            stroke={colors.target}
            fill={colors.target}
            fillOpacity={0.1}
            strokeWidth={2}
            strokeDasharray="5 5"
          />
          <Legend />
          <Tooltip 
            content={({ active, payload }) => {
              if (active && payload && payload.length) {
                const data = payload[0].payload;
                return (
                  <div className={styles.customTooltip}>
                    <p className={styles.tooltipLabel}>{data.category}</p>
                    <p>Metrics Count: {data.count}</p>
                    <p>Performance: {(data.performance - 50).toFixed(1)}%</p>
                    <p>Target: {(data.target - 50).toFixed(1)}%</p>
                  </div>
                );
              }
              return null;
            }}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );

  // Render ROI progression chart
  const renderROIProgression = () => {
    const roiData = periods.map((period, index) => {
      let cumulativeBenefit = 0;
      let cumulativeCost = projectInfo.totalInvestment / periods.length * (index + 1);

      metrics.forEach(metric => {
        for (let i = 0; i <= index; i++) {
          const baseline = metric.baseline[i];
          const projected = metric.projected[i];
          const improvement = projected - baseline;
          const benefit = improvement * metric.costPerUnit;
          
          if (metric.financialImpact === 'Cost Reduction' && improvement < 0) {
            cumulativeBenefit += Math.abs(benefit);
          } else if (metric.financialImpact === 'Revenue Increase' && improvement > 0) {
            cumulativeBenefit += benefit;
          } else if (metric.financialImpact === 'Cost Avoidance' && improvement > 0) {
            cumulativeBenefit += benefit;
          }
        }
      });

      const roi = cumulativeCost > 0 ? ((cumulativeBenefit - cumulativeCost) / cumulativeCost * 100) : 0;
      const paybackAchieved = cumulativeBenefit >= cumulativeCost;

      return {
        period,
        cumulativeBenefit,
        cumulativeCost,
        netBenefit: cumulativeBenefit - cumulativeCost,
        roi,
        paybackAchieved
      };
    });

    return (
      <div className={styles.chartContainer}>
        <div className={styles.chartHeader}>
          <h4>ROI Progression & Payback Analysis</h4>
        </div>

        <ResponsiveContainer width="100%" height={400}>
          <ComposedChart data={roiData} margin={{ top: 20, right: 30, left: 20, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="period" />
            <YAxis yAxisId="left" />
            <YAxis yAxisId="right" orientation="right" />
            <Tooltip 
              content={({ active, payload, label }) => {
                if (active && payload && payload.length) {
                  const data = payload[0].payload;
                  return (
                    <div className={styles.customTooltip}>
                      <p className={styles.tooltipLabel}>{label}</p>
                      <p>Cumulative Benefit: {projectInfo.currency} {data.cumulativeBenefit.toLocaleString()}</p>
                      <p>Cumulative Cost: {projectInfo.currency} {data.cumulativeCost.toLocaleString()}</p>
                      <p>Net Benefit: {projectInfo.currency} {data.netBenefit.toLocaleString()}</p>
                      <p>ROI: {data.roi.toFixed(1)}%</p>
                      <p>Payback: {data.paybackAchieved ? 'Achieved' : 'Not Yet'}</p>
                    </div>
                  );
                }
                return null;
              }}
            />
            <Legend />
            <Area 
              yAxisId="left"
              type="monotone" 
              dataKey="cumulativeBenefit" 
              fill={colors.positive}
              fillOpacity={0.3}
              stroke={colors.positive}
              name="Cumulative Benefit"
            />
            <Area 
              yAxisId="left"
              type="monotone" 
              dataKey="cumulativeCost" 
              fill={colors.negative}
              fillOpacity={0.3}
              stroke={colors.negative}
              name="Cumulative Cost"
            />
            <Line 
              yAxisId="right"
              type="monotone" 
              dataKey="roi" 
              stroke={colors.baseline}
              strokeWidth={3}
              name="ROI %"
            />
            <ReferenceLine yAxisId="right" y={0} stroke="#666" strokeDasharray="2 2" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    );
  };

  return (
    <div className={styles.chartsContainer}>
      <div className={styles.chartTabs}>
        <button 
          className={`${styles.tabBtn} ${activeChart === 'trend' ? styles.active : ''}`}
          onClick={() => setActiveChart('trend')}
        >
          <i className="fas fa-chart-line"></i> Trend Analysis
        </button>
        <button 
          className={`${styles.tabBtn} ${activeChart === 'comparison' ? styles.active : ''}`}
          onClick={() => setActiveChart('comparison')}
        >
          <i className="fas fa-chart-bar"></i> Comparison
        </button>
        <button 
          className={`${styles.tabBtn} ${activeChart === 'financial' ? styles.active : ''}`}
          onClick={() => setActiveChart('financial')}
        >
          <i className="fas fa-chart-pie"></i> Financial
        </button>
        <button 
          className={`${styles.tabBtn} ${activeChart === 'performance' ? styles.active : ''}`}
          onClick={() => setActiveChart('performance')}
        >
          <i className="fas fa-radar-chart"></i> Performance
        </button>
        <button 
          className={`${styles.tabBtn} ${activeChart === 'roi' ? styles.active : ''}`}
          onClick={() => setActiveChart('roi')}
        >
          <i className="fas fa-chart-area"></i> ROI Progress
        </button>
      </div>

      <div className={styles.chartContent}>
        {activeChart === 'trend' && renderTrendChart()}
        {activeChart === 'comparison' && renderComparisonChart()}
        {activeChart === 'financial' && renderFinancialBreakdown()}
        {activeChart === 'performance' && renderPerformanceRadar()}
        {activeChart === 'roi' && renderROIProgression()}
      </div>
    </div>
  );
};

export default FinYCharts;

