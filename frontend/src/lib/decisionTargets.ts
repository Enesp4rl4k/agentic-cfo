/**
 * Where a decision record points, for the objects whose id the browser has to work out itself.
 */

/**
 * The decision-record target of an account question, as the server names it
 * (`account_identity.answer`: the two groups' sorted job ids, the groups sorted, the first id of each, joined by "|").
 */
export function pairTargetId(q: { job_ids_a: string[]; job_ids_b: string[] }): string {
  const sorted = (ids: string[]) => [...ids].sort();
  const before = (x: string[], y: string[]) => {
    for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] < y[i];
    return x.length <= y.length;
  };
  const a = sorted(q.job_ids_a);
  const b = sorted(q.job_ids_b);
  const [left, right] = before(a, b) ? [a, b] : [b, a];
  return `${left[0]}|${right[0]}`;
}

