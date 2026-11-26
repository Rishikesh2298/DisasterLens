import React from "react";
import { AlertTriangle } from "lucide-react";

export const SafetyBanner: React.FC = () => {
  return (
    <div className="bg-amber-950/80 border-b border-amber-600/40 text-amber-200 px-4 py-2.5 text-xs sm:text-sm flex items-center justify-between shadow-sm">
      <div className="flex items-center gap-2 max-w-5xl mx-auto">
        <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
        <span>
          <strong className="font-semibold text-amber-300">
            RESEARCH PROTOTYPE:
          </strong>{" "}
          Results are based on synthetic, computer-generated scenes and do not
          establish real-world disaster performance. Road statuses indicate
          strictly:{" "}
          <em>"No obstruction detected in imagery captured at time T."</em> Not
          certified for navigation or life safety.
        </span>
      </div>
    </div>
  );
};
