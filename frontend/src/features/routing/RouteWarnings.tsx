import React from 'react';
import { AlertCircle, AlertTriangle, Info, ShieldAlert } from 'lucide-react';
import { RouteAlertItem, RouteVerification } from './types';

interface RouteWarningsProps {
  alerts: RouteAlertItem[];
  verification?: RouteVerification | null;
  warnings?: string[];
}

export const RouteWarnings: React.FC<RouteWarningsProps> = ({
  alerts,
  verification,
  warnings = [],
}) => {
  const hasAlerts = alerts && alerts.length > 0;
  const hasFailures = verification && !verification.is_valid;
  const hasWarnings = warnings && warnings.length > 0;

  if (!hasAlerts && !hasFailures && !hasWarnings) {
    return null;
  }

  return (
    <div className="space-y-3">
      {/* Route Corridor Alerts (from Ingest / Advance) */}
      {hasAlerts && (
        <div className="space-y-2">
          {alerts.map((alert, idx) => {
            const isCritical = alert.severity === 'critical';
            const isWarning = alert.severity === 'warning';

            return (
              <div
                key={`alert-${idx}`}
                className={`p-3 rounded-xl border flex items-start gap-3 text-xs ${
                  isCritical
                    ? 'bg-red-500/15 border-red-500/40 text-red-200'
                    : isWarning
                    ? 'bg-amber-500/15 border-amber-500/40 text-amber-200'
                    : 'bg-sky-500/15 border-sky-500/40 text-sky-200'
                }`}
              >
                {isCritical ? (
                  <ShieldAlert className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                ) : isWarning ? (
                  <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                ) : (
                  <Info className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" />
                )}

                <div className="space-y-0.5 flex-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold tracking-wide uppercase text-[11px]">
                      {alert.alert_type.replace(/_/g, ' ')}
                    </span>
                    <span className="font-mono text-[10px] opacity-80">
                      Segment: {alert.segment_id}
                    </span>
                  </div>
                  <div>{alert.message}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Verification Failures */}
      {hasFailures && (
        <div className="bg-red-950/30 border border-red-500/40 rounded-xl p-3.5 space-y-1.5 text-xs text-red-200">
          <div className="flex items-center gap-2 font-bold text-red-300">
            <AlertCircle className="w-4 h-4 text-red-400" />
            <span>Route Constraint Violations</span>
          </div>
          <ul className="list-disc list-inside space-y-1 text-red-300/90 pl-1">
            {verification.failure_reasons.map((reason, i) => (
              <li key={`fail-${i}`}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {/* General Engine Warnings */}
      {hasWarnings && (
        <div className="bg-amber-950/20 border border-amber-500/30 rounded-xl p-3 space-y-1 text-xs text-amber-200">
          <div className="flex items-center gap-2 font-semibold text-amber-300 text-[11px]">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            <span>Advisory Warnings</span>
          </div>
          <ul className="list-disc list-inside space-y-0.5 text-amber-300/80 text-[11px] pl-1">
            {warnings.map((w, i) => (
              <li key={`warn-${i}`}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
