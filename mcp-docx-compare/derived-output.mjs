// The output name docxcompare.sh derives when outputPath is omitted.
//
// It lives in its own module so the MCP server and its regression test compute
// the name with the same code. Keying the server's in-flight map on the input
// pair instead let two calls with the same original and two revised files that
// share a basename write the same redline concurrently.
import { realpathSync } from 'node:fs';
import * as path from 'node:path';

function realOrSelf(p) {
  try {
    return realpathSync(p);
  } catch {
    return p;
  }
}

function stem(p) {
  // Bash's `${ORIG_BASE%.*}`: strip the shortest suffix that starts at the
  // last dot.
  return path.basename(p).replace(/\.[^.]*$/, '');
}

export function derivedOutput(original, revised) {
  const originalReal = realOrSelf(original);
  const revisedReal = realOrSelf(revised);
  return path.join(path.dirname(originalReal),
                   `${stem(originalReal)}-vs-${stem(revisedReal)}-redline.docx`);
}
