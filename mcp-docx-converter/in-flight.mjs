// The in-flight serialization key for convert_docx_to_pdf.
//
// docx2pdf.sh resolves the input with realpath and writes the PDF next to the
// REAL file, so a lexical `<abs>.pdf` key misses the destination when the
// input is a symlink. The destination is also commonly a case-insensitive
// Windows/drvfs path, so the key is folded to lower case.
import { realpathSync } from 'node:fs';

export function pdfKey(docxPath) {
  let real = String(docxPath);
  try {
    real = realpathSync(real);
  } catch {
    // Keep the lexical path if the file vanished after the existence check.
  }
  return real.replace(/\.docx$/i, '.pdf').toLowerCase();
}
