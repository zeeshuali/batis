import React, { useEffect, useState } from "react";
import { useSelection } from "../../context/SelectionContext";
import { api } from "../../lib/api";
import {
  KpiCard, Spinner, EmptyState, SectionError,
} from "../../components/primitives";
import { SectionMap } from "../../components/SectionMap";
import "../sections.css";
import "./planning.css";

interface ScenarioStop { lat: number; lng: number; label?: string | null; }
interface ScenarioRow {
  id: number;
  name: string;
  description: string | null;
  stops: ScenarioStop[];
  frequency_min: number;
  agency_id: string | null;
  created_at: string;
  updated_at: string;
}
interface ScenarioImpact {
  scenario_id: number;
  stop_count: number;
  frequency_min: number;
  newly_covered_cells: number;
  newly_covered_population: number;
  newly_covered_high_need: number;
  by_tier: { very_high: number; high: number; medium: number; low: number };
  baseline_covered_cells: number;
  scenario_covered_cells: number;
}

/** Scenarios — the what-if simulator. Each map click in this mode appends
 *  to selection.scenarioStops (handled by MapView). The editor lets the
 *  user name the scenario, set a peak headway, and POST it to /scenarios.
 *  After save, the impact endpoint returns the coverage / equity delta
 *  using the same radius-coverage model the Coverage page uses for
 *  baseline scoring. */
