import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    if (typeof this.props.onError === 'function') {
      this.props.onError(error, info);
    }
    console.error('ErrorBoundary caught:', error, info);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
    if (typeof this.props.onRetry === 'function') {
      this.props.onRetry();
    }
  };

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    const title = this.props.title || 'Something went wrong';
    const message = this.state.error?.message || this.props.message || 'This section hit an unexpected error.';

    return (
      <div
        style={{
          border: '1px solid rgba(239, 68, 68, 0.2)',
          background: '#fff5f5',
          borderRadius: 18,
          padding: '18px 20px',
          display: 'grid',
          gap: 10,
        }}
        role="alert"
      >
        <strong style={{ color: '#7f1d1d', fontSize: 18 }}>{title}</strong>
        <span style={{ color: '#991b1b' }}>{message}</span>
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="button"
            onClick={this.handleRetry}
            style={{
              border: 0,
              borderRadius: 999,
              background: '#161f3b',
              color: '#fff',
              fontWeight: 600,
              padding: '10px 16px',
              cursor: 'pointer',
            }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }
}
