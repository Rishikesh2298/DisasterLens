type Matrix = Record<string, Record<string, number>>;

export function ConfusionMatrix({ matrix }: { matrix: Matrix }) {
  const classes = Object.keys(matrix);
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Road-status confusion matrix</h2>
          <p>Rows are ground truth; columns are model answers.</p>
        </div>
      </div>
      {classes.length ? (
        <div className="matrix-scroll">
          <table className="matrix-table">
            <thead>
              <tr>
                <th>Truth ↓ / Pred. →</th>
                {classes.map((label) => (
                  <th key={label}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {classes.map((actual) => (
                <tr key={actual}>
                  <th>{actual}</th>
                  {classes.map((predicted) => {
                    const count = matrix[actual]?.[predicted] ?? 0;
                    return (
                      <td
                        className={
                          actual === predicted && count
                            ? "matrix-hit"
                            : count
                              ? "matrix-error"
                              : ""
                        }
                        key={predicted}
                      >
                        {count}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty-state">
          No road-status examples were included in this run.
        </p>
      )}
    </section>
  );
}