export const Scenarios: React.FC = () => {
  const { selection, addScenarioStop, removeScenarioStop, setScenarioStops } = useSelection();
  const stops = selection.scenarioStops;

  const [name, setName]                   = useState("");
  const [description, setDescription]     = useState("");
  const [frequencyMin, setFrequencyMin]   = useState(15);
  const [scenarios, setScenarios]         = useState<ScenarioRow[]>([]);
  const [impact, setImpact]               = useState<ScenarioImpact | null>(null);
  const [activeId, setActiveId]           = useState<number | null>(null);
  const [loading, setLoading]             = useState(false);
  const [saving, setSaving]               = useState(false);
  const [error, setError]                 = useState<string | null>(null);
  const [tick, setTick]                   = useState(0);

  // Load saved scenarios on mount + after each save/delete.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get<ScenarioRow[]>("/scenarios")
      .then(res => { if (!cancelled) setScenarios(Array.isArray(res.data) ? res.data : []); })
      .catch(err => { if (!cancelled) setError(err?.message ?? "Failed to load scenarios"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tick]);

  const newScenario = () => {
    setActiveId(null);
    setName("");
    setDescription("");
    setFrequencyMin(15);
    setScenarioStops([]);
    setImpact(null);
    setError(null);
  };

  const loadScenario = async (s: ScenarioRow) => {
    setActiveId(s.id);
    setName(s.name);
    setDescription(s.description ?? "");
    setFrequencyMin(s.frequency_min);
    setScenarioStops(s.stops);
    setImpact(null);
    try {
      const res = await api.get<ScenarioImpact>(`/scenarios/${s.id}/impact`);
      setImpact(res.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load impact");
    }
  };

  const save = async () => {
    if (!name.trim()) {
      setError("Name is required."); return;
    }
    setSaving(true); setError(null);
    try {
      const res = await api.post<ScenarioRow>("/scenarios", {
        name: name.trim(),
        description: description.trim() || null,
        stops: stops.map((s, i) => ({ ...s, label: `S${i + 1}` })),
        frequency_min: frequencyMin,
      });
      setActiveId(res.data.id);
      const imp = await api.get<ScenarioImpact>(`/scenarios/${res.data.id}/impact`);
      setImpact(imp.data);
      setTick(t => t + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: number) => {
    try {
      await api.delete(`/scenarios/${id}`);
      if (activeId === id) newScenario();
      setTick(t => t + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const fmtPop = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Scenarios</h2>
        <span className="section__subtitle">
          Click the map to drop hypothetical stops, set a frequency, save to see the impact
        </span>
        <button type="button" className="export-button" onClick={newScenario}>+ New scenario</button>
      </div>

      {error && <SectionError message={error} onRetry={() => { setError(null); setTick(t => t + 1); }} />}

      <div className="section__grid">
        <SectionMap mapMode="scenarios" title="Pin-on-map editor" height={480} />

        <div className="section__panel">
          <h3 className="section__panel-title">{activeId ? `Scenario #${activeId}` : "New scenario"}</h3>

          <div className="planning-scenarios__form">
            <label className="planning-scenarios__field">
              <span>Name</span>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="e.g. Telegraph Ave bus extension"
              />
            </label>
            <label className="planning-scenarios__field">
              <span>Description</span>
              <input
                type="text"
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder="optional"
              />
            </label>
            <label className="planning-scenarios__field">
              <span>Peak headway (min)</span>
              <input
                type="number"
                min={1} max={120}
                value={frequencyMin}
                onChange={e => setFrequencyMin(Number(e.target.value) || 15)}
              />
            </label>
          </div>

          <h4 className="planning-scenarios__sub-title">
            Stops <span className="planning-scenarios__count">{stops.length}</span>
          </h4>
          {stops.length === 0 ? (
            <EmptyState message="Click the map to drop your first stop." />
          ) : (
            <ul className="planning-scenarios__stops">
              {stops.map((s, i) => (
                <li key={i} className="planning-scenarios__stop">
                  <span className="planning-scenarios__stop-code">S{i + 1}</span>
                  <span className="planning-scenarios__stop-coord">
                    {s.lat.toFixed(5)}, {s.lng.toFixed(5)}
                  </span>
                  <button
                    type="button"
                    className="planning-scenarios__stop-remove"
                    onClick={() => removeScenarioStop(i)}
                    aria-label={`Remove stop ${i + 1}`}
                  >✕</button>
                </li>
              ))}
            </ul>
          )}

          <div className="planning-scenarios__actions">
            <button
              type="button"
              className="planning-scenarios__save"
              disabled={saving || stops.length === 0 || !name.trim()}
              onClick={save}
            >
              {saving ? "Saving…" : activeId ? "Save as new" : "Save scenario"}
            </button>
            <button
              type="button"
              className="planning-scenarios__clear"
              onClick={() => setScenarioStops([])}
              disabled={stops.length === 0}
            >
              Clear stops
            </button>
          </div>
        </div>
      </div>

      {impact && (
        <div className="section__kpi-strip">
          <KpiCard label="Newly covered cells"      value={String(impact.newly_covered_cells)} sub="vs baseline" />
          <KpiCard label="Newly reached residents"  value={fmtPop(impact.newly_covered_population)} />
          <KpiCard label="High-need newly served"   value={fmtPop(impact.newly_covered_high_need)} sub="very-high + high tiers" />
          <KpiCard label="Stops"                    value={String(impact.stop_count)} sub={`headway ${impact.frequency_min} min`} />
          <KpiCard label="Total scenario coverage"  value={String(impact.scenario_covered_cells)} sub="cells within 400 m of any stop" />
        </div>
      )}

      {impact && (
        <div className="section__panel">
          <h3 className="section__panel-title">Impact by equity tier</h3>
          <ul className="planning-coverage-tiers">
            {(["very_high", "high", "medium", "low"] as const).map(tier => {
              const pop = impact.by_tier[tier];
              const total = impact.newly_covered_population || 1;
              return (
                <li key={tier} className="planning-coverage-tier">
                  <span className={`planning-coverage-tier__chip planning-coverage-tier__chip--${tier}`}>
                    {tier.replace("_", " ")}
                  </span>
                  <span className="planning-coverage-tier__count">{fmtPop(pop)} residents</span>
                  <span className="planning-coverage-tier__pop"></span>
                  <span className="planning-coverage-tier__pct">{Math.round((pop / total) * 100)}%</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="section__panel">
        <h3 className="section__panel-title">
          Saved scenarios <span className="planning-scenarios__count">{scenarios.length}</span>
        </h3>
        {loading && scenarios.length === 0 ? <Spinner /> :
         scenarios.length === 0 ? (
           <EmptyState message="No saved scenarios yet." hint="Drop some stops on the map and click Save scenario." />
         ) : (
           <ul className="planning-scenarios__list">
             {scenarios.map(s => (
               <li key={s.id} className={`planning-scenarios__list-row ${activeId === s.id ? "planning-scenarios__list-row--active" : ""}`}>
                 <button type="button" className="planning-scenarios__list-load" onClick={() => loadScenario(s)}>
                   <span className="planning-scenarios__list-name">{s.name}</span>
                   <span className="planning-scenarios__list-meta">
                     {Array.isArray(s.stops) ? s.stops.length : 0} stops · {s.frequency_min} min
                   </span>
                 </button>
                 <button
                   type="button"
                   className="planning-scenarios__stop-remove"
                   onClick={() => remove(s.id)}
                   aria-label={`Delete scenario ${s.name}`}
                 >✕</button>
               </li>
             ))}
           </ul>
         )}
      </div>
    </div>
  );
};
