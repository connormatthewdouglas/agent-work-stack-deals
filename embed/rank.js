/* Price order for the live GPU badge. Same tuple as core.deals.compare_gpu_prices on this
   branch: reserved last, unresolved flag 0 (pages do not set it), out-of-stock last,
   then hourly price, advertiser, gpu. Affiliate is not an input.
   isServerlessRate ports core/serverless.py rate_reason (SERVERLESS_RE, RATE_FIELDS,
   price_per_second_usd). headlineEligible(r, gpus) is the shared rule; gpus defaults
   to 1. The homepage and the GPU calculator inline these functions from this file.
   When compare_gpu_prices(..., gpus=) from core PR #130 is on main, prefer that API. */
function gpuRateRankKey(r) {
  var a = r.availability;
  var oos = a && a.in_stock === false ? 1 : 0;
  var reserved = r.tier_class === "reserved" ? 1 : 0;
  return [reserved, 0, oos, Number(r.hourly_equiv_usd), r.advertiser || "", r.gpu || ""];
}
function cmpGpuRank(a, b) {
  var ka = gpuRateRankKey(a), kb = gpuRateRankKey(b);
  for (var i = 0; i < ka.length; i++) {
    if (ka[i] < kb[i]) return -1;
    if (ka[i] > kb[i]) return 1;
  }
  return 0;
}
function isSingleGpuRate(r) {
  var n = Number(r.min_gpus);
  return !(n > 1);
}
function minGpusLabel(r) {
  var n = Number(r.min_gpus);
  return n > 1 ? (n + "x GPU minimum") : "";
}
/* core/serverless.py SERVERLESS_RE and RATE_FIELDS. Not a keyword list of our own. */
var SERVERLESS_RE = /serverless|\bflex\b|active[-_ ]worker|per[-_ ]?sec(?:ond)?s?\b|\/\s*sec(?:ond)?\b|scale[-_ ]to[-_ ]zero/i;
var RATE_FIELDS = ["tier", "billing_unit", "billing", "price_basis_label", "price_basis", "tier_class"];
function isServerlessRate(r) {
  var pps = r.price_per_second_usd;
  if (pps !== undefined && pps !== null && pps !== "" && pps !== 0) return true;
  for (var i = 0; i < RATE_FIELDS.length; i++) {
    var v = r[RATE_FIELDS[i]];
    if (typeof v === "string" && SERVERLESS_RE.test(v)) return true;
  }
  return false;
}
function headlineEligible(r, gpus) {
  var limit = (gpus == null || gpus === "") ? 1 : Number(gpus);
  if (!(limit >= 1)) limit = 1;
  var n = Number(r.min_gpus);
  if (!(n >= 1)) n = 1;
  if (n > limit) return false;
  if (r.tier_class === "reserved") return false;
  if (isServerlessRate(r)) return false;
  return true;
}
function rankGpuRates(rows) {
  return (rows || []).slice().sort(cmpGpuRank);
}
function singleGpuHeadline(rows) {
  var rs = (rows || []).filter(headlineEligible);
  rs.sort(cmpGpuRank);
  return rs.length ? rs[0] : null;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    gpuRateRankKey: gpuRateRankKey,
    cmpGpuRank: cmpGpuRank,
    isSingleGpuRate: isSingleGpuRate,
    minGpusLabel: minGpusLabel,
    isServerlessRate: isServerlessRate,
    headlineEligible: headlineEligible,
    rankGpuRates: rankGpuRates,
    singleGpuHeadline: singleGpuHeadline
  };
}
