"""Check D: deflated_sharpe vs Bailey & Lopez de Prado (2014).

B&LdP: SR0 = sqrt(V{SR_n}) * [(1-gamma)*Z(1-1/N) + gamma*Z(1-1/(N*e))]
where V{SR_n} is the CROSS-TRIAL variance of the estimated Sharpes.
Code: sr0 = max_z / sqrt(n_obs - 1), i.e. it hardwires V{SR_n} = 1/(T-1),
the iid-noise null value, with no way to pass the actual trial dispersion.

Test 1 (null calibration): N iid pure-noise strategies, take the best one's
per-bar SR, ask deflated_sharpe. If calibrated, P(DSR > 0.95) ~= 5%.
Test 2 (dispersion case): trials whose true SRs differ (a real sweep:
some params genuinely worse/better in-sample), so V{SR_n} > 1/(T-1).
Compare code's DSR vs the paper's DSR using empirical V{SR_n}.
Test 3 (units footgun): feed the ANNUALIZED sharpe that walk_forward
outputs (the only sharpe this codebase surfaces).
"""
import math
import numpy as np
from quantfirm.metrics import deflated_sharpe, _norm_cdf, _norm_ppf

rng = np.random.default_rng(7)

# --- Test 1: null calibration ---
T, N, reps = 5000, 100, 400
hits = 0
for _ in range(reps):
    x = rng.standard_normal((N, T))
    srs = x.mean(axis=1) / x.std(axis=1, ddof=1)
    best = srs.max()
    if deflated_sharpe(best, n_trials=N, n_obs=T) > 0.95:
        hits += 1
print(f"Test 1 (iid noise, N={N}, T={T}): P(DSR>0.95) = {hits/reps:.3f}  (nominal 0.05)")

# --- Test 2: trials with genuine dispersion ---
# 100 trials, true per-bar SRs spread N(0, 0.03) (some params just worse),
# T=5000 obs. Empirical V{SR_n} then ~ 0.03^2 + 1/T >> 1/T.
reps2, hits_code, hits_paper = 400, 0, 0
emc = 0.5772156649
for _ in range(reps2):
    true_sr = rng.normal(0, 0.03, N)          # true edges are noise around 0
    est = true_sr + rng.standard_normal(N) / math.sqrt(T)
    best = est.max()
    dsr_code = deflated_sharpe(best, n_trials=N, n_obs=T)
    # paper: SR0 with empirical cross-trial variance
    max_z = (1 - emc) * _norm_ppf(1 - 1/N) + emc * _norm_ppf(1 - 1/(N*math.e))
    sr0 = math.sqrt(est.var(ddof=1)) * max_z
    denom = math.sqrt((1 + 0.5*best**2) / (T - 1))
    dsr_paper = _norm_cdf((best - sr0) / denom)
    hits_code += dsr_code > 0.95
    hits_paper += dsr_paper > 0.95
print(f"Test 2 (dispersed trials, all true SR ~ 0 on average):")
print(f"  code   deflated_sharpe: P(pass 0.95 bar) = {hits_code/reps2:.3f}")
print(f"  paper  (empirical V):   P(pass 0.95 bar) = {hits_paper/reps2:.3f}")

# single concrete example
true_sr = rng.normal(0, 0.03, N); est = true_sr + rng.standard_normal(N)/math.sqrt(T)
best = est.max()
print(f"  example: best per-bar SR {best:.4f} -> code DSR "
      f"{deflated_sharpe(best, N, T):.4f}")

# --- Test 3: annualized-units footgun ---
ann_sr = 1.2   # a typical walk_forward 'oos_sharpe' output (annualized)
per_bar = ann_sr / math.sqrt(24*365)
print(f"Test 3: annualized SR {ann_sr} over T=50000 bars, N=500 trials:")
print(f"  fed annualized (as walk_forward reports it): DSR = "
      f"{deflated_sharpe(ann_sr, 500, 50000):.6f}")
print(f"  fed per-bar (correct units):                 DSR = "
      f"{deflated_sharpe(per_bar, 500, 50000):.6f}")
