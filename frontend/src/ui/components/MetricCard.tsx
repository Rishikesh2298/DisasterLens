export function MetricCard({
  title,
  value,
  note,
  icon,
  tone = "green",
}: {
  title: string;
  value: string;
  note: string;
  icon: string;
  tone?: string;
}) {
  return (
    <article className="metric-card">
      <div className="metric-top">
        <span>{title}</span>
        <i className={`metric-icon ${tone}`}>{icon}</i>
      </div>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}
