// Minimal line diff — computes a longest common subsequence of the two
// line arrays and emits marks per line so a split-pane diff can tint
// added / removed lines. This is not a real Myers diff; it's O(n·m) LCS
// on line strings, fine for a few hundred lines of SQL.

export interface DiffLine {
  text: string;
  n: number;
  mark: "ctx" | "add" | "del";
}

export interface DiffPair {
  left: DiffLine[];
  right: DiffLine[];
}

export function lineDiff(a: string, b: string): DiffPair {
  const A = a.split("\n");
  const B = b.split("\n");
  const n = A.length;
  const m = B.length;

  // LCS matrix
  const L: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    }
  }

  const left: DiffLine[] = [];
  const right: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      left.push({ text: A[i], n: i + 1, mark: "ctx" });
      right.push({ text: B[j], n: j + 1, mark: "ctx" });
      i++;
      j++;
    } else if (L[i + 1][j] >= L[i][j + 1]) {
      left.push({ text: A[i], n: i + 1, mark: "del" });
      right.push({ text: "", n: 0, mark: "ctx" });
      i++;
    } else {
      left.push({ text: "", n: 0, mark: "ctx" });
      right.push({ text: B[j], n: j + 1, mark: "add" });
      j++;
    }
  }
  while (i < n) {
    left.push({ text: A[i], n: i + 1, mark: "del" });
    right.push({ text: "", n: 0, mark: "ctx" });
    i++;
  }
  while (j < m) {
    left.push({ text: "", n: 0, mark: "ctx" });
    right.push({ text: B[j], n: j + 1, mark: "add" });
    j++;
  }
  return { left, right };
}
