/**
 * Helpers for registries.
 *
 * @module
 */

/**
 * A key-value registry.
 *
 * @typeParam K - the key type
 * @typeParam V - the value type
 */
export class Registry<K, V> {
    private readonly entries = new Map<K, V>();

    /** The value under `key`, or `fallback` when there is none. */
    get(key: K, fallback?: V): V | undefined {
        return this.entries.has(key) ? this.entries.get(key) : fallback;
    }

    /** A decorator-style function that stores its value under `key`. */
    register(key: K): (value: V) => V {
        return (value) => {
            this.entries.set(key, value);
            return value;
        };
    }
}

/** The first item, or `undefined` for an empty iterable. */
export function first<T>(items: Iterable<T>): T | undefined {
    for (const item of items) return item;
    return undefined;
}
