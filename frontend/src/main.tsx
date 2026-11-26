import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import RouteApp from "./App";
import BenchmarkApp from "./ui/App";
import "./index.css";
import "./ui/styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/benchmark" element={<BenchmarkApp />} />
          <Route path="/compare" element={<BenchmarkApp />} />
          <Route path="/failures" element={<BenchmarkApp />} />
          <Route path="*" element={<RouteApp />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
