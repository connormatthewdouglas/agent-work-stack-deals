/* Price order for the live GPU badge. Mirrors core.deals.gpu_rate_rank_key:
   reserved last, out-of-stock last, then hourly price, advertiser, gpu.
   Affiliate status is not an input. min_gpus is not an input: singleGpuHeadline
   skips min_gpus above 1 because the engine rank does not.
   isServerlessRate mirrors core.gpu.price_bucket == "serverless" (the word serverless
   in the tier), plus billing_unit "per-second", plus a billing or tier line that says
   per-second or function. headlineEligible is the shared headline rule. The homepage
   and the GPU calculator inline isServerlessRate and headlineEligible from this file. */
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
function isServerlessRate(r) {
  var tier = String(r.tier || "");
  var billing = String(r.billing || "");
  var blob = (billing + " " + tier).toLowerCase();
  if (tier.toLowerCase().indexOf("serverless") >= 0) return true;
  if (r.billing_unit === "per-second") return true;
  return blob.indexOf("per-second") >= 0 || blob.indexOf("per second") >= 0 || blob.indexOf("function") >= 0;
}
function headlineEligible(r) {
  if (!isSingleGpuRate(r)) return false;
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
