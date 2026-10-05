import { Component, Suspense, type ErrorInfo, type ReactNode } from 'react';
import { useLocation } from 'react-router';

import { ErrorPage } from './ErrorPage';
import { PageLoading } from './PageLoading';

interface BoundaryProps {
  children: ReactNode;
}

class ErrorBoundary extends Component<BoundaryProps, { error: unknown }> {
  state = { error: null as unknown };

  static getDerivedStateFromError(error: unknown) {
    return { error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('A page failed to render', error, info.componentStack);
  }

  render() {
    if (this.state.error) return <ErrorPage error={this.state.error} />;
    return this.props.children;
  }
}

/**
 * Wraps a route's page: shows a loading line while its code downloads (route-based
 * code splitting) and an error page if it fails to load or render. Moving to
 * another page clears the error.
 */
export function RouteBoundary({ children }: BoundaryProps) {
  const { pathname } = useLocation();
  return (
    <ErrorBoundary key={pathname}>
      <Suspense fallback={<PageLoading />}>{children}</Suspense>
    </ErrorBoundary>
  );
}
