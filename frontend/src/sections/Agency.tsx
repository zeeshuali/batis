import React from "react";
import { useAgencies } from "../context/AgenciesContext";
import { useUrlState } from "../lib/useUrlState";
import { Spinner, EmptyState } from "../components/primitives";
import "./sections.css";

/** Per-agency drill-down view.  Reached via `#agency?id=<agency_id>`.
 *  Phase B-2 will flesh this out with KPIs, map, and charts; this initial
 *  render is the navigation skeleton so Phase B-1 (URL routing + AppShell
 *  wiring) ships as a working build. */
export const Agency: React.FC = () => {
  const { state, setState } = useUrlState();
  const { byId, loading } = useAgencies();
  const agency = state.agency_id ? byId[state.agency_id] : null;
  const back = () => setState({ ...state, section: "overview", agency_id: null });

  if (loading && !agency && state.agency_id) {
    return <div className="section"><Spinner /></div>;
  }
  if (!state.agency_id || !agency) {
    return (
      <div className="section">
        <div className="section__header">
          <h2 className="section__title">Agency</h2>
          <button type="button" className="export-button" onClick={back}>← Back to Overview</button>
        </div>
        <EmptyState
          message="Pick an agency from Overview → By agency to drill in."
          hint={state.agency_id ? `Unknown agency "${state.agency_id}"` : undefined}
        />
      </div>
    );
  }

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">{agency.agency_name}</h2>
        <span className="section__subtitle">
          {[agency.agency_type, agency.monitored ? "Live RT" : null]
            .filter(Boolean).join(" · ")}
        </span>
        <button type="button" className="export-button" onClick={back}>← Back to Overview</button>
      </div>
      <EmptyState message="Agency drill-down KPIs and charts arrive in Phase B-2." />
    </div>
  );
};
