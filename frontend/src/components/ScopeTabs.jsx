import { SCOPES } from "../lib/presentation.js";
import Icon from "./Icon.jsx";

export default function ScopeTabs({ filters, onChange }) {
  return (
    <div className="scope-tabs" role="group" aria-label="CCF 级别与出版类型">
      {SCOPES.map((scope) => {
        const selected = filters.level === scope.level && filters.type === scope.type;
        return <button key={scope.id} className={`scope-tab ${selected ? "active" : ""}`}
          aria-label={scope.label} aria-pressed={selected} onClick={() => onChange({ level: scope.level, type: scope.type, venue: "" })}>
          {scope.id === "all" ? <Icon name="layers" size={15} /> : <span aria-hidden="true" className={`level-mark level-${scope.level.toLowerCase()}`}>{scope.level}</span>}
          {scope.label}
        </button>;
      })}
    </div>
  );
}
