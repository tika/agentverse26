import privateKeys from './private-keys.json';

/** Keys that only exist in private simulator/evaluator truth. See DATA_DICTIONARY.md layer 3. */
export const PRIVATE_KEYS: ReadonlySet<string> = new Set(privateKeys.keys);

/** Returns the dotted paths of every private key found anywhere in `value`. */
export function findPrivateKeys(value: unknown, path = '$', found: string[] = []): string[] {
  if (Array.isArray(value)) {
    value.forEach((item, i) => findPrivateKeys(item, `${path}[${i}]`, found));
  } else if (value !== null && typeof value === 'object') {
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      if (PRIVATE_KEYS.has(key)) found.push(`${path}.${key}`);
      findPrivateKeys(child, `${path}.${key}`, found);
    }
  }
  return found;
}
