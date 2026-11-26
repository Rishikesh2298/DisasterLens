import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import {
  getFailures,
  getRun,
  getScene,
  listRuns,
  mocksEnabled,
} from "../api/client";
import {
  BenchmarkOverview,
  ModelComparison,
} from "../features/benchmark/BenchmarkOverview";
import { FailureBrowser } from "../features/failures/FailureBrowser";
import type { Failure } from "../types";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export default function App() {
  const location = useLocation();
  const page =
    location.pathname === "/failures"
      ? "failures"
      : location.pathname === "/compare"
        ? "compare"
        : "overview";
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedFailure, setSelectedFailure] = useState<Failure | null>(null);
  const [category, setCategory] = useState("all");
  const [difficulty, setDifficulty] = useState("all");
  const [mock, setMock] = useState(mocksEnabled);

  const runIndex = useQuery({
    queryKey: ["runs", mocksEnabled],
    queryFn: listRuns,
  });
  const runOptions = runIndex.data?.runs ?? [];
  useEffect(() => {
    if (
      runOptions.length &&
      !runOptions.some((item) => item.id === selectedRunId)
    ) {
      setSelectedRunId(runOptions[0].id);
    }
  }, [runOptions, selectedRunId]);

  const activeRunId = selectedRunId || runOptions[0]?.id || "";
  const runQuery = useQuery({
    queryKey: ["run", mocksEnabled, activeRunId],
    queryFn: () => getRun(activeRunId),
    enabled: Boolean(activeRunId),
  });
  const failureQuery = useQuery({
    queryKey: ["failures", mocksEnabled, activeRunId],
    queryFn: () => getFailures(activeRunId),
    enabled: Boolean(activeRunId),
  });
  const comparisonQueries = useQueries({
    queries: runOptions.map((item) => ({
      queryKey: ["run", mocksEnabled, item.id],
      queryFn: () => getRun(item.id),
    })),
  });
  const comparisonRuns = comparisonQueries.flatMap((query) =>
    query.data ? [query.data] : [],
  );

  const failures = failureQuery.data ?? [];
  const categories = useMemo(
    () => [...new Set(failures.map((item) => item.category))].sort(),
    [failures],
  );
  const difficulties = useMemo(
    () =>
      [
        ...new Set(
          failures
            .map((item) => item.difficulty)
            .filter((x): x is string => Boolean(x)),
        ),
      ].sort(),
    [failures],
  );
  const filteredFailures = failures.filter(
    (item) =>
      (category === "all" || item.category === category) &&
      (difficulty === "all" || item.difficulty === difficulty),
  );
  const sceneQuery = useQuery({
    queryKey: ["scene", mocksEnabled, activeRunId, selectedFailure?.scene_id],
    queryFn: () => getScene(activeRunId, selectedFailure!.scene_id),
    enabled: page === "failures" && Boolean(activeRunId && selectedFailure),
  });
  const run = runQuery.data;

  const exportCsv = () => {
    if (!run) return;
    const lines = [
      "task,metric,value",
      ...Object.entries(run.metrics).flatMap(([task, item]) =>
        Object.entries(item.metrics).map(
          ([key, value]) => `${task},${key},${value ?? ""}`,
        ),
      ),
    ];
    lines.push(
      `route_impact,unsafe_route_rate,${run.route_impact.unsafe_route_rate ?? ""}`,
    );
    lines.push(
      `route_impact,unnecessary_detour_rate,${run.route_impact.unnecessary_detour_rate ?? ""}`,
    );
    const link = document.createElement("a");
    link.href = URL.createObjectURL(
      new Blob([lines.join("\n")], { type: "text/csv" }),
    );
    link.download = `${run.run_name}-metrics.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const setFilters = (kind: "category" | "difficulty", value: string) => {
    if (kind === "category") setCategory(value);
    else setDifficulty(value);
    setSelectedFailure(null);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">D</span>
          <span>
            DisasterLens<small>RESEARCH BENCHMARK</small>
          </span>
        </div>
        <div className="side-label">WORKSPACE</div>
        <Link
          className={`nav-item ${page === "overview" ? "active" : ""}`}
          to="/benchmark"
        >
          <span>◫</span> Benchmark
        </Link>
        <Link
          className={`nav-item ${page === "compare" ? "active" : ""}`}
          to="/compare"
        >
          <span>▤</span> Model comparison
        </Link>
        <Link
          className={`nav-item ${page === "failures" ? "active" : ""}`}
          to="/failures"
        >
          <span>⌁</span> Failure browser <b>{failures.length}</b>
        </Link>
        <div className="side-label secondary">COMING NEXT</div>
        <div className="nav-muted">◉ &nbsp; Scene viewer</div>
        <div className="nav-muted">⌖ &nbsp; Route finder</div>
        <div className="sidebar-foot">
          <span className="pulse" /> Local workspace
          <small>v0.1.0 · Contracts frozen</small>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="breadcrumbs">
            Workspace <span>/</span>{" "}
            {page === "overview"
              ? "Benchmark"
              : page === "compare"
                ? "Model comparison"
                : "Failure browser"}
          </div>
          <div className="header-actions">
            {runOptions.length > 1 && (
              <label className="run-picker">
                Run
                <select
                  value={activeRunId}
                  onChange={(event) => {
                    setSelectedRunId(event.target.value);
                    setSelectedFailure(null);
                  }}
                >
                  {runOptions.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.model_id} · {item.split}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="switch-label">
              Mock data
              <input
                type="checkbox"
                checked={mock}
                onChange={(event) => {
                  setMock(event.target.checked);
                  window.location.search = event.target.checked
                    ? "?mock=true"
                    : "?mock=false";
                }}
              />
              <span className="switch" />
            </label>
            <button className="avatar" aria-label="Rishikesh">
              R
            </button>
          </div>
        </header>
        <div className="content">
          <div className="safety">
            <span>ⓘ</span>
            <div>
              <strong>Synthetic scenes only</strong>
              <span>
                Research prototype. Results do not describe real disaster
                performance and are not emergency guidance.
              </span>
            </div>
            <span className="safety-lock">RESEARCH USE</span>
          </div>
          {runIndex.isError && (
            <div className="error">
              Could not load runs: {errorMessage(runIndex.error)}
            </div>
          )}
          {runQuery.isError && (
            <div className="error">
              Could not load results: {errorMessage(runQuery.error)}
            </div>
          )}
          {runIndex.isLoading || runQuery.isLoading ? (
            <div className="loading">Loading benchmark results…</div>
          ) : (
            run && (
              <>
                <div className="page-heading">
                  <div>
                    <div className="eyebrow">
                      EVALUATION / {run.split.toUpperCase()}
                    </div>
                    <h1>
                      {page === "overview"
                        ? "Benchmark overview"
                        : page === "compare"
                          ? "Model comparison"
                          : "Failure browser"}
                    </h1>
                    <p>
                      {page === "failures"
                        ? "Inspect model errors against per-scene ground truth."
                        : "Measure model predictions against exact synthetic-scene ground truth."}
                    </p>
                  </div>
                  <div className="heading-actions">
                    {run.is_mock && (
                      <span className="badge mock">MOCK RUN</span>
                    )}
                    {!mock && <span className="badge api-badge">API DATA</span>}
                    <button className="secondary-button" onClick={exportCsv}>
                      ↓ &nbsp; Export CSV
                    </button>
                  </div>
                </div>
                <div className="run-strip">
                  <span className="run-dot" />
                  <div>
                    <b>{run.model_id}</b>
                    <span>
                      Run {run.run_name} · {run.scene_count} scenes · Updated{" "}
                      {new Date(run.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <span className="split-badge">{run.split} set</span>
                </div>
                {page === "overview" && (
                  <BenchmarkOverview
                    run={run}
                    runs={comparisonRuns.filter(
                      (item) => item.split === run.split,
                    )}
                  />
                )}
                {page === "compare" && (
                  <ModelComparison
                    runs={comparisonRuns.filter(
                      (item) => item.split === run.split,
                    )}
                  />
                )}
                {page === "failures" && (
                  <FailureBrowser
                    failures={filteredFailures}
                    categories={categories}
                    difficulties={difficulties}
                    category={category}
                    difficulty={difficulty}
                    selected={selectedFailure}
                    scene={sceneQuery.data}
                    sceneLoading={sceneQuery.isLoading}
                    sceneError={
                      sceneQuery.isError
                        ? errorMessage(sceneQuery.error)
                        : undefined
                    }
                    onCategory={(value) => setFilters("category", value)}
                    onDifficulty={(value) => setFilters("difficulty", value)}
                    onSelect={setSelectedFailure}
                  />
                )}
                <footer>
                  DISASTERLENS <span>·</span> SYNTHETIC DATA RESEARCH{" "}
                  <span>·</span> NO REAL-WORLD SAFETY CLAIMS
                </footer>
              </>
            )
          )}
          {!runIndex.isLoading && !runIndex.isError && !runOptions.length && (
            <div className="empty-state">
              No evaluated runs yet. Run the sample benchmark or add run folders
              under `results/`.
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
