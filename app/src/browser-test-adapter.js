// Browser-only adapter for the synchronous node:test modules in this folder.
const assert = {
  equal(actual, expected) {
    if (!Object.is(actual, expected)) throw new Error(`Expected ${JSON.stringify(expected)}, received ${JSON.stringify(actual)}`);
  },
  deepEqual(actual, expected) {
    if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error('Objects differ');
  },
  throws(callback) {
    let threw = false;
    try { callback(); } catch { threw = true; }
    if (!threw) throw new Error('Expected an exception');
  },
};

function test(name, callback) {
  const row = document.createElement('li');
  try {
    callback();
    row.textContent = `PASS: ${name}`;
    row.className = 'pass';
  } catch (error) {
    row.textContent = `FAIL: ${name}: ${error.message}`;
    row.className = 'fail';
  }
  document.getElementById('results').append(row);
}

// Both standard imports resolve here; node:test is callable, node:assert is a namespace-like object.
export default Object.assign(test, assert);
