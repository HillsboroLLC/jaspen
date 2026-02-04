// path: src/ErrorBoundary.jsx
import React from "react";

function serializeError(err) {
  if (!err) return "Unknown error";
  const obj = {};
  Object.getOwnPropertyNames(err).forEach(k => { obj[k] = err[k]; });
  obj.name = err.name || "Error";
  obj.message = err.message || String(err);
  return JSON.stringify(obj, null, 2);
}

export default class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null, info: null }; }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  componentDidCatch(error, info) { console.error("ErrorBoundary caught:", error, info); this.setState({ info }); }
  componentDidMount() {
    this._onError = (msg, src, line, col, err) => { console.error("window.onerror:", msg, src, line, col, err); this.setState({ hasError: true, error: err || new Error(String(msg)) }); };
    this._onRejection = e => { console.error("unhandledrejection:", e.reason); this.setState({ hasError: true, error: e.reason || new Error("Unhandled promise rejection") }); };
    window.addEventListener("error", this._onError);
    window.addEventListener("unhandledrejection", this._onRejection);
  }
  componentWillUnmount() {
    window.removeEventListener("error", this._onError);
    window.removeEventListener("unhandledrejection", this._onRejection);
  }
  render() {
    if (this.state.hasError) {
      const detail = serializeError(this.state.error);
      const comp = this.state.info?.componentStack || "";
      return (
        <div style={{padding:16,fontFamily:"system-ui",maxWidth:900,margin:"0 auto"}}>
          <h2>App crashed</h2>
          <p>Detail:</p>
          <pre style={{whiteSpace:"pre-wrap",background:"#f6f8fa",padding:12,borderRadius:8}}>{detail}</pre>
          {comp && (<><p>Component stack:</p><pre style={{whiteSpace:"pre-wrap",background:"#f6f8fa",padding:12,borderRadius:8}}>{comp}</pre></>)}
        </div>
      );
    }
    return this.props.children;
  }
}
