/**
 * Shapes and the boxes that store them.
 *
 * @example
 * ```ts
 * const box = Box.of("apple");
 * box.put("pear");
 * ```
 *
 * @module
 */

/** Name given to a shape without one. */
export const DEFAULT_NAME = "shape";

/** Something with sides and a name. */
export interface Shape {
    /** Number of sides. */
    readonly sides: number;
    /** Display name. */
    name: string;
    /**
     * Surface of the shape.
     *
     * @returns the area in square units
     */
    area(): number;
}

/** How a box is closed. */
export enum Lid {
    /** No lid at all. */
    Open,
    /** A lid that snaps shut. */
    Snap = 2,
}

/** Thrown when a box is full. */
export class BoxFullError extends Error {
    /** @param capacity - the capacity that was reached */
    constructor(public readonly capacity: number) {
        super(`box full at ${capacity}`);
    }
}

/**
 * A generic box that stores items in insertion order.
 *
 * @typeParam T - the type of the stored items
 */
export class Box<T> implements Shape {
    /** Most items a box holds. */
    static readonly CAPACITY = 16;
    readonly sides = 6;
    name = DEFAULT_NAME;
    private items: T[];

    /** @param items - the first items */
    constructor(items: T[] = []) {
        this.items = [...items];
    }

    /** A box holding `items`. */
    static of<U>(...items: U[]): Box<U> {
        return new Box(items);
    }

    /** Number of items stored. */
    get size(): number {
        return this.items.length;
    }

    /**
     * Store one item.
     *
     * @param item - the item to store
     * @throws {@link BoxFullError} when the box already holds {@link Box.CAPACITY} items
     */
    put(item: T): void {
        if (this.items.length >= Box.CAPACITY) {
            throw new BoxFullError(Box.CAPACITY);
        }
        this.items.push(item);
    }

    /**
     * A box of `func` applied to every item.
     *
     * @typeParam U - the type of the mapped items
     */
    map<U extends object>(func: (item: T) => U): Box<U> {
        return new Box(this.items.map(func));
    }

    area(): number {
        return this.sides;
    }

    shake(times: number): void {
        this.items.reverse();
        if (times > 1) this.shake(times - 1);
    }

    /** @deprecated Use {@link Box.put} instead. */
    add(item: T): void {
        this.put(item);
    }
}

/** A box that can be sealed. */
export abstract class Crate<T> extends Box<T> {
    /** Seal the crate for shipping. */
    abstract seal(): void;
}

/** A point on the plane. */
export type Point = { x: number; y?: number };

/** Apply `func` to each item, in order. */
export function apply<T, U>(func: (item: T) => U, items: readonly T[]): U[] {
    return items.map(func);
}

/** Multiply value by factor, keeping its type. */
export function scale(value: number, factor: number): number;
/** Multiply two bigints. */
export function scale(value: bigint, factor: bigint): bigint;
export function scale(value: any, factor: any): any {
    return value * factor;
}

/** Helpers for boxes. */
export namespace Boxes {
    /** An empty box. */
    export function empty<T>(): Box<T> {
        return new Box<T>();
    }

    /** Boxes made so far. */
    export let made = 0;
}
