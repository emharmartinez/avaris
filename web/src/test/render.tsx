import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";

// Fresh query cache per test, no retries; a wrapper, so rerender keeps the providers
export function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>
        <TooltipProvider>{children}</TooltipProvider>
      </QueryClientProvider>
    ),
  });
}
