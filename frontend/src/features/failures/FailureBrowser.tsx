import type { Failure, SceneRecord } from "../../types";
import { SceneComparison } from "../../ui/components/SceneComparison";

export function FailureBrowser({
  failures,
  categories,
  difficulties,
  category,
  difficulty,
  selected,
  scene,
  sceneLoading,
  sceneError,
  onCategory,
  onDifficulty,
  onSelect,
}: {
  failures: Failure[];
  categories: string[];
  difficulties: string[];
  category: string;
  difficulty: string;
  selected: Failure | null;
  scene: SceneRecord | undefined;
  sceneLoading: boolean;
  sceneError: string | undefined;
  onCategory: (value: string) => void;
  onDifficulty: (value: string) => void;
  onSelect: (failure: Failure) => void;
}) {
  return (
    <div className="failure-browser">
      <section className="panel failures-panel">
        <div className="panel-head">
          <div>
            <h2>Model errors</h2>
            <p>
              {failures.length} matched examples from this run. Select one to
              compare predictions with truth.
            </p>
          </div>
          <div className="filter-row">
            <label>
              Category{" "}
              <select
                value={category}
                onChange={(event) => onCategory(event.target.value)}
              >
                <option value="all">All categories</option>
                {categories.map((item) => (
                  <option key={item} value={item}>
                    {item.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Difficulty{" "}
              <select
                value={difficulty}
                onChange={(event) => onDifficulty(event.target.value)}
              >
                <option value="all">All levels</option>
                {difficulties.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
          </div>
        </div>
        {failures.length ? (
          <div className="failure-list">
            <div className="table-row table-header failure-row">
              <span>Scene</span>
              <span>Failure category</span>
              <span>Prediction → truth</span>
            </div>
            {failures.map((failure, index) => (
              <button
                className={`table-row failure-row ${selected?.scene_id === failure.scene_id ? "selected" : ""}`}
                key={`${failure.scene_id}-${index}`}
                onClick={() => onSelect(failure)}
              >
                <span>
                  <b>{failure.scene_id}</b>
                  <small>{failure.difficulty ?? "unrated"} difficulty</small>
                </span>
                <span className="failure-tag">
                  {failure.category.replaceAll("_", " ")}
                </span>
                <span className="failure-answer">
                  <code>
                    {JSON.stringify(failure.prediction)} →{" "}
                    {JSON.stringify(failure.truth)}
                  </code>
                </span>
              </button>
            ))}
          </div>
        ) : (
          <p className="empty-state">
            No failures match these filters. For a perfect oracle run, this is
            expected.
          </p>
        )}
      </section>
      {selected && (
        <>
          {sceneLoading && (
            <section className="panel loading">Loading scene evidence…</section>
          )}
          {sceneError && (
            <section className="panel error">
              Could not load scene {selected.scene_id}: {sceneError}
            </section>
          )}
          {scene && <SceneComparison scene={scene} />}
        </>
      )}
    </div>
  );
}
