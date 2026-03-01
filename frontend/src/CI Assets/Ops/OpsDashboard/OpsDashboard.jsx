import React from 'react';
import styles from './OpsDashboard.module.css';

const OpsDashboard = () => {
  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Operations Dashboard</h1>
      <p>This will serve as the central hub for ops-related visualizations and tools.</p>
    </div>
  );
};

export default OpsDashboard;
