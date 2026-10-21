/**
 * UI feature switches decided by the user, not by the install.
 *
 * `visualAnalysis` — R1 (visual analysis). Hidden by the user's decision of
 * 2026-10-20 (D-105) until a deterministic attribution guard (S-1.18.9)
 * removes the residual error measured in R1 runs 1-8: about one report
 * sentence per run that credits the speaker with something only shown on
 * screen. The backend stays. Stills of frames that already exist still show
 * (a real frame cannot misattribute anything); what is hidden is everything
 * that STARTS visual analysis: the run opt-in and on-demand capture. A run or
 * template that carried the option over runs without it while this is off;
 * templates keep their stored setting so it returns intact.
 *
 * A mutable object rather than a constant so tests can exercise both states.
 */
export const featureFlags = {
  visualAnalysis: false,
};
