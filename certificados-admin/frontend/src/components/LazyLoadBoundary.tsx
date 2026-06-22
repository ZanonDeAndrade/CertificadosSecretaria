import { Component, ErrorInfo, ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  failed: boolean;
}

export default class LazyLoadBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Falha ao carregar módulo do editor", error, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return (
        <section role="alert" className="rounded-3xl border border-rose-200 bg-rose-50 p-6">
          <h2 className="font-semibold text-rose-900">Não foi possível carregar o editor.</h2>
          <p className="mt-1 text-sm text-rose-800">Verifique a conexão e tente novamente.</p>
          <button
            type="button"
            onClick={() => this.setState({ failed: false })}
            className="mt-4 rounded-full bg-rose-700 px-4 py-2 text-sm font-semibold text-white"
          >
            Tentar novamente
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}
