import { fmtFieldName, fmtValue } from "../lib/format";
import type { DiffPreview } from "../lib/types";

export function DiffTable({ diff }: { diff: DiffPreview }) {
  return (
    <table className="diff-table">
      <tbody>
        {diff.fields.map((field) => (
          <tr key={field.field} className={field.changed ? "diff-changed" : ""}>
            <th scope="row">{fmtFieldName(field.field)}</th>
            <td className="diff-current">{fmtValue(field.current)}</td>
            <td className="diff-arrow" aria-hidden>→</td>
            <td className="diff-proposed">{fmtValue(field.proposed)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
