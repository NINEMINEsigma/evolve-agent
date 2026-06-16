import { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("[ErrorBoundary]", error, errorInfo);
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div className="error-boundary">
          <div className="error-boundary-box">
            <h2>界面渲染出错</h2>
            <p>某个组件渲染失败，导致页面异常。点击刷新恢复。</p>
            <pre className="error-boundary-detail">
              {this.state.error?.message ?? "unknown error"}
            </pre>
            <button onClick={this.handleReload}>刷新页面</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
