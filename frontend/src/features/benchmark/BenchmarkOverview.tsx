import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Run } from "../../types";
import { ConfusionMatrix } from "../../ui/components/ConfusionMatrix";
import { MetricCard } from "../../ui/components/MetricCard";

const taskLabels: Record<string, string> = {
  detection: "Hazard detection",
  segments: "Road status",
  counts: "Building count",
  water: "Standing water",
  routes: "Route obstruction",
  zones: "Zone comparison",
  calibration: "Confidence calibration",
  reliability: "Output reliability",
};
const percent = (value: number | null | undefined) =>
  value == null ? "—" : `${(value * 100).toFixed(1)}%`;

function primaryScore(run: Run, task: string) {
  const metrics = run.metrics[task]?.metrics;
  if (!metrics) return 0;
  return (
    metrics.f1 ??
    metrics.macro_f1 ??
    metrics.accuracy ??
    metrics.exact_match ??
    0
  );
}

export function BenchmarkOverview({ run, runs }: { run: Run; runs: Run[] }) {
  const taskData = [
    "detection",
    "segments",
    "counts",
    "water",
    "routes",
    "zones",
  ]
    .filter((key) => run.metrics[key])
    .map((key) => ({ task: taskLabels[key], score: primaryScore(run, key) }));
  const difficultyData = Object.entries(
    run.route_impact.by_difficulty ?? {},
  ).map(([difficulty, data]) => ({
    difficulty,
    unsafe: data.unsafe_rate ?? 0,
  }));
  const matrix = (run.metrics.segments?.details.confusion_matrix ??
    {}) as Record<string, Record<string, number>>;

  return (
    <>
      <section className="metrics-grid">
        <MetricCard
          title="Road-status macro F1"
          value={percent(run.metrics.segments?.metrics.macro_f1)}
          note="Across represented road classes"
          icon="◈"
        />
        <MetricCard
          title="False-clear share"
          value={percent(run.metrics.segments?.metrics.false_clear_rate)}
          note="Blocked roads predicted clear / all roads"
          icon="⊘"
          tone="amber"
        />
        <MetricCard
          title="Unsafe route rate"
          value={percent(run.route_impact.unsafe_route_rate)}
          note="Predicted paths crossing true blockages"
          icon="⌖"
          tone="red"
        />
        <MetricCard
          title="Valid JSON rate"
          value={percent(run.metrics.reliability?.metrics.valid_json_rate)}
          note="Structured responses parsed"
          icon="◎"
        />
      </section>
      <section className="panel chart-panel">
        <div className="panel-head">
          <div>
            <h2>Task performance</h2>
            <p>Primary F1 or accuracy by task.</p>
          </div>
          <span className="legend">
            <i />
            {run.model_id}
          </span>
        </div>
        <div className="chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={taskData}
              margin={{ top: 10, right: 12, left: -15, bottom: 4 }}
            >
              <CartesianGrid
                strokeDasharray="3 5"
                vertical={false}
                stroke="#e9eeeb"
              />
              <XAxis
                dataKey="task"
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#718078", fontSize: 11 }}
              />
              <YAxis
                domain={[0, 1]}
                tickFormatter={(v) => `${Math.round(v * 100)}%`}
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#87938d", fontSize: 11 }}
              />
              <Tooltip formatter={(v: number) => percent(v)} />
              <Bar
                dataKey="score"
                fill="#267a59"
                radius={[5, 5, 0, 0]}
                maxBarSize={46}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
      <div className="lower-grid">
        <section className="panel comparison">
          <div className="panel-head">
            <div>
              <h2>Evaluation metrics</h2>
              <p>Selected run summary by task.</p>
            </div>
            <span className="text-link">{run.scene_count} SCENES</span>
          </div>
          <div className="metric-table">
            <div className="table-row table-header">
              <span>Task</span>
              <span>Primary score</span>
              <span>Additional signal</span>
            </div>
            {Object.entries(run.metrics)
              .filter(([key]) => taskLabels[key])
              .map(([key, metric]) => (
                <div className="table-row" key={key}>
                  <span className="task-name">
                    <i className="task-icon">
                      {key === "segments"
                        ? "⌖"
                        : key === "counts"
                          ? "▦"
                          : key === "calibration"
                            ? "◌"
                            : key === "reliability"
                              ? "✓"
                              : "◉"}
                    </i>
                    {taskLabels[key]}
                  </span>
                  <strong>
                    {key === "calibration"
                      ? (metric.metrics.brier_score?.toFixed(3) ?? "—")
                      : percent(
                          key === "reliability"
                            ? metric.metrics.valid_json_rate
                            : primaryScore(run, key),
                        )}
                  </strong>
                  <span className="muted-cell">
                    {key === "segments"
                      ? `${percent(metric.metrics.false_clear_rate)} false clear`
                      : key === "calibration"
                        ? "Brier score · lower is better"
                        : key === "reliability"
                          ? metric.metrics.mean_latency_ms == null
                            ? "Latency n/a"
                            : `${metric.metrics.mean_latency_ms.toFixed(0)} ms average`
                          : `${metric.metrics.count ?? run.scene_count} answers`}
                  </span>
                </div>
              ))}
          </div>
        </section>
        <section className="panel impact">
          <div className="panel-head">
            <div>
              <h2>Route impact</h2>
              <p>How predictions change path choices.</p>
            </div>
            <span className="impact-icon">⌖</span>
          </div>
          <div className="impact-stat">
            <b>{percent(run.route_impact.unsafe_route_rate)}</b>
            <span>unsafe route rate</span>
          </div>
          <div className="impact-line">
            <span>Unnecessary detour rate</span>
            <b>{percent(run.route_impact.unnecessary_detour_rate)}</b>
          </div>
          <div className="impact-line">
            <span>Mean extra distance</span>
            <b>
              {(run.route_impact.mean_extra_distance_percent ?? 0).toFixed(1)}%
            </b>
          </div>
          <div className="impact-note">
            A route is flagged when it uses a road segment marked blocked by
            ground truth.
          </div>
        </section>
      </div>
      <div className="lower-grid difficulty-grid">
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Route impact by difficulty</h2>
              <p>Unsafe-route rate for each scene level.</p>
            </div>
          </div>
          {difficultyData.length ? (
            <div className="chart compact">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={difficultyData}
                  margin={{ top: 8, right: 8, left: -18, bottom: 0 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 5"
                    vertical={false}
                    stroke="#e9eeeb"
                  />
                  <XAxis
                    dataKey="difficulty"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "#718078", fontSize: 10 }}
                  />
                  <YAxis
                    domain={[0, 1]}
                    tickFormatter={(v) => `${Math.round(v * 100)}%`}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "#87938d", fontSize: 10 }}
                  />
                  <Tooltip formatter={(v: number) => percent(v)} />
                  <Bar
                    dataKey="unsafe"
                    name="Unsafe route rate"
                    fill="#bd6957"
                    radius={[4, 4, 0, 0]}
                    maxBarSize={48}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="empty-state">
              No route-by-difficulty measurements are available.
            </p>
          )}
        </section>
        <section className="panel baseline-preview">
          <div className="panel-head">
            <div>
              <h2>Model vs baselines</h2>
              <p>Runs in the {run.split} split.</p>
            </div>
          </div>
          {runs.length > 1 ? (
            <div className="metric-table">
              <div className="table-row baseline-row table-header">
                <span>Run</span>
                <span>Road macro F1</span>
                <span>Route impact</span>
              </div>
              {runs.map((item) => (
                <div
                  className="table-row baseline-row"
                  key={item.id ?? item.run_name}
                >
                  <span>
                    {item.model_id}
                    {item.is_mock && <small>MOCK</small>}
                  </span>
                  <strong>
                    {percent(item.metrics.segments?.metrics.macro_f1)}
                  </strong>
                  <span>{percent(item.route_impact.unsafe_route_rate)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-state">
              Only one run is available in this split. Add model and baseline
              run folders to compare results.
            </p>
          )}
        </section>
      </div>
      <ConfusionMatrix matrix={matrix} />
    </>
  );
}

export function ModelComparison({ runs }: { runs: Run[] }) {
  const tasks = ["detection", "segments", "counts", "water", "routes", "zones"];
  return (
    <section className="panel compare-page">
      <div className="panel-head">
        <div>
          <h2>Model and baseline comparison</h2>
          <p>Side-by-side scores for runs available in the selected split.</p>
        </div>
        <span className="split-badge">{runs[0]?.split ?? "no"} SET</span>
      </div>
      {runs.length > 1 ? (
        <div className="compare-scroll">
          <table className="compare-table">
            <thead>
              <tr>
                <th>Task / metric</th>
                {runs.map((run) => (
                  <th key={run.id ?? run.run_name}>
                    {run.model_id}
                    {run.is_mock && <small> MOCK</small>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task}>
                  <th>{taskLabels[task]}</th>
                  {runs.map((run) => (
                    <td key={run.id ?? run.run_name}>
                      {percent(primaryScore(run, task))}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <th>False-clear share</th>
                {runs.map((run) => (
                  <td key={run.id ?? run.run_name}>
                    {percent(run.metrics.segments?.metrics.false_clear_rate)}
                  </td>
                ))}
              </tr>
              <tr>
                <th>Unsafe route rate</th>
                {runs.map((run) => (
                  <td key={run.id ?? run.run_name}>
                    {percent(run.route_impact.unsafe_route_rate)}
                  </td>
                ))}
              </tr>
              <tr>
                <th>Unnecessary detour</th>
                {runs.map((run) => (
                  <td key={run.id ?? run.run_name}>
                    {percent(run.route_impact.unnecessary_detour_rate)}
                  </td>
                ))}
              </tr>
              <tr>
                <th>Valid JSON rate</th>
                {runs.map((run) => (
                  <td key={run.id ?? run.run_name}>
                    {percent(run.metrics.reliability?.metrics.valid_json_rate)}
                  </td>
                ))}
              </tr>
              <tr>
                <th>Brier score ↓</th>
                {runs.map((run) => (
                  <td key={run.id ?? run.run_name}>
                    {run.metrics.calibration?.metrics.brier_score?.toFixed(3) ??
                      "—"}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty-state">
          A comparison needs at least two runs in the same split. Mock mode
          includes illustrative model and baseline runs.
        </p>
      )}
    </section>
  );
}
